from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.models.ram import (
    PrivilegeStatus,
    RamInfoResponse,
    PagesMapResponse,
    PageDetailResponse,
    ProcessInfo,
    ProcessPagesResponse,
    ReserveRequest,
    ReserveResponse,
    ReleaseRequest,
    ReleaseResponse,
    ReservationItem,
)
from app.linux.privileges import check_privileges
from app.services.ram_service import RamService
from app.services.page_service import PageService
from app.services.process_service import ProcessService
from app.services.reservation_service import ReservationService

router = APIRouter()

ram_service = RamService()
page_service = PageService()
process_service = ProcessService()
reservation_service = ReservationService()

@router.get("/status", response_model=PrivilegeStatus, summary="Check Linux privilege and kernel module status")
def get_status():
    return check_privileges()

@router.get("/ram", response_model=RamInfoResponse, summary="Get global physical RAM statistics")
def get_ram():
    return ram_service.get_ram_info()

@router.get("/pages", response_model=PagesMapResponse, summary="Get physical memory page block map with aggregation")
def get_pages(
    start_pfn: Optional[int] = Query(None, description="Starting PFN index"),
    count: Optional[int] = Query(None, description="Number of PFNs to scan"),
    resolution: int = Query(512, ge=32, le=4096, description="Visual block resolution (number of bins)"),
):
    return page_service.get_pages_map(start_pfn=start_pfn, count=count, resolution=resolution)

@router.get("/page/{pfn}", response_model=PageDetailResponse, summary="Inspect detailed metadata of a single PFN")
def get_page_detail(pfn: int):
    if pfn < 0:
        raise HTTPException(status_code=400, detail="PFN must be non-negative")
    return page_service.get_page_detail(pfn)

@router.get("/processes", response_model=List[ProcessInfo], summary="Get list of running processes with RSS, PSS, VSZ")
def get_processes(limit: int = Query(200, ge=1, le=1000)):
    return process_service.list_processes(limit=limit)

@router.get("/process/{pid}", response_model=ProcessInfo, summary="Get memory summary for a single process")
def get_process_info(pid: int):
    procs = process_service.list_processes(limit=1000)
    for p in procs:
        if p.pid == pid:
            return p
    raise HTTPException(status_code=404, detail=f"Process with PID {pid} not found")

@router.get("/process/{pid}/pages", response_model=ProcessPagesResponse, summary="Get physical pages mapped by a process")
def get_process_pages(
    pid: int,
    max_pages: int = Query(10000, ge=10, le=100000, description="Max physical pages to return in detail")
):
    if pid == 0:
        raise HTTPException(status_code=400, detail="PID 0 is reserved. Please provide a valid process PID.")
    return process_service.get_process_pages(pid, max_pages=max_pages)

# Step 6: Memory Reservation & Deallocation Endpoints
@router.post("/reserve", response_model=ReserveResponse, summary="Allocate/reserve physical memory for an application")
def reserve_memory(req: ReserveRequest):
    if not req.application or not req.application.strip():
        raise HTTPException(status_code=400, detail="Application name cannot be empty")
    
    # Check that requested size is within safe limits (1 KB to 512 MB)
    size_b = req.size_bytes if (req.size_bytes is not None and req.size_bytes > 0) else (
        int((req.size_mb or 16) * 1024 * 1024)
    )
    if size_b <= 0:
        raise HTTPException(status_code=400, detail="Reservation size must be positive")
    if size_b > (512 * 1024 * 1024):
        raise HTTPException(status_code=400, detail="Maximum single allocation size is 512 MB for safety")

    res = reservation_service.reserve(req)
    if not res.success:
        raise HTTPException(status_code=500, detail=res.message)
    return res

@router.post("/release", response_model=ReleaseResponse, summary="Deallocate a previously reserved memory region")
def release_memory(req: ReleaseRequest):
    if req.region_id <= 0:
        raise HTTPException(status_code=400, detail="Region ID must be positive integer")
    
    res = reservation_service.release(req.region_id)
    if not res.success:
        raise HTTPException(status_code=404, detail=res.message)
    return res

@router.get("/reservations", response_model=List[ReservationItem], summary="List all currently active memory reservations")
def list_reservations():
    return reservation_service.list_reservations()
