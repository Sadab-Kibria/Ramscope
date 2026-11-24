// SPDX-License-Identifier: GPL-2.0
/*
 * RAMScope kernel module
 * ======================
 *
 * What it does
 *   Creates the device file /dev/ramscope. User programs (our Python
 *   backend, test_ioctl.c, or simply "cat") use it like this:
 *
 *     read()                          text report  (try: cat /dev/ramscope)
 *     RAMSCOPE_IOC_GET_RAM_INFO       overall RAM numbers
 *     RAMSCOPE_IOC_QUERY_PFNS         what each physical page is used for
 *     RAMSCOPE_IOC_RESERVE            reserve (lock) physical RAM for a label
 *     RAMSCOPE_IOC_RELEASE            give a reservation back to Linux
 *     RAMSCOPE_IOC_LIST_RESERVATIONS  list all reservations
 *     RAMSCOPE_IOC_GET_REGION_RANGES  exact physical blocks of a reservation
 *
 * How reserving works (short version)
 *   We ask the Linux page allocator for REAL pages (alloc_pages_exact).
 *   While we hold them they are taken out of Linux's free memory, so no
 *   other process - and not the kernel itself - can use them. "free -h"
 *   and /proc/meminfo show them as used. They go back to Linux on
 *   RELEASE or when the module is unloaded (rmmod).
 *
 * Words used in this file
 *   page         RAM is managed in blocks of PAGE_SIZE bytes (normally 4 KB)
 *   PFN          Page Frame Number = index of a physical page
 *                physical address = PFN * PAGE_SIZE
 *   struct page  the record the kernel keeps for every physical page
 *   region       one reservation (has an ID and a label)
 *   chunk        one unbroken block of pages that belongs to a region
 *
 * File layout
 *   Part 1  settings and bookkeeping data
 *   Part 2  range of RAM page numbers
 *   Part 3  flags of one page
 *   Part 4  status of one page
 *   Part 5  reservation engine (getting real pages from Linux)
 *   Part 6  ioctl commands
 *   Part 7  read(): text report
 *   Part 8  device file, module load / unload
 */

#define pr_fmt(fmt) "ramscope: " fmt     /* prefix for every log line */

#include <linux/module.h>             /* module_init, MODULE_LICENSE        */
#include <linux/miscdevice.h>         /* misc_register -> /dev/ramscope     */
#include <linux/fs.h>                 /* file_operations, read helpers      */
#include <linux/uaccess.h>            /* copy_to_user, copy_from_user       */
#include <linux/mm.h>                 /* struct page, si_meminfo            */
#include <linux/mmzone.h>             /* NUMA nodes, node_start_pfn         */
#include <linux/memory_hotplug.h>     /* pfn_to_online_page                 */
#include <linux/page-flags.h>         /* PageReserved, PageSlab, PageBuddy  */
#include <linux/kernel-page-flags.h>  /* KPF_* bit numbers                  */
#include <linux/gfp.h>                /* alloc_pages_exact, free_pages_exact */
#include <linux/slab.h>               /* kmalloc, kvmalloc, kfree           */
#include <linux/mutex.h>              /* mutex_lock / mutex_unlock          */
#include <linux/string.h>             /* strscpy, memset                    */
#include <linux/timekeeping.h>        /* ktime_get_real_seconds             */
#include <linux/sched.h>              /* cond_resched                       */

#include "ramscope.h"

MODULE_LICENSE("GPL");
MODULE_AUTHOR("RAMScope Team");
MODULE_DESCRIPTION("RAMScope Physical Memory Inspection & Reservation Module");
MODULE_VERSION("1.2.0");


/* ===================================================================== */
/* Part 1: settings and bookkeeping data                                 */
/* ===================================================================== */

#define DEVICE_NAME       "ramscope"
#define BATCH_CHUNK_SIZE  1024      /* pages inspected before each copy to user */

/* --- Safety rules: RAMScope must never starve the operating system --- */
#define MAX_RESERVATION_BYTES   (512ULL * 1024 * 1024) /* one request: at most 512 MB  */
#define MAX_TOTAL_PERCENT       50  /* all reservations together: at most 50% of RAM  */
#define KEEP_AVAILABLE_PERCENT  20  /* Linux must keep at least 20% of RAM available  */

/* --- Reservation engine settings --- */
#define BIG_CHUNK_PAGES   1024  /* biggest block asked for at once: 1024 pages = 4 MB */
#define MAX_CHUNKS        8192  /* most blocks handled for one request               */
#define POOL_EXTRA_PAGES  16384 /* up to 64 MB borrowed briefly while looking for
                                   blocks that sit right next to each other          */

/*
 * Allocation flags used for every reserved block:
 *   GFP_KERNEL     normal kernel allocation (may sleep, may drop file cache)
 *   __GFP_NORETRY  give up quickly instead of fighting for memory; this also
 *                  means RAMScope never wakes up the OOM killer
 *   __GFP_NOWARN   no warning in dmesg when a big block is not available
 *   __GFP_ZERO     fill the pages with zeros (no old data left inside)
 */
#define RAMSCOPE_GFP (GFP_KERNEL | __GFP_NORETRY | __GFP_NOWARN | __GFP_ZERO)

/* Turn a KPF bit number into a bit mask, e.g. KPF(KPF_SLAB) = 1 << 7 */
#define KPF(bit) (1ULL << (bit))

/* One unbroken block of physical pages that we got from Linux */
struct ramscope_chunk {
    void          *virt;        /* kernel address of the block (needed to free it) */
    unsigned long  start_pfn;   /* first physical page of the block                */
    unsigned long  nr_pages;    /* number of pages in the block                    */
};

/* One reservation ("region") */
struct ramscope_region {
    u32            region_id;                /* unique ID shown to the user      */
    char           label[RAMSCOPE_LABEL_LEN];/* application name                 */
    u64            timestamp_sec;            /* when it was created              */
    unsigned long  nr_pages;                 /* total pages held                 */
    unsigned long  first_pfn;                /* lowest PFN of the region         */
    unsigned long  end_pfn;                  /* one past the highest PFN         */
    unsigned int   nr_chunks;                /* number of blocks (1 = unbroken)  */
    struct ramscope_chunk *chunks;           /* the blocks, sorted by PFN        */
};

/*
 * The reservation table. A slot is either NULL (free) or points to a region.
 * g_lock protects the table, g_reserved_pages and g_next_region_id.
 */
static struct ramscope_region *g_regions[RAMSCOPE_MAX_RESERVATIONS];
static unsigned long g_reserved_pages;      /* pages held by all regions together */
static u32 g_next_region_id = 1;
static DEFINE_MUTEX(g_lock);


/* ===================================================================== */
/* Part 2: range of RAM page numbers                                     */
/* ===================================================================== */

/*
 * Find the lowest PFN and "one past the highest" PFN of RAM.
 *
 * Why not use the kernel variable max_pfn?
 *   It is not exported to modules on modern kernels, so loading fails
 *   with: modpost: "max_pfn" undefined!
 *
 * Instead we ask every online memory node (NUMA node) where its RAM
 * starts and ends, and keep the smallest start and the biggest end.
 * A normal PC or VM has only one node.
 */
static void get_ram_pfn_range(unsigned long *first_pfn, unsigned long *end_pfn)
{
    unsigned long lowest = ULONG_MAX;
    unsigned long highest = 0;
    int nid;

    for_each_online_node(nid) {
        lowest  = min(lowest, node_start_pfn(nid));
        highest = max(highest, node_end_pfn(nid));
    }

    if (lowest > highest)   /* no node found (should never happen) */
        lowest = 0;

    *first_pfn = lowest;
    *end_pfn = highest;
}


/* ===================================================================== */
/* Part 3: flags of one page                                             */
/* ===================================================================== */

/*
 * How many page tables map this page (roughly: how many processes use it).
 * The kernel stores "mappings - 1", so -1 means "not mapped".
 * Special pages (free, page table, ...) reuse this field and then it
 * looks negative; we report 0 for them.
 */
static unsigned int read_mapcount(struct page *page)
{
    int count = atomic_read(&page->_mapcount) + 1;

    return count > 0 ? count : 0;
}

/*
 * Build a 64-bit flag word for a page, using the SAME bit numbers as
 * /proc/kpageflags (KPF_LRU, KPF_SLAB, ...), so the backend can decode
 * the flags with its existing table.
 */
static u64 read_page_flags(struct page *page, unsigned int mapcount)
{
    struct folio *folio;
    u64 flags = 0;

    /* Shape of the page: part of a bigger (compound / huge) page? */
    if (PageHead(page))     flags |= KPF(KPF_COMPOUND_HEAD);
    if (PageTail(page))     flags |= KPF(KPF_COMPOUND_TAIL);
    if (PageHuge(page))     flags |= KPF(KPF_HUGE);
    if (PageReserved(page)) flags |= KPF(KPF_RESERVED);

    /*
     * Free, slab and page-table pages use the rest of struct page for
     * other things, so the remaining tests would be meaningless.
     */
    if (PageBuddy(page))
        return flags | KPF(KPF_BUDDY);      /* free page in the buddy allocator */
    if (PageSlab(page))
        return flags | KPF(KPF_SLAB);       /* kernel objects (kmalloc)         */
    if (PageTable(page))
        return flags | KPF(KPF_PGTABLE);    /* kernel page table                */

    /*
     * Modern Linux kernels (6.x and 7.x) group normal pages as a "folio"
     * (one base page or a compound group of pages) and store the active,
     * swap and I/O flags on the folio.
     */
    folio = page_folio(page);

    if (mapcount > 0)                 flags |= KPF(KPF_MMAP);        /* mapped into a process */
    if (folio_test_anon(folio))       flags |= KPF(KPF_ANON);        /* heap / stack memory   */
    if (folio_test_lru(folio))        flags |= KPF(KPF_LRU);         /* on the reclaim lists  */
    if (folio_test_active(folio))     flags |= KPF(KPF_ACTIVE);      /* recently used a lot   */
    if (folio_test_referenced(folio)) flags |= KPF(KPF_REFERENCED);  /* recently used         */
    if (folio_test_unevictable(folio))flags |= KPF(KPF_UNEVICTABLE); /* cannot be swapped out */
    if (folio_test_locked(folio))     flags |= KPF(KPF_LOCKED);      /* locked for I/O        */
    if (folio_test_uptodate(folio))   flags |= KPF(KPF_UPTODATE);    /* data is valid         */
    if (folio_test_dirty(folio))      flags |= KPF(KPF_DIRTY);       /* must be written back  */
    if (folio_test_writeback(folio))  flags |= KPF(KPF_WRITEBACK);   /* being written to disk */
    if (folio_test_reclaim(folio))    flags |= KPF(KPF_RECLAIM);     /* about to be reclaimed */
    if (folio_test_swapcache(folio))  flags |= KPF(KPF_SWAPCACHE);   /* copy exists in swap   */
    if (folio_test_swapbacked(folio)) flags |= KPF(KPF_SWAPBACKED);  /* can go to swap        */

    return flags;
}


/* ===================================================================== */
/* Part 4: status of one page                                            */
/* ===================================================================== */

/*
 * Which RAMScope reservation (if any) owns this PFN?
 * Caller must hold g_lock.
 */
static struct ramscope_region *find_region_of_pfn(unsigned long pfn)
{
    unsigned int c;
    int i;

    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        struct ramscope_region *r = g_regions[i];

        /* quick test: outside the region's lowest..highest PFN? */
        if (!r || pfn < r->first_pfn || pfn >= r->end_pfn)
            continue;

        for (c = 0; c < r->nr_chunks; c++) {
            const struct ramscope_chunk *ch = &r->chunks[c];

            if (pfn >= ch->start_pfn && pfn < ch->start_pfn + ch->nr_pages)
                return r;
        }
    }
    return NULL;
}

/*
 * Fill 'info' for one physical page. Caller must hold g_lock.
 *
 * Step 1: is this PFN real, online RAM?
 * Step 2: read refcount, mapcount and flags.
 * Step 3: pick a status. The checks run top to bottom, first match wins:
 *
 *   ALLOCATED  reserved by RAMScope (one of our regions)
 *   RESERVED   page is reserved (firmware, BIOS, kernel image)
 *   FREE       page is in the free lists, or nobody holds a reference
 *   KERNEL     slab memory or page tables
 *   USED       process memory (anonymous, mapped, huge pages) or file cache
 *   KERNEL     everything else: kernel stacks, vmalloc, driver buffers, ...
 */
static void inspect_pfn(unsigned long pfn, struct ramscope_pfn_info *info)
{
    struct page *page;
    u64 flags;

    memset(info, 0, sizeof(*info));
    info->pfn = pfn;

    /*
     * Step 1. pfn_to_online_page() returns NULL for holes between RAM
     * banks, device memory and offline memory. For those PFNs the
     * struct page may not be initialised, so we must not read it.
     */
    page = pfn_to_online_page(pfn);
    if (!page) {
        info->status = RAMSCOPE_PAGE_STATUS_INVALID;
        info->flags = KPF(KPF_NOPAGE);
        return;
    }

    /* Step 2. */
    info->refcount = page_count(page);
    info->mapcount = read_mapcount(page);
    flags = read_page_flags(page, info->mapcount);
    info->flags = flags;

    info->is_reserved = (flags & KPF(KPF_RESERVED)) ? 1 : 0;
    info->is_slab     = (flags & KPF(KPF_SLAB))     ? 1 : 0;
    info->is_anon     = (flags & KPF(KPF_ANON))     ? 1 : 0;

    /* Step 3. */
    if (find_region_of_pfn(pfn))
        info->status = RAMSCOPE_PAGE_STATUS_ALLOCATED;
    else if (flags & KPF(KPF_RESERVED))
        info->status = RAMSCOPE_PAGE_STATUS_RESERVED;
    else if ((flags & KPF(KPF_BUDDY)) || info->refcount == 0)
        info->status = RAMSCOPE_PAGE_STATUS_FREE;
    else if (flags & (KPF(KPF_SLAB) | KPF(KPF_PGTABLE)))
        info->status = RAMSCOPE_PAGE_STATUS_KERNEL;
    else if (flags & (KPF(KPF_ANON) | KPF(KPF_MMAP) | KPF(KPF_LRU) | KPF(KPF_HUGE)))
        info->status = RAMSCOPE_PAGE_STATUS_USED;
    else
        info->status = RAMSCOPE_PAGE_STATUS_KERNEL;
}


/* ===================================================================== */
/* Part 5: reservation engine                                            */
/* ===================================================================== */
/*
 * Goal: get N real pages from Linux, ideally as ONE unbroken block.
 *
 * Linux hands out at most 4 MB (1024 pages) of touching pages per call.
 * For bigger requests we ask several times and keep blocks that sit
 * right next to each other:
 *
 *   1. Ask for blocks of 'piece' pages (start with 4 MB) and keep them
 *      in a pool that is sorted by PFN.
 *   2. Stop as soon as the pool contains enough blocks in one unbroken
 *      row. (We may borrow a few extra blocks - at most 16 MB - while
 *      searching.)
 *   3. Keep the tightest group of blocks, give every other block back.
 *   4. If Linux does not have enough blocks of this size, halve the size
 *      and try again (4 MB -> 2 MB -> 1 MB -> ...).
 *
 * Every page we keep is truly owned by us, so no one else can use it.
 */

/* Give a list of blocks back to Linux */
static void free_chunks(struct ramscope_chunk *chunks, unsigned long count)
{
    unsigned long i;

    for (i = 0; i < count; i++)
        free_pages_exact(chunks[i].virt, chunks[i].nr_pages * PAGE_SIZE);
}

/* Give a whole region back to Linux and forget it */
static void free_region(struct ramscope_region *r)
{
    free_chunks(r->chunks, r->nr_chunks);
    kvfree(r->chunks);
    kfree(r);
}

/*
 * Add a freshly allocated block to the pool and keep the pool sorted
 * by PFN (insertion sort: move bigger PFNs one step to the right).
 */
static void pool_add_sorted(struct ramscope_chunk *pool, unsigned long *count,
                            void *virt, unsigned long nr_pages)
{
    unsigned long pfn = page_to_pfn(virt_to_page(virt));
    unsigned long i = *count;

    while (i > 0 && pool[i - 1].start_pfn > pfn) {
        pool[i] = pool[i - 1];
        i--;
    }
    pool[i].virt = virt;
    pool[i].start_pfn = pfn;
    pool[i].nr_pages = nr_pages;
    (*count)++;
}

/*
 * Among 'count' sorted blocks of 'piece' pages each, find 'needed'
 * neighbouring blocks that cover the smallest PFN span.
 * Stores the index of the first block in *first and returns the span.
 * span == needed * piece means the blocks touch: one unbroken range.
 */
static unsigned long find_tightest_group(const struct ramscope_chunk *pool,
                                         unsigned long count,
                                         unsigned long needed,
                                         unsigned long piece,
                                         unsigned long *first)
{
    unsigned long best_span = ULONG_MAX;
    unsigned long i;

    *first = 0;
    for (i = 0; i + needed <= count; i++) {
        unsigned long span = pool[i + needed - 1].start_pfn + piece - pool[i].start_pfn;

        if (span < best_span) {
            best_span = span;
            *first = i;
        }
    }
    return best_span;
}

/*
 * Turn the chosen group of blocks into the region's chunk list:
 *   - give back the unneeded pages at the end of the last block
 *   - merge blocks that touch each other into one chunk
 * On failure every block of the group is given back to Linux.
 */
static int keep_group(struct ramscope_region *r, struct ramscope_chunk *group,
                      unsigned long count, unsigned long nr_pages)
{
    struct ramscope_chunk *last = &group[count - 1];
    struct ramscope_chunk *list;
    unsigned long have = 0, extra, i, n = 0;

    list = kvmalloc_array(count, sizeof(*list), GFP_KERNEL);
    if (!list) {
        free_chunks(group, count);
        return -ENOMEM;
    }

    /* 1. All blocks have the same size, so the last one may be too big */
    for (i = 0; i < count; i++)
        have += group[i].nr_pages;
    extra = have - nr_pages;
    if (extra) {
        free_pages_exact((char *)last->virt + (last->nr_pages - extra) * PAGE_SIZE,
                         extra * PAGE_SIZE);
        last->nr_pages -= extra;
    }

    /* 2. Merge blocks that touch (physically and in kernel address space) */
    for (i = 0; i < count; i++) {
        struct ramscope_chunk *prev = n ? &list[n - 1] : NULL;

        if (prev &&
            prev->start_pfn + prev->nr_pages == group[i].start_pfn &&
            (char *)prev->virt + prev->nr_pages * PAGE_SIZE == (char *)group[i].virt)
            prev->nr_pages += group[i].nr_pages;
        else
            list[n++] = group[i];
    }

    r->chunks    = list;
    r->nr_chunks = n;
    r->nr_pages  = nr_pages;
    r->first_pfn = list[0].start_pfn;
    r->end_pfn   = list[n - 1].start_pfn + list[n - 1].nr_pages;
    return 0;
}

/*
 * Try to collect nr_pages using blocks of 'piece' pages each.
 * Returns 0 on success, -ENOMEM if Linux has too few free blocks of
 * this size (in that case everything was given back already).
 */
static int try_piece_size(struct ramscope_region *r, struct ramscope_chunk *pool,
                          unsigned long nr_pages, unsigned long piece)
{
    unsigned long needed = DIV_ROUND_UP(nr_pages, piece);
    unsigned long extra = 0, pool_max, have = 0, first = 0;

    if (needed > 1)
        extra = min_t(unsigned long, DIV_ROUND_UP(POOL_EXTRA_PAGES, piece),
                      MAX_CHUNKS - needed);
    pool_max = needed + extra;          /* always <= MAX_CHUNKS */

    /* Step 1 + 2: collect blocks until 'needed' of them touch, or the pool is full */
    while (have < pool_max) {
        void *virt = alloc_pages_exact(piece * PAGE_SIZE, RAMSCOPE_GFP);

        if (!virt)
            break;                      /* Linux has no more free blocks of this size */

        pool_add_sorted(pool, &have, virt, piece);

        if (have >= needed &&
            find_tightest_group(pool, have, needed, piece, &first) == needed * piece)
            break;                      /* perfect: one unbroken row of blocks */

        cond_resched();                 /* let other tasks run */
    }

    if (have < needed) {                /* not enough blocks of this size */
        free_chunks(pool, have);
        return -ENOMEM;
    }

    /* Step 3: keep the tightest group, give all other blocks back */
    find_tightest_group(pool, have, needed, piece, &first);
    free_chunks(pool, first);
    free_chunks(pool + first + needed, have - first - needed);

    return keep_group(r, pool + first, needed, nr_pages);
}

/*
 * Get nr_pages real pages from Linux for region r (Step 4: shrinking
 * block size). Called WITHOUT g_lock held, because it may take a moment.
 */
static int grab_pages(struct ramscope_region *r, unsigned long nr_pages)
{
    /* smallest block size we accept, so one request never needs more
       than MAX_CHUNKS / 2 blocks (+ the same number of extra blocks) */
    unsigned long min_piece = DIV_ROUND_UP(nr_pages, MAX_CHUNKS / 2);
    struct ramscope_chunk *pool;
    unsigned long piece;
    int ret = -ENOMEM;

    pool = kvmalloc_array(MAX_CHUNKS, sizeof(*pool), GFP_KERNEL);
    if (!pool)
        return -ENOMEM;

    for (piece = min_t(unsigned long, BIG_CHUNK_PAGES, nr_pages);
         piece >= min_piece; piece /= 2) {
        ret = try_piece_size(r, pool, nr_pages, piece);
        if (ret == 0)
            break;
    }

    kvfree(pool);
    return ret;
}

/* Most pages RAMScope may hold in total (MAX_TOTAL_PERCENT of RAM) */
static unsigned long total_limit_pages(void)
{
    struct sysinfo si;

    si_meminfo(&si);
    return si.totalram / 100 * MAX_TOTAL_PERCENT;
}

/*
 * Safety rules, checked BEFORE we take any memory. Caller holds g_lock.
 *   1. RAMScope holds at most MAX_TOTAL_PERCENT of RAM in total.
 *   2. After the reservation, at least KEEP_AVAILABLE_PERCENT of RAM
 *      must still be available to Linux (MemAvailable in /proc/meminfo).
 */
static int check_safety_limits(unsigned long want_pages)
{
    struct sysinfo si;
    unsigned long available, keep_pages;
    long avail;

    if (g_reserved_pages + want_pages > total_limit_pages()) {
        pr_warn("refused: RAMScope may hold at most %d%% of RAM\n", MAX_TOTAL_PERCENT);
        return -ENOMEM;
    }

    si_meminfo(&si);
    keep_pages = si.totalram / 100 * KEEP_AVAILABLE_PERCENT;
    avail = si_mem_available();
    available = avail > 0 ? avail : 0;

    if (want_pages > available || available - want_pages < keep_pages) {
        pr_warn("refused: Linux must keep at least %d%% of RAM available\n",
                KEEP_AVAILABLE_PERCENT);
        return -ENOMEM;
    }
    return 0;
}

/* Index of a free slot in the table, or -1. Caller holds g_lock. */
static int find_free_slot(void)
{
    int i;

    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++)
        if (!g_regions[i])
            return i;
    return -1;
}

/*
 * Double-reservation guard: does region r share any page with a region
 * that is already in the table? (Linux never hands out the same page
 * twice, so this is only a safety net for our bookkeeping.)
 * Caller holds g_lock.
 */
static bool region_overlaps_existing(const struct ramscope_region *r)
{
    unsigned int a, b;
    int i;

    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        const struct ramscope_region *o = g_regions[i];

        if (!o || r->end_pfn <= o->first_pfn || o->end_pfn <= r->first_pfn)
            continue;

        for (a = 0; a < r->nr_chunks; a++) {
            for (b = 0; b < o->nr_chunks; b++) {
                const struct ramscope_chunk *x = &r->chunks[a];
                const struct ramscope_chunk *y = &o->chunks[b];

                if (x->start_pfn < y->start_pfn + y->nr_pages &&
                    y->start_pfn < x->start_pfn + x->nr_pages)
                    return true;
            }
        }
    }
    return false;
}

/* Take region 'region_id' out of the table (caller frees it). Caller holds g_lock. */
static struct ramscope_region *take_region(u32 region_id)
{
    int i;

    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        struct ramscope_region *r = g_regions[i];

        if (r && r->region_id == region_id) {
            g_regions[i] = NULL;
            g_reserved_pages -= r->nr_pages;
            return r;
        }
    }
    return NULL;
}


/* ===================================================================== */
/* Part 6: ioctl commands                                                */
/* ===================================================================== */

/* RAMSCOPE_IOC_GET_RAM_INFO: send overall RAM numbers to user space */
static long ramscope_get_ram_info(struct ramscope_ram_info __user *user_info)
{
    struct ramscope_ram_info info;
    struct sysinfo si;
    unsigned long first_pfn, end_pfn;

    si_meminfo(&si);                    /* same numbers as /proc/meminfo */
    get_ram_pfn_range(&first_pfn, &end_pfn);

    memset(&info, 0, sizeof(info));
    info.page_size           = PAGE_SIZE;
    info.total_pages         = si.totalram;     /* si_meminfo counts in pages */
    info.free_pages          = si.freeram;
    info.total_ram_bytes     = (u64)si.totalram * PAGE_SIZE;
    info.free_ram_bytes      = (u64)si.freeram * PAGE_SIZE;
    info.available_ram_bytes = (u64)si_mem_available() * PAGE_SIZE;
    info.min_pfn             = first_pfn;
    info.max_pfn             = end_pfn;

    if (copy_to_user(user_info, &info, sizeof(info)))
        return -EFAULT;

    return 0;
}

/*
 * RAMSCOPE_IOC_QUERY_PFNS: inspect 'count' pages starting at 'start_pfn'.
 *
 * We work in chunks of BATCH_CHUNK_SIZE pages: inspect a chunk into a
 * small kernel buffer (holding g_lock, so reservations cannot change
 * meanwhile), then copy it to the user's array without the lock.
 * cond_resched() lets other tasks run so a big query never freezes Linux.
 */
static long ramscope_query_pfns(struct ramscope_pfn_query __user *user_query)
{
    struct ramscope_pfn_query query;
    struct ramscope_pfn_info *buffer;
    unsigned int done = 0;
    long ret = 0;

    if (copy_from_user(&query, user_query, sizeof(query)))
        return -EFAULT;

    /* Check the request */
    if (query.count == 0)
        return 0;
    if (query.count > RAMSCOPE_MAX_BATCH_PFN)
        return -EINVAL;
    if (query.start_pfn > ULONG_MAX - query.count)  /* start + count would overflow */
        return -EINVAL;

    buffer = kmalloc_array(BATCH_CHUNK_SIZE, sizeof(*buffer), GFP_KERNEL);
    if (!buffer)
        return -ENOMEM;

    while (done < query.count) {
        unsigned int chunk = min_t(unsigned int, query.count - done, BATCH_CHUNK_SIZE);
        unsigned int i;

        mutex_lock(&g_lock);
        for (i = 0; i < chunk; i++)
            inspect_pfn(query.start_pfn + done + i, &buffer[i]);
        mutex_unlock(&g_lock);

        if (copy_to_user(query.results + done, buffer, chunk * sizeof(*buffer))) {
            ret = -EFAULT;
            break;
        }

        done += chunk;
        cond_resched();
    }

    kfree(buffer);
    return ret;
}

/*
 * RAMSCOPE_IOC_RESERVE: lock 'size_bytes' of physical RAM for a label.
 *
 *   Step 1  check the request and the safety rules
 *   Step 2  get real pages from Linux (Part 5)
 *   Step 3  put the new region into the table
 *   Step 4  tell user space the region ID, first PFN and page count
 */
static long ramscope_reserve_memory(struct ramscope_reservation_req __user *user_req)
{
    struct ramscope_reservation_req req;
    struct ramscope_region *r;
    unsigned long nr_pages, first_pfn;
    unsigned int nr_chunks;
    u32 region_id = 0;
    int slot, ret = 0;

    if (copy_from_user(&req, user_req, sizeof(req)))
        return -EFAULT;

    /* Step 1: check the request */
    if (req.size_bytes == 0 || req.size_bytes > MAX_RESERVATION_BYTES)
        return -EINVAL;
    nr_pages = DIV_ROUND_UP_ULL(req.size_bytes, PAGE_SIZE);  /* ceil(size / page size) */
    req.label[RAMSCOPE_LABEL_LEN - 1] = '\0';                /* label always ends with \0 */

    mutex_lock(&g_lock);
    if (find_free_slot() < 0)
        ret = -ENOSPC;                  /* all 32 slots are in use */
    else
        ret = check_safety_limits(nr_pages);
    mutex_unlock(&g_lock);
    if (ret)
        return ret;

    /* Step 2: get real pages (may take a moment, so done without the lock) */
    r = kzalloc(sizeof(*r), GFP_KERNEL);
    if (!r)
        return -ENOMEM;

    ret = grab_pages(r, nr_pages);
    if (ret) {
        pr_warn("could not get %lu free pages from Linux\n", nr_pages);
        kfree(r);
        return ret;
    }
    strscpy(r->label, req.label[0] ? req.label : "unnamed", sizeof(r->label));
    r->timestamp_sec = ktime_get_real_seconds();
    first_pfn = r->first_pfn;
    nr_chunks = r->nr_chunks;

    /* Step 3: register (check again - another request may have run meanwhile) */
    mutex_lock(&g_lock);
    slot = find_free_slot();
    if (slot < 0)
        ret = -ENOSPC;
    else if (g_reserved_pages + nr_pages > total_limit_pages())
        ret = -ENOMEM;
    else if (region_overlaps_existing(r))
        ret = -EEXIST;

    if (!ret) {
        region_id = g_next_region_id++;
        if (g_next_region_id == 0)      /* never hand out ID 0 */
            g_next_region_id = 1;
        r->region_id = region_id;
        g_regions[slot] = r;
        g_reserved_pages += nr_pages;
    }
    mutex_unlock(&g_lock);

    if (ret) {
        free_region(r);
        return ret;
    }

    pr_info("region %u (%s): locked %lu pages (%lu KB) starting at PFN %lu, %u block(s)%s\n",
            region_id, req.label[0] ? req.label : "unnamed", nr_pages,
            nr_pages * (PAGE_SIZE / 1024), first_pfn, nr_chunks,
            nr_chunks == 1 ? " = one unbroken range" : "");

    /* Step 4: answer user space */
    req.region_id  = region_id;
    req.start_pfn  = first_pfn;
    req.page_count = nr_pages;
    req.status     = 0;

    if (copy_to_user(user_req, &req, sizeof(req))) {
        /* user space will never learn the ID, so do not leave memory locked */
        mutex_lock(&g_lock);
        r = take_region(region_id);
        mutex_unlock(&g_lock);
        if (r)
            free_region(r);
        return -EFAULT;
    }

    return 0;
}

/* RAMSCOPE_IOC_RELEASE: give a reservation back to Linux */
static long ramscope_release_memory(struct ramscope_release_req __user *user_req)
{
    struct ramscope_release_req req;
    struct ramscope_region *r;

    if (copy_from_user(&req, user_req, sizeof(req)))
        return -EFAULT;

    mutex_lock(&g_lock);
    r = take_region(req.region_id);
    mutex_unlock(&g_lock);

    if (!r)
        return -ENOENT;                 /* no reservation with this ID */

    req.freed_bytes = (u64)r->nr_pages * PAGE_SIZE;
    req.status = 0;

    pr_info("region %u (%s): released %lu pages, back to Linux\n",
            r->region_id, r->label, r->nr_pages);
    free_region(r);

    if (copy_to_user(user_req, &req, sizeof(req)))
        return -EFAULT;

    return 0;
}

/* RAMSCOPE_IOC_LIST_RESERVATIONS: describe every active reservation */
static long ramscope_list_reservations(struct ramscope_reservation_list __user *user_list)
{
    struct ramscope_reservation_list *list;
    u32 count = 0;
    long ret = 0;
    int i;

    /* the list is ~2.3 KB, too big for the small kernel stack */
    list = kzalloc(sizeof(*list), GFP_KERNEL);
    if (!list)
        return -ENOMEM;

    mutex_lock(&g_lock);
    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        struct ramscope_region *r = g_regions[i];
        struct ramscope_reservation_entry *e;

        if (!r)
            continue;

        e = &list->entries[count++];
        e->region_id     = r->region_id;
        e->start_pfn     = r->first_pfn;
        e->page_count    = r->nr_pages;
        e->size_bytes    = (u64)r->nr_pages * PAGE_SIZE;
        e->timestamp_sec = r->timestamp_sec;
        memcpy(e->label, r->label, RAMSCOPE_LABEL_LEN);  /* always \0-terminated */
    }
    list->count = count;
    mutex_unlock(&g_lock);

    if (copy_to_user(user_list, list, sizeof(*list)))
        ret = -EFAULT;

    kfree(list);
    return ret;
}

/* RAMSCOPE_IOC_GET_REGION_RANGES: exact physical blocks of one reservation */
static long ramscope_get_region_ranges(struct ramscope_region_ranges __user *user_arg)
{
    struct ramscope_region_ranges arg;
    struct ramscope_pfn_range *ranges = NULL;
    struct ramscope_region *r = NULL;
    unsigned int i, n = 0;
    long ret = 0;

    if (copy_from_user(&arg, user_arg, sizeof(arg)))
        return -EFAULT;

    arg.max_ranges = min_t(u32, arg.max_ranges, MAX_CHUNKS);
    if (arg.max_ranges) {
        ranges = kvmalloc_array(arg.max_ranges, sizeof(*ranges), GFP_KERNEL);
        if (!ranges)
            return -ENOMEM;
    }

    mutex_lock(&g_lock);
    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        if (g_regions[i] && g_regions[i]->region_id == arg.region_id) {
            r = g_regions[i];
            break;
        }
    }
    if (r) {
        arg.nr_ranges = r->nr_chunks;
        n = min_t(unsigned int, arg.max_ranges, r->nr_chunks);
        for (i = 0; i < n; i++) {
            ranges[i].start_pfn  = r->chunks[i].start_pfn;
            ranges[i].page_count = r->chunks[i].nr_pages;
        }
    }
    mutex_unlock(&g_lock);

    if (!r)
        ret = -ENOENT;
    else if (n && copy_to_user(arg.ranges, ranges, n * sizeof(*ranges)))
        ret = -EFAULT;
    else if (copy_to_user(user_arg, &arg, sizeof(arg)))
        ret = -EFAULT;

    kvfree(ranges);
    return ret;
}

/*
 * Compatibility codes for backend/app/linux/kernel_module.py, which shifts
 * the ioctl fields in the order (dir | magic | nr | size). Accepting both
 * the standard Linux _IOR/_IOWR codes and the Python backend's codes means
 * both C callers (test_ioctl) and the FastAPI backend work out of the box.
 */
#define PY_IOC(dir, nr, type) \
    (((unsigned int)(dir) << 30) | ((unsigned int)RAMSCOPE_IOC_MAGIC << 22) | \
     ((unsigned int)(nr) << 14) | (unsigned int)sizeof(type))
#define PY_IOC_GET_RAM_INFO       PY_IOC(2U, 1, struct ramscope_ram_info)
#define PY_IOC_QUERY_PFNS         PY_IOC(3U, 2, struct ramscope_pfn_query)
#define PY_IOC_RESERVE            PY_IOC(3U, 3, struct ramscope_reservation_req)
#define PY_IOC_RELEASE            PY_IOC(3U, 4, struct ramscope_release_req)
#define PY_IOC_LIST_RESERVATIONS  PY_IOC(2U, 5, struct ramscope_reservation_list)

/* Called for every ioctl() on /dev/ramscope: pick the right handler */
static long ramscope_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    void __user *uarg = (void __user *)arg;

    switch (cmd) {
    case RAMSCOPE_IOC_GET_RAM_INFO:
    case PY_IOC_GET_RAM_INFO:
        return ramscope_get_ram_info(uarg);
    case RAMSCOPE_IOC_QUERY_PFNS:
    case PY_IOC_QUERY_PFNS:
        return ramscope_query_pfns(uarg);
    case RAMSCOPE_IOC_RESERVE:
    case PY_IOC_RESERVE:
        return ramscope_reserve_memory(uarg);
    case RAMSCOPE_IOC_RELEASE:
    case PY_IOC_RELEASE:
        return ramscope_release_memory(uarg);
    case RAMSCOPE_IOC_LIST_RESERVATIONS:
    case PY_IOC_LIST_RESERVATIONS:
        return ramscope_list_reservations(uarg);
    case RAMSCOPE_IOC_GET_REGION_RANGES:
        return ramscope_get_region_ranges(uarg);
    default:
        return -ENOTTY;                 /* unknown command */
    }
}


/* ===================================================================== */
/* Part 7: read() - human readable report                                */
/* ===================================================================== */

#define REPORT_SIZE 8192

/* "cat /dev/ramscope" prints RAM numbers and all reservations */
static ssize_t ramscope_read(struct file *file, char __user *buf,
                             size_t count, loff_t *ppos)
{
    unsigned long first_pfn, end_pfn;
    struct sysinfo si;
    size_t len = 0;
    ssize_t ret;
    char *text;
    int i;

    text = kzalloc(REPORT_SIZE, GFP_KERNEL);
    if (!text)
        return -ENOMEM;

    si_meminfo(&si);
    get_ram_pfn_range(&first_pfn, &end_pfn);

    len += scnprintf(text + len, REPORT_SIZE - len,
                     "RAMScope physical memory report\n"
                     "  Total RAM     : %llu MB\n"
                     "  Free RAM      : %llu MB\n"
                     "  Available RAM : %llu MB\n"
                     "  Page size     : %lu bytes\n"
                     "  RAM PFN range : %lu .. %lu\n",
                     ((u64)si.totalram * PAGE_SIZE) >> 20,
                     ((u64)si.freeram * PAGE_SIZE) >> 20,
                     ((u64)si_mem_available() * PAGE_SIZE) >> 20,
                     PAGE_SIZE, first_pfn, end_pfn);

    mutex_lock(&g_lock);
    len += scnprintf(text + len, REPORT_SIZE - len,
                     "  Locked by RAMScope: %llu MB\n\n"
                     "  ID   Label                            Start PFN     Pages  Blocks\n",
                     ((u64)g_reserved_pages * PAGE_SIZE) >> 20);
    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        struct ramscope_region *r = g_regions[i];

        if (r)
            len += scnprintf(text + len, REPORT_SIZE - len,
                             "  %-4u %-32s %-12lu %7lu  %u\n",
                             r->region_id, r->label, r->first_pfn,
                             r->nr_pages, r->nr_chunks);
    }
    mutex_unlock(&g_lock);

    ret = simple_read_from_buffer(buf, count, ppos, text, len);
    kfree(text);
    return ret;
}


/* ===================================================================== */
/* Part 8: device file and module load / unload                          */
/* ===================================================================== */

static const struct file_operations ramscope_fops = {
    .owner          = THIS_MODULE,
    .read           = ramscope_read,
    .unlocked_ioctl = ramscope_ioctl,
};

/* A "misc" device is the simplest way to get a file in /dev */
static struct miscdevice ramscope_miscdev = {
    .minor = MISC_DYNAMIC_MINOR,    /* let the kernel choose the number  */
    .name  = DEVICE_NAME,           /* -> /dev/ramscope                  */
    .fops  = &ramscope_fops,
    .mode  = 0666,                  /* read + write, needed for reserve  */
};

/* Runs on: sudo insmod ramscope.ko */
static int __init ramscope_init(void)
{
    unsigned long first_pfn, end_pfn;
    int ret;

    ret = misc_register(&ramscope_miscdev);
    if (ret) {
        pr_err("failed to register /dev/%s (error %d)\n", DEVICE_NAME, ret);
        return ret;
    }

    get_ram_pfn_range(&first_pfn, &end_pfn);
    pr_info("loaded: /dev/%s ready, RAM PFN range %lu..%lu\n",
            DEVICE_NAME, first_pfn, end_pfn);
    return 0;
}

/* Runs on: sudo rmmod ramscope - every reservation goes back to Linux */
static void __exit ramscope_exit(void)
{
    int i;

    misc_deregister(&ramscope_miscdev);   /* no new requests from now on */

    mutex_lock(&g_lock);
    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        if (g_regions[i]) {
            free_region(g_regions[i]);
            g_regions[i] = NULL;
        }
    }
    g_reserved_pages = 0;
    mutex_unlock(&g_lock);

    pr_info("unloaded, all reserved memory returned to Linux\n");
}

module_init(ramscope_init);
module_exit(ramscope_exit);
