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
#define RAMSCOPE_PAGE_STATUS_ALLOCATED  5   /* Project application-reserved RAM */

#define RAMSCOPE_MAX_RESERVATIONS       32
#define RAMSCOPE_LABEL_LEN              32

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

/* Structure for requesting a memory reservation */
struct ramscope_reservation_req {
    __u64 size_bytes;                   /* [in] requested size in bytes */
    char  label[RAMSCOPE_LABEL_LEN];    /* [in] application name / label */
    __u32 region_id;                    /* [out] unique allocation region ID */
    __u64 start_pfn;                    /* [out] starting PFN */
    __u64 page_count;                   /* [out] number of 4KB pages allocated */
    __u32 status;                       /* [out] 0 = success, errno otherwise */
};

/* Structure for releasing an existing memory reservation */
struct ramscope_release_req {
    __u32 region_id;                    /* [in] allocation region ID to free */
    __u64 freed_bytes;                  /* [out] bytes deallocated */
    __u32 status;                       /* [out] 0 = success, errno otherwise */
};

/* Structure representing an active reservation in the list */
struct ramscope_reservation_entry {
    __u32 region_id;
    __u64 start_pfn;
    __u64 page_count;
    __u64 size_bytes;
    char  label[RAMSCOPE_LABEL_LEN];
    __u64 timestamp_sec;
};

/* Structure for querying all active reservations */
struct ramscope_reservation_list {
    __u32 count;
    struct ramscope_reservation_entry entries[RAMSCOPE_MAX_RESERVATIONS];
};

/* IOCTL Commands */
#define RAMSCOPE_IOC_GET_RAM_INFO       _IOR(RAMSCOPE_IOC_MAGIC, 1, struct ramscope_ram_info)
#define RAMSCOPE_IOC_QUERY_PFNS         _IOWR(RAMSCOPE_IOC_MAGIC, 2, struct ramscope_pfn_query)
#define RAMSCOPE_IOC_RESERVE            _IOWR(RAMSCOPE_IOC_MAGIC, 3, struct ramscope_reservation_req)
#define RAMSCOPE_IOC_RELEASE            _IOWR(RAMSCOPE_IOC_MAGIC, 4, struct ramscope_release_req)
#define RAMSCOPE_IOC_LIST_RESERVATIONS  _IOR(RAMSCOPE_IOC_MAGIC, 5, struct ramscope_reservation_list)

#endif /* _RAMSCOPE_H */
