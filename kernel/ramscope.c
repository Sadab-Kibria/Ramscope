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

#include "ramscope.h"

#define DEVICE_NAME "ramscope"
#define BATCH_CHUNK_SIZE 1024

MODULE_LICENSE("GPL");
MODULE_AUTHOR("RAMScope Team");
MODULE_DESCRIPTION("RAMScope Physical Memory Inspection Module");
MODULE_VERSION("1.0.0");

/* Safely classify a single PFN */
static void inspect_pfn(unsigned long pfn, struct ramscope_pfn_info *info)
{
    memset(info, 0, sizeof(*info));
    info->pfn = pfn;

    if (!pfn_valid(pfn)) {
        info->status = RAMSCOPE_PAGE_STATUS_INVALID;
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

static long ramscope_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    switch (cmd) {
    case RAMSCOPE_IOC_GET_RAM_INFO:
        return ramscope_get_ram_info((struct ramscope_ram_info __user *)arg);
    case RAMSCOPE_IOC_QUERY_PFNS:
        return ramscope_query_pfns((struct ramscope_pfn_query __user *)arg);
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
    .mode  = 0444, /* Read-only permissions for safety */
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
    misc_deregister(&ramscope_miscdev);
    pr_info("ramscope: module unloaded\n");
}

module_init(ramscope_init);
module_exit(ramscope_exit);
