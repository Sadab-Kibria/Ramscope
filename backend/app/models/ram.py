from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class PrivilegeStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    platform_is_linux: bool = Field(..., alias="platformIsLinux", description="Whether host OS is Linux")
    is_root: bool = Field(..., alias="isRoot", description="Whether backend is running as root/UID 0")
    can_read_kpageflags: bool = Field(..., alias="canReadKpageflags", description="Access to /proc/kpageflags")
    can_read_kpagecount: bool = Field(..., alias="canReadKpagecount", description="Access to /proc/kpagecount")
    can_read_pagemap: bool = Field(..., alias="canReadPagemap", description="Access to /proc/<pid>/pagemap")
    kernel_module_loaded: bool = Field(..., alias="kernelModuleLoaded", description="Whether /dev/ramscope kernel device is accessible")
    device_path: Optional[str] = Field("/dev/ramscope", alias="devicePath")
    warning_message: Optional[str] = Field(None, alias="warningMessage")
    privileged: bool = Field(False, description="True if elevated Linux capabilities are present")

class RamInfoResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_bytes: int = Field(..., alias="totalBytes", description="Total physical RAM in bytes")
    used_bytes: int = Field(..., alias="usedBytes", description="Used physical RAM in bytes")
    available_bytes: int = Field(..., alias="availableBytes", description="Available physical RAM in bytes")
    free_bytes: int = Field(0, alias="freeBytes", description="Free physical RAM in bytes")
    cached_bytes: int = Field(0, alias="cachedBytes", description="Page cache memory in bytes")
    buffers_bytes: int = Field(0, alias="buffersBytes", description="Buffer memory in bytes")
    slab_bytes: int = Field(0, alias="slabBytes", description="Slab memory in bytes")
    kernel_cache_bytes: int = Field(0, alias="kernelCacheBytes", description="Total kernel + cache memory in bytes")
    page_size: int = Field(4096, alias="pageSize", description="Page size in bytes")
    total_pages: int = Field(..., alias="totalPages", description="Total number of physical page frames")
    max_pfn: int = Field(..., alias="maxPfn", description="Maximum Page Frame Number (PFN)")
    usage_percentage: float = Field(..., alias="usagePercentage", description="Memory usage percentage (0-100)")
    privileged: bool = Field(False, description="Whether privileged physical memory scanning is available")

class PageBlockSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_pfn: int = Field(..., alias="startPFN")
    end_pfn: int = Field(..., alias="endPFN")
    page_count: int = Field(..., alias="pageCount")
    status: str = Field(..., description="'free', 'used', 'kernel', 'reserved', 'mixed', 'unknown'")
    free_count: int = Field(0, alias="freeCount")
    used_count: int = Field(0, alias="usedCount")
    kernel_count: int = Field(0, alias="kernelCount")
    reserved_count: int = Field(0, alias="reservedCount")
    unknown_count: int = Field(0, alias="unknownCount")
    start_address_hex: str = Field(..., alias="startAddressHex")
    end_address_hex: str = Field(..., alias="endAddressHex")

class PagesMapResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_size: int = Field(4096, alias="pageSize")
    total_pages: int = Field(..., alias="totalPages")
    max_pfn: int = Field(..., alias="maxPFN")
    start_pfn: int = Field(..., alias="startPFN")
    end_pfn: int = Field(..., alias="endPFN")
    resolution: int
    bucket_size: int = Field(..., alias="blockSize")
    block_count: int = Field(..., alias="blockCount")
    privileged: bool = Field(False)
    pages: List[PageBlockSummary] = Field(..., alias="blocks")

class ProcessMappingSummary(BaseModel):
    pid: int
    name: str

class PageDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pfn: int
    physical_address_hex: str = Field(..., alias="physicalAddressHex")
    status: str
    page_size: int = Field(4096, alias="pageSize")
    map_count: int = Field(0, alias="mapCount")
    ref_count: int = Field(0, alias="refCount")
    flags: List[str] = []
    raw_flags_hex: str = Field("0x0", alias="rawFlagsHex")
    is_kernel: bool = Field(False, alias="isKernel")
    is_anon: bool = Field(False, alias="isAnon")
    is_slab: bool = Field(False, alias="isSlab")
    is_reserved: bool = Field(False, alias="isReserved")
    mapped_processes: List[ProcessMappingSummary] = Field([], alias="mappedProcesses")
    note: Optional[str] = None

class ProcessInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pid: int
    name: str
    cmdline: Optional[str] = ""
    rss: int = Field(0, description="Resident Set Size in bytes")
    pss: Optional[int] = Field(None, description="Proportional Set Size in bytes")
    vsz: int = Field(0, description="Virtual Memory Size in bytes")
    memory_percent: float = Field(0.0, alias="memoryPercent", description="Memory % of total RAM")
    resident_pages: int = Field(0, alias="residentPages", description="Number of resident 4KB pages")
    user: Optional[str] = ""

class ProcessPageEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pfn: int
    virtual_address_hex: str = Field(..., alias="virtualAddressHex")
    physical_address_hex: str = Field(..., alias="physicalAddressHex")
    flags: List[str] = []
    map_count: int = Field(1, alias="mapCount")
    is_shared: bool = Field(False, alias="isShared")
    is_swapped: bool = Field(False, alias="isSwapped")
    is_present: bool = Field(True, alias="isPresent")

class ProcessPagesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pid: int
    name: str
    total_mapped_pages: int = Field(0, alias="totalMappedPages")
    resident_pages: int = Field(0, alias="residentPages")
    pfn_list: List[int] = Field([], alias="pfnList")
    pages: List[ProcessPageEntry] = []
    error: Optional[str] = None
