import os
import logging
from typing import List, Dict, Optional
from app.models.ram import (
    PagesMapResponse,
    PageBlockSummary,
    PageDetailResponse,
    ProcessMappingSummary
)
from app.linux.kpageflags import KpageflagsReader
from app.linux.proc_meminfo import (
    get_system_page_size,
    read_proc_meminfo,
    get_max_physical_pfn,
)
from app.linux.kernel_module import KernelModuleClient
from app.linux.pagemap import PagemapReader

logger = logging.getLogger("ramscope.page_service")

class PageService:
    def __init__(self):
        self.kflags = KpageflagsReader()
        self.kmod = KernelModuleClient()
        self.pagemap_reader = PagemapReader(self.kflags)

    def get_pages_map(
        self,
        start_pfn: Optional[int] = None,
        count: Optional[int] = None,
        resolution: int = 512
    ) -> PagesMapResponse:
        page_size = get_system_page_size()
        meminfo = read_proc_meminfo()
        total_bytes = int(meminfo.get("MemTotal", 0))
        total_pages = (total_bytes // page_size) if (total_bytes > 0 and page_size > 0) else 1048576

        max_pfn = get_max_physical_pfn(total_pages, page_size)
        if max_pfn <= 0:
            max_pfn = total_pages

        start = max(0, start_pfn if start_pfn is not None else 0)
        total_requested = count if (count is not None and count > 0) else (max_pfn - start)
        end = min(max_pfn, start + total_requested)
        total_span = max(1, end - start)

        num_blocks = min(resolution, total_span)
        if num_blocks <= 0:
            num_blocks = 1

        block_size = max(1, total_span // num_blocks)
        blocks: List[PageBlockSummary] = []

        is_privileged = self.kmod.is_available() or self.kflags.is_available()
        use_kmod = self.kmod.is_available()

        logger.info(
            f"Generating physical page map: range=[{start}, {end}], totalSpan={total_span}, "
            f"resolution={resolution}, blockSize={block_size}, privileged={is_privileged}"
        )

        if is_privileged:
            # Privileged path: inspect real kernel page frames
            for b in range(num_blocks):
                b_start = start + b * block_size
                b_end = min(end, b_start + block_size)
                b_count = b_end - b_start

                if b_count <= 0:
                    continue

                if use_kmod and b_count <= 64:
                    items = self.kmod.query_pfns(b_start, b_count)
                    if items:
                        f_c = sum(1 for x in items if x["status"] == "free")
                        u_c = sum(1 for x in items if x["status"] == "used")
                        k_c = sum(1 for x in items if x["status"] == "kernel")
                        r_c = sum(1 for x in items if x["status"] in ("reserved", "invalid"))

                        if f_c > b_count * 0.8:
                            st = "free"
                        elif u_c > b_count * 0.8:
                            st = "used"
                        elif k_c > b_count * 0.8:
                            st = "kernel"
                        elif r_c > b_count * 0.8:
                            st = "reserved"
                        else:
                            st = "mixed"

                        summary = {
                            "status": st,
                            "freeCount": f_c,
                            "usedCount": u_c,
                            "kernelCount": k_c,
                            "reservedCount": r_c,
                            "unknownCount": 0,
                        }
                    else:
                        sample_rate = max(1, b_count // 32)
                        summary = self.kflags.read_pfn_range_summary(b_start, b_count, sample_rate=sample_rate)
                else:
                    sample_rate = max(1, b_count // 32)
                    summary = self.kflags.read_pfn_range_summary(b_start, b_count, sample_rate=sample_rate)

                blocks.append(PageBlockSummary(
                    start_pfn=b_start,
                    end_pfn=b_end,
                    page_count=b_count,
                    status=summary["status"],
                    free_count=summary["freeCount"],
                    used_count=summary["usedCount"],
                    kernel_count=summary["kernelCount"],
                    reserved_count=summary["reservedCount"],
                    unknown_count=summary.get("unknownCount", 0),
                    start_address_hex=f"0x{b_start * page_size:012x}",
                    end_address_hex=f"0x{b_end * page_size:012x}",
                ))
        else:
            # Unprivileged mode: derive realistic memory layout partitions from real /proc/meminfo
            used_bytes = max(0, total_bytes - int(meminfo.get("MemAvailable", int(meminfo.get("MemFree", 0)))))
            free_bytes = int(meminfo.get("MemFree", 0))
            kernel_bytes = int(meminfo.get("Slab", 0)) + int(meminfo.get("Buffers", 0))

            used_ratio = (used_bytes / total_bytes) if total_bytes > 0 else 0.5
            kernel_ratio = (kernel_bytes / total_bytes) if total_bytes > 0 else 0.1
            free_ratio = (free_bytes / total_bytes) if total_bytes > 0 else 0.4

            for b in range(num_blocks):
                b_start = start + b * block_size
                b_end = min(end, b_start + block_size)
                b_count = b_end - b_start

                if b_count <= 0:
                    continue

                fraction = b / num_blocks
                if fraction < kernel_ratio:
                    st = "kernel"
                    k_c, u_c, f_c = b_count, 0, 0
                elif fraction < (kernel_ratio + used_ratio):
                    st = "used"
                    k_c, u_c, f_c = 0, b_count, 0
                else:
                    st = "free"
                    k_c, u_c, f_c = 0, 0, b_count

                blocks.append(PageBlockSummary(
                    start_pfn=b_start,
                    end_pfn=b_end,
                    page_count=b_count,
                    status=st,
                    free_count=f_c,
                    used_count=u_c,
                    kernel_count=k_c,
                    reserved_count=0,
                    unknown_count=0,
                    start_address_hex=f"0x{b_start * page_size:012x}",
                    end_address_hex=f"0x{b_end * page_size:012x}",
                ))

        return PagesMapResponse(
            page_size=page_size,
            total_pages=total_pages,
            max_pfn=max_pfn,
            start_pfn=start,
            end_pfn=end,
            resolution=resolution,
            bucket_size=block_size,
            block_count=len(blocks),
            privileged=is_privileged,
            pages=blocks,
        )

    def find_processes_mapping_pfn(self, target_pfn: int, max_scan_pids: int = 40) -> List[ProcessMappingSummary]:
        mapped: List[ProcessMappingSummary] = []
        page_size = get_system_page_size()
        if not os.path.exists("/proc"):
            return mapped

        pid_dirs = [int(p) for p in os.listdir("/proc") if p.isdigit()]
        scanned = 0

        for pid in pid_dirs:
            if scanned >= max_scan_pids:
                break

            pagemap_path = f"/proc/{pid}/pagemap"
            if not os.path.exists(pagemap_path):
                continue

            vmas = self.pagemap_reader.get_process_vmas(pid)
            if not vmas:
                continue

            scanned += 1
            found = False

            try:
                with open(pagemap_path, "rb") as f_pm:
                    for start_addr, end_addr, _, _ in vmas:
                        start_vpage = start_addr // page_size
                        end_vpage = end_addr // page_size
                        vpage_cnt = end_vpage - start_vpage

                        f_pm.seek(start_vpage * 8)
                        data = f_pm.read(vpage_cnt * 8)
                        import struct
                        for i in range(len(data) // 8):
                            entry_val = struct.unpack_from("Q", data, i * 8)[0]
                            if entry_val & (1 << 63):
                                pfn = entry_val & ((1 << 55) - 1)
                                if pfn == target_pfn:
                                    proc_name = f"PID {pid}"
                                    comm_path = f"/proc/{pid}/comm"
                                    if os.path.exists(comm_path):
                                        try:
                                            with open(comm_path, "r", encoding="utf-8", errors="ignore") as fc:
                                                proc_name = fc.read().strip()
                                        except Exception:
                                            pass
                                    mapped.append(ProcessMappingSummary(pid=pid, name=proc_name))
                                    found = True
                                    break
                        if found:
                            break
            except Exception:
                continue

        return mapped

    def get_page_detail(self, pfn: int) -> PageDetailResponse:
        page_size = get_system_page_size()
        logger.info(f"Inspecting single physical page frame PFN={pfn}")

        if self.kmod.is_available():
            q_res = self.kmod.query_pfns(pfn, 1)
            if q_res and len(q_res) > 0:
                item = q_res[0]
                flags_decoded = self.kflags.decode_flags(item["flags"])
                mapped_procs = []
                if item["mapcount"] > 0:
                    mapped_procs = self.find_processes_mapping_pfn(pfn)

                note = None
                if not mapped_procs and item["mapcount"] == 0:
                    note = "No user-space process mapping identified"

                return PageDetailResponse(
                    pfn=pfn,
                    physical_address_hex=f"0x{pfn * page_size:012x}",
                    status=item["status"],
                    page_size=page_size,
                    map_count=item["mapcount"],
                    ref_count=item["refcount"],
                    flags=flags_decoded,
                    raw_flags_hex=f"0x{item['flags']:x}",
                    is_kernel=(item["status"] == "kernel"),
                    is_anon=item["is_anon"],
                    is_slab=item["is_slab"],
                    is_reserved=item["is_reserved"],
                    mapped_processes=mapped_procs,
                    note=note,
                )

        info = self.kflags.get_pfn_info(pfn)
        if not info:
            return PageDetailResponse(
                pfn=pfn,
                physical_address_hex=f"0x{pfn * page_size:012x}",
                status="unknown",
                page_size=page_size,
                map_count=0,
                ref_count=0,
                flags=[],
                raw_flags_hex="0x0",
                is_kernel=False,
                is_anon=False,
                is_slab=False,
                is_reserved=False,
                mapped_processes=[],
                note="Basic memory information available. Run the backend with elevated privileges for detailed physical-frame inspection.",
            )

        mapped_procs = []
        if info["mapcount"] > 0:
            mapped_procs = self.find_processes_mapping_pfn(pfn)

        note = None
        if not mapped_procs and info["mapcount"] == 0:
            note = "No user-space process mapping identified"

        return PageDetailResponse(
            pfn=pfn,
            physical_address_hex=f"0x{pfn * page_size:012x}",
            status=info["status"],
            page_size=page_size,
            map_count=info["mapcount"],
            ref_count=0,
            flags=info["flags"],
            raw_flags_hex=f"0x{info['raw_flags']:x}",
            is_kernel=info["is_kernel"],
            is_anon=info["is_anon"],
            is_slab=info["is_slab"],
            is_reserved=info["is_reserved"],
            mapped_processes=mapped_procs,
            note=note,
        )
