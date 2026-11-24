/* SPDX-License-Identifier: GPL-2.0 */
/*
 * ramscope.h - shared definitions between the kernel module and user space
 *
 * This header is included by:
 *   - ramscope.c      (the kernel module)
 *   - test_ioctl.c    (the C test program)
 * and the same layout is copied in backend/app/linux/kernel_module.py.
 *
 * IMPORTANT: do not change the order, type or size of the fields in the
 * existing structs below, otherwise the Python backend reads wrong data.
 * (Where a small field is followed by a __u64, the compiler silently adds
 *  4 bytes of padding. Python's ctypes adds exactly the same padding.)
 */
#ifndef _RAMSCOPE_H
#define _RAMSCOPE_H

#include <linux/types.h>
#include <linux/ioctl.h>

/*
 * "__user" marks a pointer that points into user-space memory.
 * It only exists inside the kernel, so for user programs we define it
 * as nothing. (Without this, test_ioctl.c does not compile.)
 */
#ifndef __KERNEL__
#ifndef __user
#define __user
#endif
#endif

/* Every ioctl number of this driver starts with the letter 'R' */
#define RAMSCOPE_IOC_MAGIC 'R'

/* Maximum number of pages that can be asked for in one QUERY_PFNS call */
#define RAMSCOPE_MAX_BATCH_PFN 65536

/* What a physical page is currently used for */
#define RAMSCOPE_PAGE_STATUS_INVALID    0   /* not RAM (hole / offline / device)  */
#define RAMSCOPE_PAGE_STATUS_FREE       1   /* free, Linux can hand it out        */
#define RAMSCOPE_PAGE_STATUS_USED       2   /* user programs or file cache        */
#define RAMSCOPE_PAGE_STATUS_KERNEL     3   /* used by the kernel itself          */
#define RAMSCOPE_PAGE_STATUS_RESERVED   4   /* firmware / BIOS / kernel image     */
#define RAMSCOPE_PAGE_STATUS_ALLOCATED  5   /* reserved (locked) by RAMScope      */

#define RAMSCOPE_MAX_RESERVATIONS       32  /* at most 32 reservations at a time  */
#define RAMSCOPE_LABEL_LEN              32  /* application label, incl. final \0  */


/* ===================================================================== */
/* Inspecting memory                                                     */
/* ===================================================================== */

/* Answer of RAMSCOPE_IOC_GET_RAM_INFO: overall RAM numbers */
struct ramscope_ram_info {
    __u64 total_ram_bytes;      /* RAM managed by the kernel            */
    __u64 free_ram_bytes;       /* completely unused RAM                */
    __u64 available_ram_bytes;  /* free + cache that can be reclaimed   */
    __u64 total_pages;          /* total_ram_bytes / page_size          */
    __u64 free_pages;           /* free_ram_bytes  / page_size          */
    __u64 max_pfn;              /* one past the highest RAM page number */
    __u64 min_pfn;              /* lowest RAM page number               */
    __u32 page_size;            /* normally 4096 bytes                  */
    __u32 _reserved;            /* padding, always 0                    */
};

/* Information about ONE physical page */
struct ramscope_pfn_info {
    __u64 pfn;          /* page frame number (physical address / page_size)  */
    __u64 flags;        /* page flags, same bit numbers as /proc/kpageflags  */
    __u32 mapcount;     /* how many page tables (processes) map this page    */
    __u32 refcount;     /* how many users hold a reference to this page      */
    __u8  status;       /* one of RAMSCOPE_PAGE_STATUS_*                     */
    __u8  is_slab;      /* 1 = kernel slab allocator page                    */
    __u8  is_anon;      /* 1 = anonymous memory (heap / stack of a process)  */
    __u8  is_reserved;  /* 1 = reserved page                                 */
    __u32 _reserved;    /* padding, always 0                                 */
};

/* Request of RAMSCOPE_IOC_QUERY_PFNS: "tell me about pages start..start+count" */
struct ramscope_pfn_query {
    __u64 start_pfn;                            /* first page to inspect      */
    __u32 count;                                /* how many pages             */
    __u32 _reserved;                            /* padding, always 0          */
    struct ramscope_pfn_info __user *results;   /* array of 'count' entries   */
};


/* ===================================================================== */
/* Reserving memory                                                      */
/* ===================================================================== */

/* RAMSCOPE_IOC_RESERVE: "lock size_bytes of physical RAM for this label" */
struct ramscope_reservation_req {
    __u64 size_bytes;                   /* [in]  requested size in bytes          */
    char  label[RAMSCOPE_LABEL_LEN];    /* [in]  application name / label         */
    __u32 region_id;                    /* [out] unique ID of the new reservation */
    __u64 start_pfn;                    /* [out] lowest PFN of the reservation    */
    __u64 page_count;                   /* [out] number of pages reserved         */
    __u32 status;                       /* [out] 0 = success                      */
};

/* RAMSCOPE_IOC_RELEASE: "give reservation region_id back to Linux" */
struct ramscope_release_req {
    __u32 region_id;                    /* [in]  reservation to free              */
    __u64 freed_bytes;                  /* [out] bytes given back to Linux        */
    __u32 status;                       /* [out] 0 = success                      */
};

/* One line of RAMSCOPE_IOC_LIST_RESERVATIONS */
struct ramscope_reservation_entry {
    __u32 region_id;
    __u64 start_pfn;                    /* lowest PFN of the reservation          */
    __u64 page_count;                   /* number of pages reserved               */
    __u64 size_bytes;                   /* page_count * page_size                 */
    char  label[RAMSCOPE_LABEL_LEN];
    __u64 timestamp_sec;                /* creation time (seconds since 1970)     */
};

/* Answer of RAMSCOPE_IOC_LIST_RESERVATIONS */
struct ramscope_reservation_list {
    __u32 count;                        /* how many entries are filled            */
    struct ramscope_reservation_entry entries[RAMSCOPE_MAX_RESERVATIONS];
};

/*
 * RAMSCOPE_IOC_GET_REGION_RANGES (new, optional):
 * the exact physical layout of one reservation. Normally a reservation
 * is ONE unbroken block of pages (nr_ranges == 1). If Linux could not
 * find one big free block, it is made of a few separate blocks.
 */
struct ramscope_pfn_range {
    __u64 start_pfn;                    /* first page of this block               */
    __u64 page_count;                   /* number of pages in this block          */
};

struct ramscope_region_ranges {
    __u32 region_id;                            /* [in]  which reservation        */
    __u32 max_ranges;                           /* [in]  size of ranges[] array   */
    __u32 nr_ranges;                            /* [out] blocks in the region     */
    __u32 _reserved;                            /* padding, always 0              */
    struct ramscope_pfn_range __user *ranges;   /* [out] filled with the blocks   */
};


/* ===================================================================== */
/* ioctl commands (direction + magic letter + number + argument size)    */
/* ===================================================================== */
#define RAMSCOPE_IOC_GET_RAM_INFO       _IOR(RAMSCOPE_IOC_MAGIC, 1, struct ramscope_ram_info)
#define RAMSCOPE_IOC_QUERY_PFNS         _IOWR(RAMSCOPE_IOC_MAGIC, 2, struct ramscope_pfn_query)
#define RAMSCOPE_IOC_RESERVE            _IOWR(RAMSCOPE_IOC_MAGIC, 3, struct ramscope_reservation_req)
#define RAMSCOPE_IOC_RELEASE            _IOWR(RAMSCOPE_IOC_MAGIC, 4, struct ramscope_release_req)
#define RAMSCOPE_IOC_LIST_RESERVATIONS  _IOR(RAMSCOPE_IOC_MAGIC, 5, struct ramscope_reservation_list)
#define RAMSCOPE_IOC_GET_REGION_RANGES  _IOWR(RAMSCOPE_IOC_MAGIC, 6, struct ramscope_region_ranges)

#endif /* _RAMSCOPE_H */
