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

RAMSCOPE_MAX_RESERVATIONS = 32
RAMSCOPE_LABEL_LEN = 32

class RamscopeReservationReq(ctypes.Structure):
    _fields_ = [
        ("size_bytes", ctypes.c_uint64),
        ("label", ctypes.c_char * RAMSCOPE_LABEL_LEN),
        ("region_id", ctypes.c_uint32),
        ("start_pfn", ctypes.c_uint64),
        ("page_count", ctypes.c_uint64),
        ("status", ctypes.c_uint32),
    ]

class RamscopeReleaseReq(ctypes.Structure):
    _fields_ = [
        ("region_id", ctypes.c_uint32),
        ("freed_bytes", ctypes.c_uint64),
        ("status", ctypes.c_uint32),
    ]

class RamscopeReservationEntry(ctypes.Structure):
    _fields_ = [
        ("region_id", ctypes.c_uint32),
        ("start_pfn", ctypes.c_uint64),
        ("page_count", ctypes.c_uint64),
        ("size_bytes", ctypes.c_uint64),
        ("label", ctypes.c_char * RAMSCOPE_LABEL_LEN),
        ("timestamp_sec", ctypes.c_uint64),
    ]

class RamscopeReservationList(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("entries", RamscopeReservationEntry * RAMSCOPE_MAX_RESERVATIONS),
    ]

# IOCTL codes
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
RAMSCOPE_IOC_RESERVE = _IOWR(IOC_MAGIC, 3, ctypes.sizeof(RamscopeReservationReq))
RAMSCOPE_IOC_RELEASE = _IOWR(IOC_MAGIC, 4, ctypes.sizeof(RamscopeReleaseReq))
RAMSCOPE_IOC_LIST_RESERVATIONS = _IOR(IOC_MAGIC, 5, ctypes.sizeof(RamscopeReservationList))

STATUS_MAP = {
    0: "invalid",
    1: "free",
    2: "used",
    3: "kernel",
    4: "reserved",
    5: "allocated",
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

    def reserve_memory(self, size_bytes: int, label: str) -> Optional[Dict]:
        if not self.is_available() or size_bytes <= 0:
            return None

        try:
            with open(self.device_path, "r+b") as fd:
                req = RamscopeReservationReq()
                req.size_bytes = size_bytes
                encoded = label.encode("utf-8")[:RAMSCOPE_LABEL_LEN - 1]
                req.label = encoded
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_RESERVE, req)
                if ret == 0 and req.status == 0:
                    return {
                        "region_id": req.region_id,
                        "start_pfn": req.start_pfn,
                        "page_count": req.page_count,
                        "size_bytes": req.size_bytes,
                        "label": req.label.decode("utf-8", errors="replace"),
                    }
        except Exception:
            pass
        return None

    def release_memory(self, region_id: int) -> Optional[Dict]:
        if not self.is_available() or region_id <= 0:
            return None

        try:
            with open(self.device_path, "r+b") as fd:
                req = RamscopeReleaseReq()
                req.region_id = region_id
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_RELEASE, req)
                if ret == 0 and req.status == 0:
                    return {
                        "region_id": req.region_id,
                        "freed_bytes": req.freed_bytes,
                    }
        except Exception:
            pass
        return None

    def list_reservations(self) -> Optional[List[Dict]]:
        if not self.is_available():
            return None

        try:
            with open(self.device_path, "rb") as fd:
                res_list = RamscopeReservationList()
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_LIST_RESERVATIONS, res_list)
                if ret == 0:
                    out = []
                    for i in range(res_list.count):
                        item = res_list.entries[i]
                        out.append({
                            "region_id": item.region_id,
                            "start_pfn": item.start_pfn,
                            "page_count": item.page_count,
                            "size_bytes": item.size_bytes,
                            "label": item.label.decode("utf-8", errors="replace"),
                            "timestamp_sec": item.timestamp_sec,
                        })
                    return out
        except Exception:
            pass
        return None

