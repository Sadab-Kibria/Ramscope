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
from app.services.reservation_service import ReservationService

logger = logging.getLogger("ramscope.page_service")

class PageService:
    def __init__(self):
        self.kflags = KpageflagsReader()
        self.kmod = KernelModuleClient()
        self.pagemap_reader = PagemapReader(self.kflags)
        self.reservation_service = ReservationService()

    def _summarize_block_via_kmod(self, b_start: int, b_count: int) -> Optional[Dict]:
        """Query or sample PFNs via /dev/ramscope so the map works even without /proc/kpageflags."""
        if b_count <= 0:
            return None

        if b_count <= 2048:
            items = self.kmod.query_pfns(b_start, b_count)
            scale = 1.0
        else:
            # Sample 4 evenly-spaced slices of 16 pages across the block
            slices = 4
            per_slice = 16
            items = []
            step = max(per_slice, b_count // slices)
            for s in range(slices):
                pos = b_start + min(s * step, max(0, b_count - per_slice))
                part = self.kmod.query_pfns(pos, min(per_slice, b_start + b_count - pos))
                if part:
                    items.extend(part)
            scale = (b_count / len(items)) if items else 0.0

        if not items:
            return None

        f_c = int(sum(1 for x in items if x["status"] == "free") * scale)
        u_c = int(sum(1 for x in items if x["status"] == "used") * scale)
        k_c = int(sum(1 for x in items if x["status"] == "kernel") * scale)
        r_c = int(sum(1 for x in items if x["status"] in ("reserved", "invalid")) * scale)
        a_c = int(sum(1 for x in items if x["status"] == "allocated") * scale)

        if a_c >= b_count * 0.5:
            st = "allocated"
        elif f_c > b_count * 0.8:
            st = "free"
        elif u_c > b_count * 0.8:
            st = "used"
        elif k_c > b_count * 0.8:
            st = "kernel"
        elif r_c > b_count * 0.8:
            st = "reserved"
        else:
            st = "mixed"

        return {
            "status": st,
            "freeCount": f_c,
            "usedCount": u_c,
            "kernelCount": k_c,
            "reservedCount": r_c,
            "allocatedCount": a_c,
            "unknownCount": 0,
        }

    @staticmethod
    def _overlap_allocated_pages(b_start: int, b_end: int, active_res: List) -> int:
        alloc_count = 0
        for r in active_res:
            spans = getattr(r, "ranges", None) or []
            if spans:
                for rg in spans:
                    ov_s = max(b_start, rg.start_pfn)
                    ov_e = min(b_end, rg.end_pfn)
                    if ov_e > ov_s:
                        alloc_count += (ov_e - ov_s)
            else:
                ov_s = max(b_start, r.start_pfn)
                ov_e = min(b_end, r.end_pfn)
                if ov_e > ov_s:
                    alloc_count += (ov_e - ov_s)
        return alloc_count

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

        max_pfn = 0
        if self.kmod.is_available():
            kinfo = self.kmod.get_ram_info()
            if kinfo:
                max_pfn = int(kinfo.get("max_pfn") or 0)
                if int(kinfo.get("total_pages") or 0) > 0:
                    total_pages = int(kinfo["total_pages"])

        if max_pfn <= 0:
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
        active_res = self.reservation_service.list_reservations()

        logger.info(
            f"Generating physical page map: range=[{start}, {end}], totalSpan={total_span}, "
            f"resolution={resolution}, blockSize={block_size}, privileged={is_privileged}, "
            f"activeReservations={len(active_res)}"
        )

        if is_privileged:
            # Privileged path: inspect real kernel page frames
            for b in range(num_blocks):
                b_start = start + b * block_size
                b_end = min(end, b_start + block_size)
                b_count = b_end - b_start

                if b_count <= 0:
                    continue

                summary = None
                if use_kmod and (b_count <= 2048 or not self.kflags.is_available()):
                    summary = self._summarize_block_via_kmod(b_start, b_count)

                if summary is None:
                    sample_rate = max(1, b_count // 32)
                    summary = self.kflags.read_pfn_range_summary(b_start, b_count, sample_rate=sample_rate)
                    summary["allocatedCount"] = 0

                # Overlay exact reservation chunk counts so small reservations inside big buckets are never missed
                exact_alloc = self._overlap_allocated_pages(b_start, b_end, active_res)
                alloc_count = max(summary.get("allocatedCount", 0), exact_alloc)

                st = summary["status"]
                if alloc_count > 0:
                    if alloc_count >= b_count * 0.5:
                        st = "allocated"
                    elif st != "allocated":
                        st = "mixed"

                blocks.append(PageBlockSummary(
                    start_pfn=b_start,
                    end_pfn=b_end,
                    page_count=b_count,
                    status=st,
                    free_count=summary["freeCount"],
                    used_count=summary["usedCount"],
                    kernel_count=summary["kernelCount"],
                    reserved_count=summary["reservedCount"],
                    allocated_count=alloc_count,
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

                # Check project reservations
                alloc_count = self._overlap_allocated_pages(b_start, b_end, active_res)

                fraction = b / num_blocks
                if alloc_count >= b_count * 0.5:
                    st = "allocated"
                    k_c, u_c, f_c = 0, 0, 0
                elif fraction < kernel_ratio:
                    st = "kernel"
                    k_c, u_c, f_c = b_count, 0, 0
                elif fraction < (kernel_ratio + used_ratio):
                    st = "used"
                    k_c, u_c, f_c = 0, b_count, 0
                else:
                    st = "free"
                    k_c, u_c, f_c = 0, 0, b_count

                if alloc_count > 0 and st != "allocated":
                    st = "mixed"

                blocks.append(PageBlockSummary(
                    start_pfn=b_start,
                    end_pfn=b_end,
                    page_count=b_count,
                    status=st,
                    free_count=f_c,
                    used_count=u_c,
                    kernel_count=k_c,
                    reserved_count=0,
                    allocated_count=alloc_count,
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

        # Check if PFN is allocated by RAMScope project reservation
        res_item = self.reservation_service.get_reservation_for_pfn(pfn)
        if res_item:
            ref_cnt = 1
            map_cnt = 0
            raw_hex = "0x0"
            flags_list = ["ALLOCATED", "PROJECT_RESERVED"]
            if self.kmod.is_available():
                q_res = self.kmod.query_pfns(pfn, 1)
                if q_res:
                    ref_cnt = int(q_res[0]["refcount"])
                    map_cnt = int(q_res[0]["mapcount"])
                    raw_hex = f"0x{q_res[0]['flags']:x}"
                    k_decoded = self.kflags.decode_flags(q_res[0]["flags"])
                    for fl in k_decoded:
                        if fl not in flags_list:
                            flags_list.append(fl)

            return PageDetailResponse(
                pfn=pfn,
                physical_address_hex=f"0x{pfn * page_size:012x}",
                status="allocated",
                page_size=page_size,
                map_count=map_cnt,
                ref_count=ref_cnt,
                flags=flags_list,
                raw_flags_hex=raw_hex,
                is_kernel=False,
                is_anon=False,
                is_slab=False,
                is_reserved=False,
                is_allocated=True,
                allocated_by=res_item.application,
                mapped_processes=[
                    ProcessMappingSummary(
                        pid=-int(res_item.region_id),
                        name=f"{res_item.application} [Allocated #{res_item.region_id}]",
                    )
                ],
                note=f"Locked in kernel RAM by RAMScope for '{res_item.application}' (Region #{res_item.region_id}, {res_item.size_mb} MB)",
            )

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
