import os
import struct
from typing import List, Dict, Optional, Tuple
from app.models.ram import ProcessPageEntry, ProcessPagesResponse
from app.linux.kpageflags import KpageflagsReader

PAGE_SIZE = 4096

class PagemapReader:
    def __init__(self, kpageflags_reader: Optional[KpageflagsReader] = None):
        self.kflags = kpageflags_reader or KpageflagsReader()

    def get_process_vmas(self, pid: int) -> List[Tuple[int, int, str, str]]:
        """
        Parses /proc/<pid>/maps to get virtual address ranges.
        Returns list of (start_addr, end_addr, permissions, pathname).
        """
        maps_path = f"/proc/{pid}/maps"
        vmas = []
        if not os.path.exists(maps_path):
            return vmas

        try:
            with open(maps_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        addr_range = parts[0].split("-")
                        if len(addr_range) == 2:
                            start = int(addr_range[0], 16)
                            end = int(addr_range[1], 16)
                            perms = parts[1]
                            pathname = parts[5] if len(parts) >= 6 else ""
                            vmas.append((start, end, perms, pathname))
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            pass
        return vmas

    def get_process_pages(self, pid: int, max_pages: int = 50000) -> ProcessPagesResponse:
        """
        Reads /proc/<pid>/pagemap for all VMAs and returns physical pages.
        """
        pagemap_path = f"/proc/{pid}/pagemap"
        cmdline_path = f"/proc/{pid}/comm"
        
        proc_name = f"pid_{pid}"
        if os.path.exists(cmdline_path):
            try:
                with open(cmdline_path, "r", encoding="utf-8", errors="ignore") as f:
                    proc_name = f.read().strip()
            except Exception:
                pass

        if not os.path.exists(pagemap_path):
            return ProcessPagesResponse(
                pid=pid,
                name=proc_name,
                totalMappedPages=0,
                residentPages=0,
                pfnList=[],
                pages=[],
                error=f"Process /proc/{pid}/pagemap is not accessible. (Process may have exited or permissions are restricted)"
            )

        vmas = self.get_process_vmas(pid)
        if not vmas:
            return ProcessPagesResponse(
                pid=pid,
                name=proc_name,
                totalMappedPages=0,
                residentPages=0,
                pfnList=[],
                pages=[],
                error="Could not read process memory maps"
            )

        entries: List[ProcessPageEntry] = []
        pfn_set = set()
        total_mapped = 0
        resident_count = 0

        try:
            with open(pagemap_path, "rb") as f_pm:
                for start_addr, end_addr, perms, _ in vmas:
                    start_vpage = start_addr // PAGE_SIZE
                    end_vpage = end_addr // PAGE_SIZE
                    vpage_count = end_vpage - start_vpage

                    total_mapped += vpage_count

                    # Seek to start of VMA in pagemap (8 bytes per vpage)
                    try:
                        f_pm.seek(start_vpage * 8)
                        data = f_pm.read(vpage_count * 8)
                    except Exception:
                        continue

                    read_entries = len(data) // 8
                    for i in range(read_entries):
                        vaddr = (start_vpage + i) * PAGE_SIZE
                        entry_val = struct.unpack_from("Q", data, i * 8)[0]

                        # Bit 63: Page Present in RAM
                        is_present = bool(entry_val & (1 << 63))
                        # Bit 62: Page Swapped
                        is_swapped = bool(entry_val & (1 << 62))

                        if is_present:
                            # Bits 0-54: PFN
                            pfn = entry_val & ((1 << 55) - 1)
                            resident_count += 1
                            pfn_set.add(pfn)

                            # Fetch additional flags if within detail limit
                            if len(entries) < max_pages:
                                pfn_info = self.kflags.get_pfn_info(pfn)
                                flags = pfn_info["flags"] if pfn_info else []
                                map_count = pfn_info["mapcount"] if pfn_info else 1
                                is_shared = (map_count > 1)

                                entries.append(ProcessPageEntry(
                                    pfn=pfn,
                                    virtualAddressHex=f"0x{vaddr:012x}",
                                    physicalAddressHex=f"0x{pfn * PAGE_SIZE:012x}",
                                    flags=flags,
                                    mapCount=map_count,
                                    isShared=is_shared,
                                    isSwapped=False,
                                    isPresent=True
                                ))
                        elif is_swapped:
                            if len(entries) < max_pages:
                                entries.append(ProcessPageEntry(
                                    pfn=0,
                                    virtualAddressHex=f"0x{vaddr:012x}",
                                    physicalAddressHex="Swapped",
                                    flags=["Swapped"],
                                    mapCount=0,
                                    isShared=False,
                                    isSwapped=True,
                                    isPresent=False
                                ))
        except PermissionError:
            return ProcessPagesResponse(
                pid=pid,
                name=proc_name,
                totalMappedPages=total_mapped,
                residentPages=resident_count,
                pfnList=sorted(list(pfn_set)),
                pages=entries,
                error="Permission denied accessing /proc/<pid>/pagemap. Elevated privileges (root / CAP_SYS_ADMIN) required."
            )
        except (FileNotFoundError, ProcessLookupError):
            return ProcessPagesResponse(
                pid=pid,
                name=proc_name,
                totalMappedPages=0,
                residentPages=0,
                pfnList=[],
                pages=[],
                error=f"Process {pid} terminated during scan"
            )

        return ProcessPagesResponse(
            pid=pid,
            name=proc_name,
            totalMappedPages=total_mapped,
            residentPages=resident_count,
            pfnList=sorted(list(pfn_set)),
            pages=entries,
            error=None
        )
