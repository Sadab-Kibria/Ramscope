export interface PrivilegeStatus {
  platform_is_linux: boolean;
  platformIsLinux?: boolean;
  is_root: boolean;
  isRoot?: boolean;
  can_read_kpageflags: boolean;
  canReadKpageflags?: boolean;
  can_read_kpagecount: boolean;
  canReadKpagecount?: boolean;
  can_read_pagemap: boolean;
  canReadPagemap?: boolean;
  kernel_module_loaded: boolean;
  kernelModuleLoaded?: boolean;
  device_path?: string | null;
  devicePath?: string | null;
  warning_message?: string | null;
  warningMessage?: string | null;
  privileged?: boolean;
}

export interface RamInfo {
  totalBytes: number;
  total_bytes?: number;
  usedBytes: number;
  used_bytes?: number;
  availableBytes: number;
  available_bytes?: number;
  freeBytes: number;
  free_bytes?: number;
  cachedBytes: number;
  cached_bytes?: number;
  buffersBytes: number;
  buffers_bytes?: number;
  slabBytes: number;
  slab_bytes?: number;
  kernelCacheBytes?: number;
  kernel_cache_bytes?: number;
  pageSize: number;
  page_size?: number;
  totalPages: number;
  total_pages?: number;
  maxPfn: number;
  max_pfn?: number;
  usagePercentage: number;
  usage_percentage?: number;
  privileged?: boolean;
}

export interface PageBlockSummary {
  startPFN: number;
  start_pfn?: number;
  endPFN: number;
  end_pfn?: number;
  pageCount: number;
  page_count?: number;
  status: "free" | "used" | "kernel" | "reserved" | "mixed" | "unknown";
  freeCount: number;
  free_count?: number;
  usedCount: number;
  used_count?: number;
  kernelCount: number;
  kernel_count?: number;
  reservedCount: number;
  reserved_count?: number;
  unknownCount?: number;
  unknown_count?: number;
  startAddressHex: string;
  start_address_hex?: string;
  endAddressHex: string;
  end_address_hex?: string;
}

export interface PagesMapResponse {
  pageSize: number;
  page_size?: number;
  totalPages: number;
  total_pages?: number;
  maxPFN: number;
  max_pfn?: number;
  startPFN: number;
  start_pfn?: number;
  endPFN: number;
  end_pfn?: number;
  blockSize: number;
  bucket_size?: number;
  blockCount: number;
  block_count?: number;
  resolution: number;
  privileged?: boolean;
  blocks: PageBlockSummary[];
  pages?: PageBlockSummary[];
}

export interface ProcessMappingSummary {
  pid: number;
  name: string;
}

export interface PageDetail {
  pfn: number;
  physicalAddressHex: string;
  physical_address_hex?: string;
  status: string;
  pageSize: number;
  page_size?: number;
  mapCount: number;
  map_count?: number;
  refCount: number;
  ref_count?: number;
  flags: string[];
  rawFlagsHex: string;
  raw_flags_hex?: string;
  isKernel: boolean;
  is_kernel?: boolean;
  isAnon: boolean;
  is_anon?: boolean;
  isSlab: boolean;
  is_slab?: boolean;
  isReserved: boolean;
  is_reserved?: boolean;
  mappedProcesses: ProcessMappingSummary[];
  mapped_processes?: ProcessMappingSummary[];
  note?: string | null;
}

export interface ProcessInfo {
  pid: number;
  name: string;
  cmdline?: string;
  rss: number;
  pss?: number | null;
  vsz: number;
  memoryPercent?: number;
  memory_percent?: number;
  residentPages: number;
  resident_pages?: number;
  user?: string;
}

export interface ProcessPageEntry {
  pfn: number;
  virtualAddressHex: string;
  virtual_address_hex?: string;
  physicalAddressHex: string;
  physical_address_hex?: string;
  flags: string[];
  mapCount: number;
  map_count?: number;
  isShared: boolean;
  is_shared?: boolean;
  isSwapped: boolean;
  is_swapped?: boolean;
  isPresent: boolean;
  is_present?: boolean;
}

export interface ProcessPagesResponse {
  pid: number;
  name: string;
  totalMappedPages: number;
  total_mapped_pages?: number;
  residentPages: number;
  resident_pages?: number;
  pfnList: number[];
  pfn_list?: number[];
  pages: ProcessPageEntry[];
  error?: string | null;
}
