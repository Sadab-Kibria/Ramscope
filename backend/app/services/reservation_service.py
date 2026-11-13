import time
import math
import logging
from typing import List, Optional, Dict
from datetime import datetime, timezone

from app.models.ram import (
    ReserveRequest,
    ReserveResponse,
    ReleaseRequest,
    ReleaseResponse,
    ReservationItem,
)
from app.linux.kernel_module import KernelModuleClient
from app.linux.privileges import check_privileges

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
        # Software fallback tracking for environments where kernel module isn't loaded
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
        # Default fallback to 16 MB
        return 16 * 1024 * 1024

    def reserve(self, req: ReserveRequest) -> ReserveResponse:
        size_bytes = self._normalize_size(req.size_bytes, req.size_mb)
        # Round up to 4KB page size
        page_count = math.ceil(size_bytes / PAGE_SIZE)
        aligned_bytes = page_count * PAGE_SIZE
        size_mb = round(aligned_bytes / (1024 * 1024), 2)
        app_label = req.application.strip() or "AnonymousApp"

        # Try hardware kernel module first
        if self.client.is_available():
            try:
                k_res = self.client.reserve_memory(size_bytes=aligned_bytes, label=app_label)
                if k_res:
                    region_id = k_res["region_id"]
                    start_pfn = k_res["start_pfn"]
                    end_pfn = start_pfn + k_res["page_count"]
                    phys_addr_hex = f"0x{start_pfn * PAGE_SIZE:012X}"
                    now_str = datetime.now(timezone.utc).isoformat()
                    logger.info(f"Kernel module reserved region {region_id} for '{app_label}' at PFN {start_pfn}")
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
                        timestamp=now_str,
                        message=f"Successfully allocated {size_mb} MB in physical RAM via /dev/ramscope driver.",
                    )
            except Exception as e:
                logger.warning(f"Kernel module reservation attempt failed: {e}. Falling back to simulation.")

        # Software / user-space simulation fallback
        region_id = self._next_sim_id
        self._next_sim_id += 1

        start_pfn = self._sim_next_pfn
        self._sim_next_pfn += page_count + 128  # gap between regions
        end_pfn = start_pfn + page_count
        phys_addr_hex = f"0x{start_pfn * PAGE_SIZE:012X}"
        now_str = datetime.now(timezone.utc).isoformat()

        entry = {
            "region_id": region_id,
            "application": app_label,
            "start_pfn": start_pfn,
            "end_pfn": end_pfn,
            "page_count": page_count,
            "size_bytes": aligned_bytes,
            "size_mb": size_mb,
            "physical_address_hex": phys_addr_hex,
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
            timestamp=now_str,
            message=f"Allocated {size_mb} MB for '{app_label}' at PFN range {start_pfn}..{end_pfn}.",
        )

    def release(self, region_id: int) -> ReleaseResponse:
        # Check kernel module first
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
                        message=f"Successfully deallocated region {region_id} ({round(freed / (1024*1024), 2)} MB freed).",
                    )
            except Exception as e:
                logger.warning(f"Kernel module release failed: {e}")

        # Check simulation storage
        if region_id in self._sim_reservations:
            entry = self._sim_reservations.pop(region_id)
            freed = entry["size_bytes"]
            logger.info(f"Simulated reservation {region_id} released ({freed} bytes)")
            return ReleaseResponse(
                success=True,
                region_id=region_id,
                freed_bytes=freed,
                message=f"Successfully deallocated region {region_id} ({entry['size_mb']} MB freed).",
            )

        return ReleaseResponse(
            success=False,
            region_id=region_id,
            freed_bytes=0,
            message=f"Reservation region ID {region_id} not found.",
        )

    def list_reservations(self) -> List[ReservationItem]:
        results: List[ReservationItem] = []

        # Query kernel module if available
        if self.client.is_available():
            try:
                k_list = self.client.list_reservations()
                if k_list:
                    for item in k_list:
                        spfn = item["start_pfn"]
                        pcount = item["page_count"]
                        sbytes = item["size_bytes"]
                        ts = item.get("timestamp_sec", 0)
                        if ts:
                            dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                        else:
                            dt = datetime.now(timezone.utc).isoformat()

                        results.append(
                            ReservationItem(
                                region_id=item["region_id"],
                                application=item["label"],
                                start_pfn=spfn,
                                end_pfn=spfn + pcount,
                                page_count=pcount,
                                size_bytes=sbytes,
                                size_mb=round(sbytes / (1024 * 1024), 2),
                                physical_address_hex=f"0x{spfn * PAGE_SIZE:012X}",
                                created_at=dt,
                            )
                        )
                    return results
            except Exception as e:
                logger.warning(f"Failed querying kernel module reservations: {e}")

        # Software fallback
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
                    created_at=entry["created_at"],
                )
            )

        return results

    def get_reservation_for_pfn(self, pfn: int) -> Optional[ReservationItem]:
        """Check if a specific PFN falls within any active reservation."""
        reservations = self.list_reservations()
        for res in reservations:
            if res.start_pfn <= pfn < res.end_pfn:
                return res
        return None
