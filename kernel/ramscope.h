#ifndef _RAMSCOPE_H
#define _RAMSCOPE_H

#include <linux/types.h>
#include <linux/ioctl.h>

#define RAMSCOPE_IOC_MAGIC 'R'

/* Maximum PFNs queryable in a single ioctl batch for safety */
#define RAMSCOPE_MAX_BATCH_PFN 65536

/* Page classification status flags */
#define RAMSCOPE_PAGE_STATUS_INVALID    0
#define RAMSCOPE_PAGE_STATUS_FREE       1
#define RAMSCOPE_PAGE_STATUS_USED       2
#define RAMSCOPE_PAGE_STATUS_KERNEL     3
#define RAMSCOPE_PAGE_STATUS_RESERVED   4

/* Structure for global RAM information */
struct ramscope_ram_info {
    __u64 total_ram_bytes;
    __u64 free_ram_bytes;
    __u64 available_ram_bytes;
    __u64 total_pages;
    __u64 free_pages;
    __u64 max_pfn;
    __u64 min_pfn;
    __u32 page_size;
    __u32 _reserved;
};

/* Structure for single PFN info */
struct ramscope_pfn_info {
    __u64 pfn;
    __u64 flags;
    __u32 mapcount;
    __u32 refcount;
    __u8  status;       /* RAMSCOPE_PAGE_STATUS_* */
    __u8  is_slab;
    __u8  is_anon;
    __u8  is_reserved;
    __u32 _reserved;
};

/* Structure for querying a batch of PFNs */
struct ramscope_pfn_query {
    __u64 start_pfn;
    __u32 count;
    __u32 _reserved;
    struct ramscope_pfn_info __user *results;
};

/* IOCTL Commands */
#define RAMSCOPE_IOC_GET_RAM_INFO   _IOR(RAMSCOPE_IOC_MAGIC, 1, struct ramscope_ram_info)
#define RAMSCOPE_IOC_QUERY_PFNS     _IOWR(RAMSCOPE_IOC_MAGIC, 2, struct ramscope_pfn_query)

#endif /* _RAMSCOPE_H */
