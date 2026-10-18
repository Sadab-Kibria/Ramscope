import os
try:
    import fcntl
except ImportError:
    fcntl = None
import ctypes
from typing import Optional, List, Dict

# Match C structures from kernel/ramscope.h
class RamscopeRamInfo(ctypes.Structure):
    _fields_ = [
        ("total_ram_bytes", ctypes.c_uint64),
        ("free_ram_bytes", ctypes.c_uint64),
        ("available_ram_bytes", ctypes.c_uint64),
        ("total_pages", ctypes.c_uint64),
        ("free_pages", ctypes.c_uint64),
        ("max_pfn", ctypes.c_uint64),
        ("min_pfn", ctypes.c_uint64),
        ("page_size", ctypes.c_uint32),
        ("_reserved", ctypes.c_uint32),
    ]

class RamscopePfnInfo(ctypes.Structure):
    _fields_ = [
        ("pfn", ctypes.c_uint64),
        ("flags", ctypes.c_uint64),
        ("mapcount", ctypes.c_uint32),
        ("refcount", ctypes.c_uint32),
        ("status", ctypes.c_uint8),
        ("is_slab", ctypes.c_uint8),
        ("is_anon", ctypes.c_uint8),
        ("is_reserved", ctypes.c_uint8),
        ("_reserved", ctypes.c_uint32),
    ]

class RamscopePfnQuery(ctypes.Structure):
    _fields_ = [
        ("start_pfn", ctypes.c_uint64),
        ("count", ctypes.c_uint32),
        ("_reserved", ctypes.c_uint32),
        ("results", ctypes.c_void_p),
    ]

# IOCTL codes (_IOR('R', 1, struct ramscope_ram_info), _IOWR('R', 2, struct ramscope_pfn_query))
# _IOR('R', 1, 56) = 0x80385201 (on 64-bit Linux)
# _IOWR('R', 2, 24) = 0xc0185202
IOC_MAGIC = ord('R')
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2

def _IOC(dir_, type_, nr, size):
    return (
        (dir_ << (_IOC_NRBITS + _IOC_TYPEBITS + _IOC_SIZEBITS)) |
        (type_ << (_IOC_NRBITS + _IOC_SIZEBITS)) |
        (nr << _IOC_SIZEBITS) |
        size
    )

def _IOR(type_, nr, size):
    return _IOC(_IOC_READ, type_, nr, size)

def _IOWR(type_, nr, size):
    return _IOC(_IOC_READ | _IOC_WRITE, type_, nr, size)

RAMSCOPE_IOC_GET_RAM_INFO = _IOR(IOC_MAGIC, 1, ctypes.sizeof(RamscopeRamInfo))
RAMSCOPE_IOC_QUERY_PFNS = _IOWR(IOC_MAGIC, 2, ctypes.sizeof(RamscopePfnQuery))

STATUS_MAP = {
    0: "invalid",
    1: "free",
    2: "used",
    3: "kernel",
    4: "reserved",
}

class KernelModuleClient:
    def __init__(self, device_path: str = "/dev/ramscope"):
        self.device_path = device_path

    def is_available(self) -> bool:
        return fcntl is not None and os.path.exists(self.device_path) and os.access(self.device_path, os.R_OK)

    def get_ram_info(self) -> Optional[Dict]:
        if not self.is_available():
            return None

        try:
            with open(self.device_path, "rb") as fd:
                info = RamscopeRamInfo()
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_GET_RAM_INFO, info)
                if ret == 0:
                    return {
                        "total_ram_bytes": info.total_ram_bytes,
                        "free_ram_bytes": info.free_ram_bytes,
                        "available_ram_bytes": info.available_ram_bytes,
                        "total_pages": info.total_pages,
                        "free_pages": info.free_pages,
                        "max_pfn": info.max_pfn,
                        "min_pfn": info.min_pfn,
                        "page_size": info.page_size,
                    }
        except Exception:
            pass
        return None

    def query_pfns(self, start_pfn: int, count: int) -> Optional[List[Dict]]:
        if not self.is_available() or count <= 0:
            return None

        count = min(count, 65536)
        try:
            with open(self.device_path, "rb") as fd:
                PfnArray = RamscopePfnInfo * count
                results = PfnArray()
                query = RamscopePfnQuery(
                    start_pfn=start_pfn,
                    count=count,
                    _reserved=0,
                    results=ctypes.cast(results, ctypes.c_void_p).value
                )
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_QUERY_PFNS, query)
                if ret == 0:
                    out = []
                    for i in range(count):
                        item = results[i]
                        out.append({
                            "pfn": item.pfn,
                            "flags": item.flags,
                            "mapcount": item.mapcount,
                            "refcount": item.refcount,
                            "status": STATUS_MAP.get(item.status, "unknown"),
                            "is_slab": bool(item.is_slab),
                            "is_anon": bool(item.is_anon),
                            "is_reserved": bool(item.is_reserved),
                        })
                    return out
        except Exception:
            pass
        return None
