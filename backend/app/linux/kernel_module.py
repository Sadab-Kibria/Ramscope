import errno
import os
try:
    import fcntl
except ImportError:
    fcntl = None
import ctypes
from typing import Optional, List, Dict

class KernelReservationError(Exception):
    """Raised when /dev/ramscope is loaded and explicitly rejects a reservation/release."""
    pass

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

class RamscopePfnRange(ctypes.Structure):
    _fields_ = [
        ("start_pfn", ctypes.c_uint64),
        ("page_count", ctypes.c_uint64),
    ]

class RamscopeRegionRanges(ctypes.Structure):
    _fields_ = [
        ("region_id", ctypes.c_uint32),
        ("max_ranges", ctypes.c_uint32),
        ("nr_ranges", ctypes.c_uint32),
        ("_reserved", ctypes.c_uint32),
        ("ranges", ctypes.c_void_p),
    ]

# Standard Linux <uapi/asm-generic/ioctl.h> bit shifts:
# bits 0..7 = nr, bits 8..15 = type ('R'), bits 16..29 = size, bits 30..31 = dir
IOC_MAGIC = ord('R')
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS

_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2

def _IOC(dir_, type_, nr, size):
    return (
        (dir_ << _IOC_DIRSHIFT) |
        (size << _IOC_SIZESHIFT) |
        (type_ << _IOC_TYPESHIFT) |
        (nr << _IOC_NRSHIFT)
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
RAMSCOPE_IOC_GET_REGION_RANGES = _IOWR(IOC_MAGIC, 6, ctypes.sizeof(RamscopeRegionRanges))

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
            with open(self.device_path, "rb", buffering=0) as fd:
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
            with open(self.device_path, "rb", buffering=0) as fd:
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
            with open(self.device_path, "r+b", buffering=0) as fd:
                req = RamscopeReservationReq()
                req.size_bytes = size_bytes
                encoded = label.encode("utf-8")[:RAMSCOPE_LABEL_LEN - 1]
                req.label = encoded
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_RESERVE, req)
                if ret == 0 and req.status == 0:
                    ranges = self.get_region_ranges(req.region_id) or [
                        {"start_pfn": int(req.start_pfn), "page_count": int(req.page_count)}
                    ]
                    return {
                        "region_id": int(req.region_id),
                        "start_pfn": int(req.start_pfn),
                        "page_count": int(req.page_count),
                        "size_bytes": int(req.page_count) * 4096,
                        "label": req.label.decode("utf-8", errors="replace"),
                        "ranges": ranges,
                    }
        except OSError as exc:
            if exc.errno == errno.ENOMEM:
                raise KernelReservationError(
                    "Kernel refused reservation: not enough free physical RAM (RAMScope caps reservations at 50% of RAM and keeps at least 20% available for Linux)."
                ) from exc
            if exc.errno == errno.ENOSPC:
                raise KernelReservationError(
                    f"Kernel refused reservation: all {RAMSCOPE_MAX_RESERVATIONS} reservation slots are currently full."
                ) from exc
            if exc.errno in (errno.EACCES, errno.EPERM):
                raise KernelReservationError(
                    f"Permission denied writing to {self.device_path}. Run the backend with sudo."
                ) from exc
            if exc.errno == errno.EINVAL:
                raise KernelReservationError(
                    "Invalid reservation size (must be between 1 byte and 512 MB)."
                ) from exc
            raise KernelReservationError(f"Kernel reservation ioctl failed: {exc}") from exc
        return None

    def release_memory(self, region_id: int) -> Optional[Dict]:
        if not self.is_available() or region_id <= 0:
            return None

        try:
            with open(self.device_path, "r+b", buffering=0) as fd:
                req = RamscopeReleaseReq()
                req.region_id = region_id
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_RELEASE, req)
                if ret == 0 and req.status == 0:
                    return {
                        "region_id": int(req.region_id),
                        "freed_bytes": int(req.freed_bytes),
                    }
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                return None
            if exc.errno in (errno.EACCES, errno.EPERM):
                raise KernelReservationError(
                    f"Permission denied writing to {self.device_path}. Run the backend with sudo."
                ) from exc
            raise KernelReservationError(f"Kernel release ioctl failed: {exc}") from exc
        return None

    def get_region_ranges(self, region_id: int, max_ranges: int = 256) -> Optional[List[Dict]]:
        if not self.is_available() or region_id <= 0:
            return None

        try:
            with open(self.device_path, "rb", buffering=0) as fd:
                RangeArray = RamscopePfnRange * max_ranges
                buf = RangeArray()
                arg = RamscopeRegionRanges(
                    region_id=region_id,
                    max_ranges=max_ranges,
                    nr_ranges=0,
                    _reserved=0,
                    ranges=ctypes.cast(buf, ctypes.c_void_p).value,
                )
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_GET_REGION_RANGES, arg)
                if ret == 0:
                    shown = min(int(arg.nr_ranges), max_ranges)
                    return [
                        {
                            "start_pfn": int(buf[i].start_pfn),
                            "page_count": int(buf[i].page_count),
                        }
                        for i in range(shown)
                    ]
        except Exception:
            pass
        return None

    def list_reservations(self) -> Optional[List[Dict]]:
        if not self.is_available():
            return None

        try:
            with open(self.device_path, "rb", buffering=0) as fd:
                res_list = RamscopeReservationList()
                ret = fcntl.ioctl(fd.fileno(), RAMSCOPE_IOC_LIST_RESERVATIONS, res_list)
                if ret == 0:
                    out = []
                    for i in range(res_list.count):
                        item = res_list.entries[i]
                        rid = int(item.region_id)
                        spfn = int(item.start_pfn)
                        pcount = int(item.page_count)
                        ranges = self.get_region_ranges(rid) or [
                            {"start_pfn": spfn, "page_count": pcount}
                        ]
                        out.append({
                            "region_id": rid,
                            "start_pfn": spfn,
                            "page_count": pcount,
                            "size_bytes": int(item.size_bytes),
                            "label": item.label.decode("utf-8", errors="replace"),
                            "timestamp_sec": int(item.timestamp_sec),
                            "ranges": ranges,
                        })
                    return out
        except Exception:
            pass
        return None

