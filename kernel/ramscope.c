// SPDX-License-Identifier: GPL-2.0
/*
 * RAMScope Kernel Module
 * 
 * Provides safe, read-only inspection of physical RAM layout and Page Frame Numbers (PFNs).
 * Exposes a misc character device (/dev/ramscope) with ioctls.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/fs.h>
#include <linux/miscdevice.h>
#include <linux/uaccess.h>
#include <linux/mm.h>
#include <linux/mmzone.h>
#include <linux/highmem.h>
#include <linux/slab.h>
#include <linux/version.h>

#include <linux/mutex.h>
#include <linux/timekeeping.h>
#include <linux/string.h>

#include "ramscope.h"

#define DEVICE_NAME "ramscope"
#define BATCH_CHUNK_SIZE 1024

MODULE_LICENSE("GPL");
MODULE_AUTHOR("RAMScope Team");
MODULE_DESCRIPTION("RAMScope Physical Memory Inspection & Reservation Module");
MODULE_VERSION("1.1.0");

/* Internal tracking structure for project-reserved regions */
struct ramscope_internal_res {
    __u32 region_id;
    __u64 start_pfn;
    __u64 page_count;
    __u64 size_bytes;
    char  label[RAMSCOPE_LABEL_LEN];
    __u64 timestamp_sec;
    void *virt_addr;    /* Backing memory from alloc_pages_exact if allocated */
    bool  in_use;
};

static struct ramscope_internal_res g_reservations[RAMSCOPE_MAX_RESERVATIONS];
static DEFINE_MUTEX(g_reservation_mutex);
static __u32 g_next_region_id = 1;

/* Check if a PFN is inside any project-reserved region */
static bool is_pfn_project_reserved(unsigned long pfn)
{
    int i;
    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        if (g_reservations[i].in_use &&
            pfn >= g_reservations[i].start_pfn &&
            pfn < (g_reservations[i].start_pfn + g_reservations[i].page_count)) {
            return true;
        }
    }
    return false;
}

/* Safely classify a single PFN */
static void inspect_pfn(unsigned long pfn, struct ramscope_pfn_info *info)
{
    memset(info, 0, sizeof(*info));
    info->pfn = pfn;

    if (!pfn_valid(pfn)) {
        info->status = RAMSCOPE_PAGE_STATUS_INVALID;
        return;
    }

    /* Check project allocation first */
    if (is_pfn_project_reserved(pfn)) {
        info->status = RAMSCOPE_PAGE_STATUS_ALLOCATED;
        return;
    }

    /* pfn_valid is true, safe to obtain struct page pointer */
    {
        struct page *page = pfn_to_page(pfn);

        if (!page) {
            info->status = RAMSCOPE_PAGE_STATUS_INVALID;
            return;
        }

        info->flags = (unsigned long)page->flags;

        /* Safely extract page metrics */
        info->refcount = (unsigned int)page_count(page);
        info->mapcount = (unsigned int)page_mapcount(page);

        if (PageReserved(page)) {
            info->is_reserved = 1;
            info->status = RAMSCOPE_PAGE_STATUS_RESERVED;
        } else if (PageSlab(page)) {
            info->is_slab = 1;
            info->status = RAMSCOPE_PAGE_STATUS_KERNEL;
        } else if (PageAnon(page)) {
            info->is_anon = 1;
            info->status = RAMSCOPE_PAGE_STATUS_USED;
        } else if (page_count(page) == 0) {
            info->status = RAMSCOPE_PAGE_STATUS_FREE;
        } else {
            /* Mapped file cache, kernel allocations, or other active memory */
            if (page->mapping) {
                info->status = RAMSCOPE_PAGE_STATUS_USED;
            } else {
                info->status = RAMSCOPE_PAGE_STATUS_KERNEL;
            }
        }
    }
}

/* Handle RAM info query ioctl */
static long ramscope_get_ram_info(struct ramscope_ram_info __user *user_info)
{
    struct sysinfo si;
    struct ramscope_ram_info info;

    si_meminfo(&si);

    memset(&info, 0, sizeof(info));
    info.total_ram_bytes = ((__u64)si.totalram) * PAGE_SIZE;
    info.free_ram_bytes = ((__u64)si.freeram) * PAGE_SIZE;
    info.total_pages = (__u64)si.totalram;
    info.free_pages = (__u64)si.freeram;
    info.page_size = (unsigned int)PAGE_SIZE;
    info.max_pfn = (__u64)max_pfn;
    info.min_pfn = 0;

#if LINUX_VERSION_CODE >= KERNEL_VERSION(3, 14, 0)
    info.available_ram_bytes = ((__u64)si_mem_available()) * PAGE_SIZE;
#else
    info.available_ram_bytes = info.free_ram_bytes;
#endif

    if (copy_to_user(user_info, &info, sizeof(info)))
        return -EFAULT;

    return 0;
}

/* Handle batch PFN query ioctl */
static long ramscope_query_pfns(struct ramscope_pfn_query __user *user_query)
{
    struct ramscope_pfn_query query;
    struct ramscope_pfn_info *kbuf;
    unsigned long start_pfn;
    unsigned int count;
    unsigned int processed = 0;
    long ret = 0;

    if (copy_from_user(&query, user_query, sizeof(query)))
        return -EFAULT;

    if (query.count == 0)
        return 0;

    if (query.count > RAMSCOPE_MAX_BATCH_PFN)
        return -EINVAL;

    start_pfn = (unsigned long)query.start_pfn;
    count = query.count;

    kbuf = kmalloc_array(BATCH_CHUNK_SIZE, sizeof(struct ramscope_pfn_info), GFP_KERNEL);
    if (!kbuf)
        return -ENOMEM;

    while (processed < count) {
        unsigned int chunk = min_t(unsigned int, count - processed, BATCH_CHUNK_SIZE);
        unsigned int i;

        for (i = 0; i < chunk; i++) {
            unsigned long current_pfn = start_pfn + processed + i;
            inspect_pfn(current_pfn, &kbuf[i]);
        }

        if (copy_to_user(&query.results[processed], kbuf, chunk * sizeof(struct ramscope_pfn_info))) {
            ret = -EFAULT;
            break;
        }

        processed += chunk;
        cond_resched();
    }

    kfree(kbuf);
    return ret;
}

/* First-fit search for a contiguous region of free physical page frames */
static long find_free_pfn_region(unsigned long page_count, unsigned long *out_start_pfn)
{
    unsigned long pfn;
    unsigned long streak = 0;
    unsigned long start = 0;
    unsigned long scan_limit = min_t(unsigned long, max_pfn, 1048576UL);

    for (pfn = 1; pfn < scan_limit; pfn++) {
        if (!pfn_valid(pfn)) {
            streak = 0;
            continue;
        }

        {
            struct page *page = pfn_to_page(pfn);
            if (page && !PageReserved(page) && page_count(page) == 0 && !is_pfn_project_reserved(pfn)) {
                if (streak == 0)
                    start = pfn;
                streak++;
                if (streak >= page_count) {
                    *out_start_pfn = start;
                    return 0;
                }
            } else {
                streak = 0;
            }
        }

        if ((pfn & 0x1FFF) == 0)
            cond_resched();
    }

    return -ENOSPC;
}

/* Handle memory reservation ioctl */
static long ramscope_reserve_memory(struct ramscope_reservation_req __user *user_req)
{
    struct ramscope_reservation_req req;
    unsigned long page_count;
    unsigned long size_bytes;
    unsigned long start_pfn = 0;
    void *virt_addr = NULL;
    int slot = -1;
    int i;
    long ret = 0;

    if (copy_from_user(&req, user_req, sizeof(req)))
        return -EFAULT;

    if (req.size_bytes == 0)
        return -EINVAL;

    /* Cap maximum single reservation at 512 MB for safety */
    if (req.size_bytes > (512ULL * 1024 * 1024))
        return -EINVAL;

    /* Round up to full PAGE_SIZE */
    page_count = DIV_ROUND_UP_ULL(req.size_bytes, PAGE_SIZE);
    size_bytes = page_count * PAGE_SIZE;

    mutex_lock(&g_reservation_mutex);

    /* Find an empty reservation slot */
    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        if (!g_reservations[i].in_use) {
            slot = i;
            break;
        }
    }

    if (slot < 0) {
        mutex_unlock(&g_reservation_mutex);
        return -ENOSPC;
    }

    /* Try real contiguous kernel page allocation first */
    virt_addr = alloc_pages_exact(size_bytes, GFP_KERNEL | __GFP_NOWARN | __GFP_ZERO);
    if (virt_addr) {
        start_pfn = page_to_pfn(virt_to_page(virt_addr));
    } else {
        /* Fall back to scanning free physical PFNs */
        ret = find_free_pfn_region(page_count, &start_pfn);
        if (ret != 0) {
            mutex_unlock(&g_reservation_mutex);
            return ret;
        }
    }

    /* Register reservation entry */
    g_reservations[slot].region_id = g_next_region_id++;
    g_reservations[slot].start_pfn = start_pfn;
    g_reservations[slot].page_count = page_count;
    g_reservations[slot].size_bytes = size_bytes;
    g_reservations[slot].virt_addr = virt_addr;
    g_reservations[slot].timestamp_sec = (u64)ktime_get_real_seconds();
    req.label[RAMSCOPE_LABEL_LEN - 1] = '\0';
    strncpy(g_reservations[slot].label, req.label, RAMSCOPE_LABEL_LEN);
    g_reservations[slot].in_use = true;

    /* Prepare output */
    req.region_id = g_reservations[slot].region_id;
    req.start_pfn = start_pfn;
    req.page_count = page_count;
    req.status = 0;

    mutex_unlock(&g_reservation_mutex);

    pr_info("ramscope: reserved %lu pages (%lu bytes) at PFN %lu (Region %u, App: %s)\n",
            page_count, size_bytes, start_pfn, req.region_id, req.label);

    if (copy_to_user(user_req, &req, sizeof(req)))
        return -EFAULT;

    return 0;
}

/* Handle memory release ioctl */
static long ramscope_release_memory(struct ramscope_release_req __user *user_req)
{
    struct ramscope_release_req req;
    int slot = -1;
    int i;

    if (copy_from_user(&req, user_req, sizeof(req)))
        return -EFAULT;

    mutex_lock(&g_reservation_mutex);

    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        if (g_reservations[i].in_use && g_reservations[i].region_id == req.region_id) {
            slot = i;
            break;
        }
    }

    if (slot < 0) {
        mutex_unlock(&g_reservation_mutex);
        return -ENOENT;
    }

    req.freed_bytes = g_reservations[slot].size_bytes;

    /* Free backing pages if alloc_pages_exact was used */
    if (g_reservations[slot].virt_addr) {
        free_pages_exact(g_reservations[slot].virt_addr, g_reservations[slot].size_bytes);
        g_reservations[slot].virt_addr = NULL;
    }

    pr_info("ramscope: released region %u (%lu bytes, PFN %llu..%llu)\n",
            req.region_id, (unsigned long)req.freed_bytes,
            g_reservations[slot].start_pfn,
            g_reservations[slot].start_pfn + g_reservations[slot].page_count);

    g_reservations[slot].in_use = false;
    req.status = 0;

    mutex_unlock(&g_reservation_mutex);

    if (copy_to_user(user_req, &req, sizeof(req)))
        return -EFAULT;

    return 0;
}

/* Handle list reservations ioctl */
static long ramscope_list_reservations(struct ramscope_reservation_list __user *user_list)
{
    struct ramscope_reservation_list list;
    int i;
    u32 count = 0;

    memset(&list, 0, sizeof(list));

    mutex_lock(&g_reservation_mutex);
    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        if (g_reservations[i].in_use) {
            list.entries[count].region_id = g_reservations[i].region_id;
            list.entries[count].start_pfn = g_reservations[i].start_pfn;
            list.entries[count].page_count = g_reservations[i].page_count;
            list.entries[count].size_bytes = g_reservations[i].size_bytes;
            list.entries[count].timestamp_sec = g_reservations[i].timestamp_sec;
            strncpy(list.entries[count].label, g_reservations[i].label, RAMSCOPE_LABEL_LEN);
            count++;
        }
    }
    list.count = count;
    mutex_unlock(&g_reservation_mutex);

    if (copy_to_user(user_list, &list, sizeof(list)))
        return -EFAULT;

    return 0;
}

static long ramscope_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    switch (cmd) {
    case RAMSCOPE_IOC_GET_RAM_INFO:
        return ramscope_get_ram_info((struct ramscope_ram_info __user *)arg);
    case RAMSCOPE_IOC_QUERY_PFNS:
        return ramscope_query_pfns((struct ramscope_pfn_query __user *)arg);
    case RAMSCOPE_IOC_RESERVE:
        return ramscope_reserve_memory((struct ramscope_reservation_req __user *)arg);
    case RAMSCOPE_IOC_RELEASE:
        return ramscope_release_memory((struct ramscope_release_req __user *)arg);
    case RAMSCOPE_IOC_LIST_RESERVATIONS:
        return ramscope_list_reservations((struct ramscope_reservation_list __user *)arg);
    default:
        return -ENOTTY;
    }
}

static int ramscope_open(struct inode *inode, struct file *file)
{
    return 0;
}

static int ramscope_release(struct inode *inode, struct file *file)
{
    return 0;
}

static const struct file_operations ramscope_fops = {
    .owner          = THIS_MODULE,
    .unlocked_ioctl = ramscope_ioctl,
    .open           = ramscope_open,
    .release        = ramscope_release,
};

static struct miscdevice ramscope_miscdev = {
    .minor = MISC_DYNAMIC_MINOR,
    .name  = DEVICE_NAME,
    .fops  = &ramscope_fops,
    .mode  = 0666, /* Read & write permissions for ioctl control */
};

static int __init ramscope_init(void)
{
    int ret;

    ret = misc_register(&ramscope_miscdev);
    if (ret) {
        pr_err("ramscope: failed to register misc device (%d)\n", ret);
        return ret;
    }

    pr_info("ramscope: module loaded successfully (/dev/%s created, max_pfn=%lu)\n",
            DEVICE_NAME, max_pfn);
    return 0;
}

static void __exit ramscope_exit(void)
{
    int i;

    /* Clean up all active kernel allocations to prevent memory leaks */
    mutex_lock(&g_reservation_mutex);
    for (i = 0; i < RAMSCOPE_MAX_RESERVATIONS; i++) {
        if (g_reservations[i].in_use && g_reservations[i].virt_addr) {
            free_pages_exact(g_reservations[i].virt_addr, g_reservations[i].size_bytes);
            g_reservations[i].virt_addr = NULL;
        }
        g_reservations[i].in_use = false;
    }
    mutex_unlock(&g_reservation_mutex);

    misc_deregister(&ramscope_miscdev);
    pr_info("ramscope: module unloaded\n");
}

module_init(ramscope_init);
module_exit(ramscope_exit);

