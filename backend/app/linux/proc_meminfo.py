import os
import sys
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger("ramscope.proc_meminfo")

def get_system_page_size() -> int:
    """
    Returns the real system page size in bytes using os.sysconf or ctypes sysconf.
    """
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names:
            return os.sysconf("SC_PAGE_SIZE")
    except Exception:
        pass

    try:
        import mmap
        return mmap.PAGESIZE
    except Exception:
        pass

    return 4096

def get_system_phys_pages() -> int:
    """
    Returns the total number of physical pages using os.sysconf if available.
    """
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            pages = os.sysconf("SC_PHYS_PAGES")
            if pages > 0:
                return pages
    except Exception:
        pass
    return 0

def read_proc_meminfo() -> Dict[str, int]:
    """
    Parses /proc/meminfo and returns memory statistics in bytes.
    If /proc/meminfo is inaccessible, uses psutil to obtain real system RAM.
    """
    meminfo: Dict[str, int] = {}

    if os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val_parts = parts[1].strip().split()
                        if val_parts:
                            try:
                                num = int(val_parts[0])
                                # If unit is kB (typical in Linux meminfo), convert to bytes
                                if len(val_parts) > 1 and val_parts[1].lower() == "kb":
                                    num *= 1024
                                meminfo[key] = num
                            except ValueError:
                                continue
            if "MemTotal" in meminfo and meminfo["MemTotal"] > 0:
                return meminfo
        except Exception as e:
            logger.warning(f"Could not read /proc/meminfo directly: {e}")

    # Fallback to psutil for real hardware RAM query
    try:
        import psutil
        v = psutil.virtual_memory()
        meminfo["MemTotal"] = int(v.total)
        meminfo["MemFree"] = int(v.free)
        meminfo["MemAvailable"] = int(v.available)
        meminfo["Cached"] = int(getattr(v, "cached", 0))
        meminfo["Buffers"] = int(getattr(v, "buffers", 0))
        meminfo["Slab"] = int(getattr(v, "slab", 0))
        meminfo["SReclaimable"] = int(getattr(v, "slab", 0) // 2)
        meminfo["Shmem"] = int(getattr(v, "shared", 0))
    except Exception as e:
        logger.error(f"Failed to query system RAM via psutil: {e}")

    return meminfo

def get_max_physical_pfn(total_pages: int, page_size: int) -> int:
    """
    Determines max physical PFN from /proc/iomem or calculated total_pages.
    """
    max_addr = 0
    if os.path.exists("/proc/iomem"):
        try:
            with open("/proc/iomem", "r", encoding="utf-8") as f:
                for line in f:
                    if "System RAM" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            addrs = parts[0].strip().split("-")
                            if len(addrs) == 2:
                                end_addr = int(addrs[1], 16)
                                if end_addr > max_addr:
                                    max_addr = end_addr
        except Exception:
            pass

    if max_addr > 0 and page_size > 0:
        return max_addr // page_size

    if total_pages > 0:
        return total_pages

    return 1048576  # Default fallback 4GB / 4KB
