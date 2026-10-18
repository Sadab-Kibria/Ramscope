import os
import struct
from typing import List, Dict, Optional, Tuple

# Linux Kernel Page Flags bit definitions from <uapi/linux/kernel-page-flags.h>
KPF_FLAGS_MAP = {
    0: "Locked",
    1: "Error",
    2: "Referenced",
    3: "Uptodate",
    4: "Dirty",
    5: "LRU",
    6: "Active",
    7: "Slab",
    8: "Writeback",
    9: "Reclaim",
    10: "Buddy",
    11: "Mmap",
    12: "Anon",
    13: "SwapCache",
    14: "SwapBacked",
    15: "CompoundHead",
    16: "CompoundTail",
    17: "Huge",
    18: "Unevictable",
    19: "HWPoison",
    20: "NoPage",
    21: "KSM",
    22: "THP",
    23: "Balloon",
    24: "ZeroPage",
    25: "Idle",
    26: "PgTable",
    32: "Reserved",
}

class KpageflagsReader:
    def __init__(self):
        self.kpageflags_path = "/proc/kpageflags"
        self.kpagecount_path = "/proc/kpagecount"

    def is_available(self) -> bool:
        return os.path.exists(self.kpageflags_path) and os.access(self.kpageflags_path, os.R_OK)

    def decode_flags(self, raw_flags: int) -> List[str]:
        """Convert a 64-bit integer page flag into human-readable strings."""
        names = []
        for bit, name in KPF_FLAGS_MAP.items():
            if raw_flags & (1 << bit):
                names.append(name)
        return names

    def classify_page(self, raw_flags: int, mapcount: int) -> Tuple[str, bool, bool, bool, bool]:
        """
        Classifies page into 'free', 'used', 'kernel', 'reserved'.
        Returns (status_category, is_kernel, is_anon, is_slab, is_reserved).
        """
        # Bit 10: Buddy (free memory in the kernel buddy allocator)
        is_buddy = bool(raw_flags & (1 << 10))
        # Bit 7: Slab (kernel slab allocator)
        is_slab = bool(raw_flags & (1 << 7))
        # Bit 26: Page table allocation
        is_pgtable = bool(raw_flags & (1 << 26))
        # Bit 32: Reserved page
        is_reserved = bool(raw_flags & (1 << 32))
        # Bit 12: Anonymous page (user heap/stack/etc.)
        is_anon = bool(raw_flags & (1 << 12))
        # Bit 11: Mmap / file-backed
        is_mmap = bool(raw_flags & (1 << 11))
        # Bit 20: NoPage (non-existent RAM or unpopulated)
        is_nopage = bool(raw_flags & (1 << 20))

        if is_nopage or (raw_flags == 0 and mapcount == 0 and is_reserved):
            return "reserved", False, False, False, True

        if is_buddy or (raw_flags == 0 and mapcount == 0):
            return "free", False, False, False, False

        if is_reserved:
            return "reserved", False, False, False, True

        if is_slab or is_pgtable:
            return "kernel", True, False, is_slab, False

        if is_anon or is_mmap or mapcount > 0:
            return "used", False, is_anon, False, False

        # If has active flags or refcount
        if raw_flags != 0:
            return "used", False, is_anon, False, False

        return "free", False, False, False, False

    def get_pfn_info(self, pfn: int) -> Optional[Dict]:
        """Read 64-bit flag and mapcount for a single PFN."""
        if not self.is_available():
            return None

        flags = 0
        mapcount = 0
        try:
            with open(self.kpageflags_path, "rb") as f:
                f.seek(pfn * 8)
                data = f.read(8)
                if len(data) == 8:
                    flags = struct.unpack("Q", data)[0]

            if os.path.exists(self.kpagecount_path) and os.access(self.kpagecount_path, os.R_OK):
                with open(self.kpagecount_path, "rb") as f:
                    f.seek(pfn * 8)
                    data = f.read(8)
                    if len(data) == 8:
                        mapcount = struct.unpack("Q", data)[0]

            status, is_kernel, is_anon, is_slab, is_reserved = self.classify_page(flags, mapcount)

            return {
                "pfn": pfn,
                "flags": self.decode_flags(flags),
                "raw_flags": flags,
                "mapcount": mapcount,
                "status": status,
                "is_kernel": is_kernel,
                "is_anon": is_anon,
                "is_slab": is_slab,
                "is_reserved": is_reserved,
            }
        except Exception:
            return None

    def read_pfn_range_summary(self, start_pfn: int, count: int, sample_rate: int = 1) -> Dict:
        """
        Reads a batch of PFNs to compute category counts for block aggregation.
        """
        free_cnt = 0
        used_cnt = 0
        kernel_cnt = 0
        reserved_cnt = 0

        if not self.is_available() or count <= 0:
            return {
                "status": "reserved",
                "freeCount": 0,
                "usedCount": 0,
                "kernelCount": 0,
                "reservedCount": count,
            }

        try:
            with open(self.kpageflags_path, "rb") as f_flags:
                f_flags.seek(start_pfn * 8)
                # Read up to count * 8 bytes
                bytes_to_read = min(count * 8, 512 * 1024)  # 512 KB max per read
                raw_bytes = f_flags.read(bytes_to_read)
                actual_pages = len(raw_bytes) // 8

                if actual_pages == 0:
                    return {
                        "status": "reserved",
                        "freeCount": 0,
                        "usedCount": 0,
                        "kernelCount": 0,
                        "reservedCount": count,
                    }

                step = max(1, sample_rate)
                samples = 0
                for i in range(0, actual_pages, step):
                    val = struct.unpack_from("Q", raw_bytes, i * 8)[0]
                    status, _, _, _, _ = self.classify_page(val, 0)
                    if status == "free":
                        free_cnt += 1
                    elif status == "kernel":
                        kernel_cnt += 1
                    elif status == "reserved":
                        reserved_cnt += 1
                    else:
                        used_cnt += 1
                    samples += 1

                # Extrapolate to the full count
                if samples > 0:
                    scale = count / samples
                    free_cnt = int(free_cnt * scale)
                    used_cnt = int(used_cnt * scale)
                    kernel_cnt = int(kernel_cnt * scale)
                    reserved_cnt = int(reserved_cnt * scale)

        except Exception:
            reserved_cnt = count

        # Determine aggregate status
        if free_cnt > count * 0.8:
            overall_status = "free"
        elif used_cnt > count * 0.8:
            overall_status = "used"
        elif kernel_cnt > count * 0.8:
            overall_status = "kernel"
        elif reserved_cnt > count * 0.8:
            overall_status = "reserved"
        else:
            overall_status = "mixed"

        return {
            "status": overall_status,
            "freeCount": free_cnt,
            "usedCount": used_cnt,
            "kernelCount": kernel_cnt,
            "reservedCount": reserved_cnt,
        }
