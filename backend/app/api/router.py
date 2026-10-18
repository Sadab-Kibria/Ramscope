from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from app.models.ram import (
    PrivilegeStatus,
    RamInfoResponse,
    PagesMapResponse,
    PageDetailResponse,
    ProcessInfo,
    ProcessPagesResponse,
)
from app.linux.privileges import check_privileges
from app.services.ram_service import RamService
from app.services.page_service import PageService
from app.services.process_service import ProcessService

router = APIRouter()

ram_service = RamService()
page_service = PageService()
process_service = ProcessService()

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
    if pid <= 0:
        raise HTTPException(status_code=400, detail="PID must be positive integer")
    return process_service.get_process_pages(pid, max_pages=max_pages)
