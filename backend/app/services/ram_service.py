import logging
from app.models.ram import RamInfoResponse
from app.linux.proc_meminfo import (
    read_proc_meminfo,
    get_system_page_size,
    get_system_phys_pages,
    get_max_physical_pfn,
)
from app.linux.kernel_module import KernelModuleClient
from app.linux.kpageflags import KpageflagsReader

logger = logging.getLogger("ramscope.ram_service")

class RamService:
    def __init__(self):
        self.kmod = KernelModuleClient()
        self.kflags = KpageflagsReader()

    def get_ram_info(self) -> RamInfoResponse:
        page_size = get_system_page_size()
        is_privileged = self.kmod.is_available() or self.kflags.is_available()

        # Try kernel module first if available
        if self.kmod.is_available():
            try:
                kinfo = self.kmod.get_ram_info()
                if kinfo and kinfo.get("total_ram_bytes", 0) > 0:
                    total = int(kinfo["total_ram_bytes"])
                    avail = int(kinfo["available_ram_bytes"])
                    free = int(kinfo["free_ram_bytes"])
                    used = max(0, total - avail)
                    p_size = int(kinfo["page_size"]) or page_size
                    total_pages = int(kinfo["total_pages"]) or (total // p_size)
                    max_pfn = int(kinfo["max_pfn"]) or total_pages
                    usage_pct = (used / total * 100.0) if total > 0 else 0.0

                    meminfo = read_proc_meminfo()
                    cached = int(meminfo.get("Cached", 0))
                    buffers = int(meminfo.get("Buffers", 0))
                    slab = int(meminfo.get("Slab", 0))
                    kernel_cache = slab + buffers + cached

                    return RamInfoResponse(
                        total_bytes=total,
                        used_bytes=used,
                        available_bytes=avail,
                        free_bytes=free,
                        cached_bytes=cached,
                        buffers_bytes=buffers,
                        slab_bytes=slab,
                        kernel_cache_bytes=kernel_cache,
                        page_size=p_size,
                        total_pages=total_pages,
                        max_pfn=max_pfn,
                        usage_percentage=round(usage_pct, 2),
                        privileged=True,
                    )
            except Exception as e:
                logger.warning(f"Kernel module query failed: {e}. Falling back to /proc/meminfo")

        # Standard Linux /proc/meminfo & OS system statistics
        meminfo = read_proc_meminfo()
        total = int(meminfo.get("MemTotal", 0))
        free = int(meminfo.get("MemFree", 0))
        avail = int(meminfo.get("MemAvailable", free))
        cached = int(meminfo.get("Cached", 0))
        buffers = int(meminfo.get("Buffers", 0))
        slab = int(meminfo.get("Slab", 0))

        # Fallback if total is still not detected
        if total <= 0:
            phys_pages = get_system_phys_pages()
            if phys_pages > 0:
                total = phys_pages * page_size
                avail = free = int(total * 0.5)

        used = max(0, total - avail)
        total_pages = (total // page_size) if (total > 0 and page_size > 0) else 0
        max_pfn = get_max_physical_pfn(total_pages, page_size)
        usage_pct = (used / total * 100.0) if total > 0 else 0.0
        kernel_cache = slab + buffers + cached

        logger.info(f"RAM statistics: Total={total} Bytes ({total_pages} pages), Used={used} Bytes, Avail={avail} Bytes, PageSize={page_size}")

        return RamInfoResponse(
            total_bytes=total,
            used_bytes=used,
            available_bytes=avail,
            free_bytes=free,
            cached_bytes=cached,
            buffers_bytes=buffers,
            slab_bytes=slab,
            kernel_cache_bytes=kernel_cache,
            page_size=page_size,
            total_pages=total_pages,
            max_pfn=max_pfn,
            usage_percentage=round(usage_pct, 2),
            privileged=is_privileged,
        )
