import math
import logging
from typing import List, Optional, Dict
from datetime import datetime, timezone

from app.models.ram import (
    PfnRangeSpan,
    ReserveRequest,
    ReserveResponse,
    ReleaseResponse,
    ReservationItem,
)
from app.linux.kernel_module import KernelModuleClient, KernelReservationError
from app.linux.proc_meminfo import read_proc_meminfo

logger = logging.getLogger("ramscope.reservation")

PAGE_SIZE = 4096

class ReservationService:
    _instance: Optional["ReservationService"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, device_path: str = "/dev/ramscope"):
        if getattr(self, "_initialized", False):
            return

        self.client = KernelModuleClient(device_path=device_path)
        # Software fallback tracking ONLY for environments where /dev/ramscope isn't loaded
        self._sim_reservations: Dict[int, Dict] = {}
        self._next_sim_id: int = 1
        self._sim_next_pfn: int = 50000
        self._initialized = True
        logger.info("ReservationService initialized")

    def _normalize_size(self, size_bytes: Optional[int], size_mb: Optional[float]) -> int:
        if size_bytes is not None and size_bytes > 0:
            return size_bytes
        if size_mb is not None and size_mb > 0:
            return int(size_mb * 1024 * 1024)
        return 16 * 1024 * 1024

    @staticmethod
    def _build_spans(raw_ranges: List[Dict], fallback_start: int, fallback_count: int) -> List[PfnRangeSpan]:
        if raw_ranges:
            return [
                PfnRangeSpan(
                    start_pfn=int(r["start_pfn"]),
                    end_pfn=int(r["start_pfn"]) + int(r["page_count"]),
                    page_count=int(r["page_count"]),
                )
                for r in raw_ranges
                if int(r.get("page_count", 0)) > 0
            ]
        return [
            PfnRangeSpan(
                start_pfn=fallback_start,
                end_pfn=fallback_start + fallback_count,
                page_count=fallback_count,
            )
        ]

    def reserve(self, req: ReserveRequest) -> ReserveResponse:
        size_bytes = self._normalize_size(req.size_bytes, req.size_mb)
        page_count = math.ceil(size_bytes / PAGE_SIZE)
        aligned_bytes = page_count * PAGE_SIZE
        size_mb = round(aligned_bytes / (1024 * 1024), 2)
        app_label = req.application.strip() or "AnonymousApp"
        now_str = datetime.now(timezone.utc).isoformat()

        # When /dev/ramscope is loaded, ALWAYS use the real kernel allocator (never fake fallback)
        if self.client.is_available():
            try:
                k_res = self.client.reserve_memory(size_bytes=aligned_bytes, label=app_label)
            except KernelReservationError as exc:
                logger.warning(f"Kernel module rejected reservation for '{app_label}': {exc}")
                return ReserveResponse(
                    success=False,
                    region_id=0,
                    application=app_label,
                    start_pfn=0,
                    end_pfn=0,
                    page_count=0,
                    size_bytes=0,
                    size_mb=0.0,
                    physical_address_hex="0x0",
                    ranges=[],
                    timestamp=now_str,
                    message=str(exc),
                )

            if k_res:
                region_id = k_res["region_id"]
                start_pfn = k_res["start_pfn"]
                spans = self._build_spans(k_res.get("ranges", []), start_pfn, k_res["page_count"])
                end_pfn = spans[-1].end_pfn if spans else (start_pfn + k_res["page_count"])
                phys_addr_hex = f"0x{start_pfn * PAGE_SIZE:012X}"
                chunk_note = (
                    "contiguous physical range"
                    if len(spans) <= 1
                    else f"{len(spans)} locked physical blocks"
                )
                logger.info(
                    f"Kernel module reserved region {region_id} for '{app_label}' "
                    f"at PFN {start_pfn}..{end_pfn} ({len(spans)} block(s))"
                )
                return ReserveResponse(
                    success=True,
                    region_id=region_id,
                    application=app_label,
                    start_pfn=start_pfn,
                    end_pfn=end_pfn,
                    page_count=k_res["page_count"],
                    size_bytes=k_res["size_bytes"],
                    size_mb=round(k_res["size_bytes"] / (1024 * 1024), 2),
                    physical_address_hex=phys_addr_hex,
                    ranges=spans,
                    timestamp=now_str,
                    message=f"Locked {size_mb} MB in physical RAM via /dev/ramscope ({chunk_note}).",
                )

            return ReserveResponse(
                success=False,
                region_id=0,
                application=app_label,
                start_pfn=0,
                end_pfn=0,
                page_count=0,
                size_bytes=0,
                size_mb=0.0,
                physical_address_hex="0x0",
                ranges=[],
                timestamp=now_str,
                message="Kernel driver /dev/ramscope did not complete reservation.",
            )

        # Validate against system available RAM before creating a software fallback entry
        meminfo = read_proc_meminfo()
        avail_bytes = int(meminfo.get("MemAvailable", meminfo.get("MemFree", 0)))
        total_bytes = int(meminfo.get("MemTotal", 0))
        sim_used = sum(int(e["size_bytes"]) for e in self._sim_reservations.values())
        if total_bytes > 0 and (aligned_bytes > max(0, avail_bytes - sim_used - int(total_bytes * 0.2))):
            return ReserveResponse(
                success=False,
                region_id=0,
                application=app_label,
                start_pfn=0,
                end_pfn=0,
                page_count=0,
                size_bytes=0,
                size_mb=0.0,
                physical_address_hex="0x0",
                ranges=[],
                timestamp=now_str,
                message="Refused: requested size exceeds safe available RAM margin (20% kept free for OS).",
            )

        # Software simulation fallback (only used when /dev/ramscope is NOT loaded)
        region_id = self._next_sim_id
        self._next_sim_id += 1

        start_pfn = self._sim_next_pfn
        self._sim_next_pfn += page_count + 128
        end_pfn = start_pfn + page_count
        phys_addr_hex = f"0x{start_pfn * PAGE_SIZE:012X}"
        spans = [PfnRangeSpan(start_pfn=start_pfn, end_pfn=end_pfn, page_count=page_count)]

        entry = {
            "region_id": region_id,
            "application": app_label,
            "start_pfn": start_pfn,
            "end_pfn": end_pfn,
            "page_count": page_count,
            "size_bytes": aligned_bytes,
            "size_mb": size_mb,
            "physical_address_hex": phys_addr_hex,
            "ranges": spans,
            "created_at": now_str,
        }
        self._sim_reservations[region_id] = entry

        logger.info(f"Simulated reservation {region_id} created for '{app_label}' (PFNs {start_pfn}..{end_pfn})")

        return ReserveResponse(
            success=True,
            region_id=region_id,
            application=app_label,
            start_pfn=start_pfn,
            end_pfn=end_pfn,
            page_count=page_count,
            size_bytes=aligned_bytes,
            size_mb=size_mb,
            physical_address_hex=phys_addr_hex,
            ranges=spans,
            timestamp=now_str,
            message=f"Simulated {size_mb} MB reservation for '{app_label}' at PFN {start_pfn}..{end_pfn} (/dev/ramscope not loaded).",
        )

    def release(self, region_id: int) -> ReleaseResponse:
        if self.client.is_available():
            try:
                rel = self.client.release_memory(region_id)
                if rel:
                    freed = rel.get("freed_bytes", 0)
                    logger.info(f"Kernel module released region {region_id} ({freed} bytes)")
                    return ReleaseResponse(
                        success=True,
                        region_id=region_id,
                        freed_bytes=freed,
                        message=f"Successfully deallocated region {region_id} ({round(freed / (1024*1024), 2)} MB returned to Linux).",
                    )
                return ReleaseResponse(
                    success=False,
                    region_id=region_id,
                    freed_bytes=0,
                    message=f"Reservation region ID {region_id} not found in /dev/ramscope.",
                )
            except KernelReservationError as exc:
                logger.warning(f"Kernel module release failed: {exc}")
                return ReleaseResponse(
                    success=False,
                    region_id=region_id,
                    freed_bytes=0,
                    message=str(exc),
                )

        if region_id in self._sim_reservations:
            entry = self._sim_reservations.pop(region_id)
            freed = entry["size_bytes"]
            logger.info(f"Simulated reservation {region_id} released ({freed} bytes)")
            return ReleaseResponse(
                success=True,
                region_id=region_id,
                freed_bytes=freed,
                message=f"Successfully deallocated simulated region {region_id} ({entry['size_mb']} MB freed).",
            )

        return ReleaseResponse(
            success=False,
            region_id=region_id,
            freed_bytes=0,
            message=f"Reservation region ID {region_id} not found.",
        )

    def list_reservations(self) -> List[ReservationItem]:
        results: List[ReservationItem] = []

        if self.client.is_available():
            k_list = self.client.list_reservations()
            if k_list is not None:
                for item in k_list:
                    spfn = item["start_pfn"]
                    pcount = item["page_count"]
                    sbytes = item["size_bytes"]
                    ts = item.get("timestamp_sec", 0)
                    dt = (
                        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                        if ts
                        else datetime.now(timezone.utc).isoformat()
                    )
                    spans = self._build_spans(item.get("ranges", []), spfn, pcount)
                    epfn = spans[-1].end_pfn if spans else (spfn + pcount)

                    results.append(
                        ReservationItem(
                            region_id=item["region_id"],
                            application=item["label"],
                            start_pfn=spfn,
                            end_pfn=epfn,
                            page_count=pcount,
                            size_bytes=sbytes,
                            size_mb=round(sbytes / (1024 * 1024), 2),
                            physical_address_hex=f"0x{spfn * PAGE_SIZE:012X}",
                            ranges=spans,
                            created_at=dt,
                        )
                    )
                return results

        for entry in self._sim_reservations.values():
            results.append(
                ReservationItem(
                    region_id=entry["region_id"],
                    application=entry["application"],
                    start_pfn=entry["start_pfn"],
                    end_pfn=entry["end_pfn"],
                    page_count=entry["page_count"],
                    size_bytes=entry["size_bytes"],
                    size_mb=entry["size_mb"],
                    physical_address_hex=entry["physical_address_hex"],
                    ranges=entry.get("ranges", []),
                    created_at=entry["created_at"],
                )
            )

        return results

    def get_reservation_for_pfn(self, pfn: int) -> Optional[ReservationItem]:
        """Check if a specific PFN falls within any active reservation's locked chunks."""
        for res in self.list_reservations():
            spans = res.ranges or [
                PfnRangeSpan(start_pfn=res.start_pfn, end_pfn=res.end_pfn, page_count=res.page_count)
            ]
            for rg in spans:
                if rg.start_pfn <= pfn < rg.end_pfn:
                    return res
        return None
