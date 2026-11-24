/*
 * test_ioctl.c - command-line tester for the RAMScope kernel module
 *
 * Build:   make test
 *
 * Usage:
 *   sudo ./test_ioctl                        full self-test (info, reserve 32 MB,
 *                                            verify it is locked, release it)
 *   sudo ./test_ioctl info                   RAM numbers + status of every page
 *   sudo ./test_ioctl inspect <pfn> [count]  inspect individual PFNs (default 10)
 *   sudo ./test_ioctl reserve <MB> <label>   reserve memory and KEEP it
 *   sudo ./test_ioctl release <id>           give a reservation back to Linux
 *   sudo ./test_ioctl list                   list all reservations
 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include "ramscope.h"

#define DEVICE      "/dev/ramscope"
#define NUM_STATUS  6
#define MAX_SHOWN_RANGES 64

static const char *status_names[NUM_STATUS] = {
    "invalid", "free", "used", "kernel", "reserved", "allocated"
};

static const char *status_name(unsigned int s)
{
    return s < NUM_STATUS ? status_names[s] : "unknown";
}

/* MemAvailable from /proc/meminfo (in MB): how much RAM Linux can still hand out */
static long mem_available_mb(void)
{
    FILE *f = fopen("/proc/meminfo", "r");
    char line[256];
    long kb = -1;

    if (!f)
        return -1;
    while (fgets(line, sizeof(line), f))
        if (sscanf(line, "MemAvailable: %ld kB", &kb) == 1)
            break;
    fclose(f);
    return kb < 0 ? -1 : kb / 1024;
}

/* Print a helpful hint for the most common errors */
static void explain_error(const char *what)
{
    int e = errno;

    fprintf(stderr, "%s failed: %s\n", what, strerror(e));
    switch (e) {
    case ENOMEM:
        fprintf(stderr, "  -> not enough free RAM, or a safety limit was hit "
                        "(see: sudo dmesg | tail)\n");
        break;
    case ENOSPC:
        fprintf(stderr, "  -> all %d reservation slots are in use, release one first\n",
                RAMSCOPE_MAX_RESERVATIONS);
        break;
    case EINVAL:
        fprintf(stderr, "  -> size must be between 1 byte and 512 MB\n");
        break;
    case ENOENT:
        fprintf(stderr, "  -> no reservation with that region ID\n");
        break;
    case EBADF:
    case EPERM:
    case EACCES:
        fprintf(stderr, "  -> no write access to %s (try sudo)\n", DEVICE);
        break;
    }
}

/* Ask the module about one single page */
static int query_one(int fd, uint64_t pfn, struct ramscope_pfn_info *out)
{
    struct ramscope_pfn_query q = { .start_pfn = pfn, .count = 1, .results = out };

    return ioctl(fd, RAMSCOPE_IOC_QUERY_PFNS, &q);
}


/* ---------------------------------------------------------------------- */
/* info: RAM numbers + count every page by status                          */
/* ---------------------------------------------------------------------- */
static int cmd_info(int fd)
{
    struct ramscope_ram_info info;
    struct ramscope_pfn_info *buf;
    unsigned long long counts[NUM_STATUS + 1] = { 0 };
    uint64_t pfn;
    int i;

    if (ioctl(fd, RAMSCOPE_IOC_GET_RAM_INFO, &info) < 0) {
        explain_error("GET_RAM_INFO");
        return 1;
    }

    printf("=== RAM information ===\n");
    printf("Total RAM     : %llu MB\n", (unsigned long long)info.total_ram_bytes >> 20);
    printf("Free RAM      : %llu MB\n", (unsigned long long)info.free_ram_bytes >> 20);
    printf("Available RAM : %llu MB\n", (unsigned long long)info.available_ram_bytes >> 20);
    printf("Page size     : %u bytes\n", info.page_size);
    printf("Total pages   : %llu\n", (unsigned long long)info.total_pages);
    printf("PFN range     : %llu .. %llu\n",
           (unsigned long long)info.min_pfn, (unsigned long long)info.max_pfn);

    /* Scan every physical page, RAMSCOPE_MAX_BATCH_PFN pages per call */
    buf = malloc(RAMSCOPE_MAX_BATCH_PFN * sizeof(*buf));
    if (!buf) {
        perror("malloc");
        return 1;
    }

    for (pfn = info.min_pfn; pfn < info.max_pfn; ) {
        uint64_t left = info.max_pfn - pfn;
        uint32_t n = left < RAMSCOPE_MAX_BATCH_PFN ? (uint32_t)left : RAMSCOPE_MAX_BATCH_PFN;
        struct ramscope_pfn_query q = { .start_pfn = pfn, .count = n, .results = buf };
        uint32_t k;

        if (ioctl(fd, RAMSCOPE_IOC_QUERY_PFNS, &q) < 0) {
            explain_error("QUERY_PFNS");
            free(buf);
            return 1;
        }
        for (k = 0; k < n; k++)
            counts[buf[k].status < NUM_STATUS ? buf[k].status : NUM_STATUS]++;
        pfn += n;
    }
    free(buf);

    printf("\n=== Status of every physical page ===\n");
    for (i = 0; i < NUM_STATUS; i++)
        printf("  %-10s %10llu pages  (%llu MB)\n", status_names[i], counts[i],
               counts[i] * info.page_size >> 20);
    return 0;
}

/* Inspect 'count' individual PFNs starting at 'start_pfn' */
static int cmd_inspect(int fd, uint64_t start_pfn, uint32_t count)
{
    struct ramscope_pfn_info *buf;
    struct ramscope_pfn_query q;
    uint32_t i;

    if (count == 0 || count > RAMSCOPE_MAX_BATCH_PFN) {
        fprintf(stderr, "count must be between 1 and %d\n", RAMSCOPE_MAX_BATCH_PFN);
        return 1;
    }

    buf = calloc(count, sizeof(*buf));
    if (!buf) {
        perror("calloc");
        return 1;
    }

    memset(&q, 0, sizeof(q));
    q.start_pfn = start_pfn;
    q.count = count;
    q.results = buf;

    if (ioctl(fd, RAMSCOPE_IOC_QUERY_PFNS, &q) < 0) {
        explain_error("QUERY_PFNS");
        free(buf);
        return 1;
    }

    printf("=== Inspecting PFNs %llu .. %llu ===\n",
           (unsigned long long)start_pfn,
           (unsigned long long)(start_pfn + count - 1));
    for (i = 0; i < count; i++) {
        printf("  PFN %-8llu  Status=%-9s  RefCount=%-4u  MapCount=%-4u  Flags=0x%llx\n",
               (unsigned long long)buf[i].pfn,
               status_name(buf[i].status),
               buf[i].refcount,
               buf[i].mapcount,
               (unsigned long long)buf[i].flags);
    }

    free(buf);
    return 0;
}


/* ---------------------------------------------------------------------- */
/* reserve / ranges / release / list                                       */
/* ---------------------------------------------------------------------- */

/* Reserve 'mb' megabytes for 'label'. Fills *req on success. */
static int do_reserve(int fd, unsigned long mb, const char *label,
                      struct ramscope_reservation_req *req)
{
    memset(req, 0, sizeof(*req));
    req->size_bytes = (uint64_t)mb * 1024 * 1024;
    strncpy(req->label, label, RAMSCOPE_LABEL_LEN - 1);

    if (ioctl(fd, RAMSCOPE_IOC_RESERVE, req) < 0) {
        explain_error("RESERVE");
        return -1;
    }

    printf("Reserved region %u for '%s': %llu pages (%lu MB) starting at PFN %llu\n",
           req->region_id, req->label, (unsigned long long)req->page_count, mb,
           (unsigned long long)req->start_pfn);
    return 0;
}

/*
 * Print the physical blocks of a region. If 'verify' is set, also check
 * that the first and last page of every block report status "allocated".
 * Returns the number of failed checks.
 */
static int show_ranges(int fd, uint32_t region_id, int verify)
{
    struct ramscope_pfn_range ranges[MAX_SHOWN_RANGES];
    struct ramscope_region_ranges arg = {
        .region_id = region_id, .max_ranges = MAX_SHOWN_RANGES, .ranges = ranges,
    };
    unsigned int i, shown;
    int failures = 0;

    if (ioctl(fd, RAMSCOPE_IOC_GET_REGION_RANGES, &arg) < 0) {
        explain_error("GET_REGION_RANGES");
        return 1;
    }

    printf("  Physical layout: %u block(s)%s\n", arg.nr_ranges,
           arg.nr_ranges == 1 ? "  -> one unbroken range of physical pages" : "");

    shown = arg.nr_ranges < MAX_SHOWN_RANGES ? arg.nr_ranges : MAX_SHOWN_RANGES;
    for (i = 0; i < shown; i++) {
        uint64_t first = ranges[i].start_pfn;
        uint64_t last  = ranges[i].start_pfn + ranges[i].page_count - 1;

        printf("    PFN %llu .. %llu  (%llu pages)  phys 0x%llx .. 0x%llx\n",
               (unsigned long long)first, (unsigned long long)last,
               (unsigned long long)ranges[i].page_count,
               (unsigned long long)first * 4096, (unsigned long long)(last + 1) * 4096 - 1);

        if (verify) {
            struct ramscope_pfn_info a, b;

            if (query_one(fd, first, &a) < 0 || query_one(fd, last, &b) < 0 ||
                a.status != RAMSCOPE_PAGE_STATUS_ALLOCATED ||
                b.status != RAMSCOPE_PAGE_STATUS_ALLOCATED) {
                printf("    FAIL: pages of this block are not reported as 'allocated'\n");
                failures++;
            }
        }
    }
    if (shown < arg.nr_ranges)
        printf("    ... %u more block(s)\n", arg.nr_ranges - shown);
    return failures;
}

static int do_release(int fd, uint32_t region_id)
{
    struct ramscope_release_req rel = { .region_id = region_id };

    if (ioctl(fd, RAMSCOPE_IOC_RELEASE, &rel) < 0) {
        explain_error("RELEASE");
        return -1;
    }
    printf("Released region %u: %llu MB given back to Linux\n",
           region_id, (unsigned long long)rel.freed_bytes >> 20);
    return 0;
}

static int cmd_list(int fd)
{
    struct ramscope_reservation_list list;
    uint32_t i;

    if (ioctl(fd, RAMSCOPE_IOC_LIST_RESERVATIONS, &list) < 0) {
        explain_error("LIST_RESERVATIONS");
        return 1;
    }

    printf("=== Active reservations: %u ===\n", list.count);
    for (i = 0; i < list.count; i++) {
        struct ramscope_reservation_entry *e = &list.entries[i];

        printf("  Region %u  '%s'  start PFN %llu  %llu pages  (%llu MB)\n",
               e->region_id, e->label, (unsigned long long)e->start_pfn,
               (unsigned long long)e->page_count,
               (unsigned long long)e->size_bytes >> 20);
        show_ranges(fd, e->region_id, 0);
    }
    return 0;
}

static int cmd_reserve_keep(int fd, unsigned long mb, const char *label)
{
    struct ramscope_reservation_req req;

    if (do_reserve(fd, mb, label, &req) < 0)
        return 1;
    show_ranges(fd, req.region_id, 0);
    printf("The memory stays locked. Release it with: sudo ./test_ioctl release %u\n",
           req.region_id);
    return 0;
}


/* ---------------------------------------------------------------------- */
/* self-test                                                               */
/* ---------------------------------------------------------------------- */
static int cmd_selftest(int fd)
{
    const unsigned long test_mb = 32;
    struct ramscope_reservation_req req;
    long before, during, after;
    int failures = 0;

    if (cmd_info(fd) != 0)
        return 1;

    printf("\n=== Self-test: reserve %lu MB ===\n", test_mb);
    before = mem_available_mb();
    if (do_reserve(fd, test_mb, "SelfTest", &req) < 0)
        return 1;
    during = mem_available_mb();

    failures += show_ranges(fd, req.region_id, 1);

    printf("  MemAvailable before: %ld MB, while reserved: %ld MB (dropped %ld MB)\n",
           before, during, before - during);
    if (before - during >= (long)(test_mb * 3 / 4))
        printf("  OK: Linux really lost this memory - it is locked for everyone else\n");
    else
        printf("  NOTE: drop is smaller than expected (other programs freed memory meanwhile?)\n");

    printf("\n");
    cmd_list(fd);

    printf("\n");
    if (do_release(fd, req.region_id) < 0)
        failures++;
    after = mem_available_mb();
    printf("  MemAvailable after release: %ld MB\n", after);

    printf("\n%s (%d failed check(s))\n", failures ? "SELF-TEST FAILED" : "SELF-TEST PASSED",
           failures);
    return failures ? 1 : 0;
}


static void usage(const char *prog)
{
    fprintf(stderr,
            "Usage:\n"
            "  %s                           full self-test\n"
            "  %s info                      RAM numbers + status of every page\n"
            "  %s inspect <pfn> [count]     inspect individual PFNs (default 10)\n"
            "  %s reserve <MB> <label>      reserve memory and keep it\n"
            "  %s release <id>              release a reservation\n"
            "  %s list                      list reservations\n",
            prog, prog, prog, prog, prog, prog);
}

int main(int argc, char **argv)
{
    int fd, ret;

    fd = open(DEVICE, O_RDWR);
    if (fd < 0)
        fd = open(DEVICE, O_RDONLY);    /* enough for info / list */
    if (fd < 0) {
        perror("open " DEVICE " (is the module loaded? run: sudo insmod ramscope.ko)");
        return 1;
    }

    if (argc < 2)
        ret = cmd_selftest(fd);
    else if (!strcmp(argv[1], "info"))
        ret = cmd_info(fd);
    else if (!strcmp(argv[1], "inspect") && argc >= 3)
        ret = cmd_inspect(fd, strtoull(argv[2], NULL, 0),
                          argc >= 4 ? (uint32_t)strtoul(argv[3], NULL, 10) : 10);
    else if (!strcmp(argv[1], "list"))
        ret = cmd_list(fd);
    else if (!strcmp(argv[1], "reserve") && argc >= 3)
        ret = cmd_reserve_keep(fd, strtoul(argv[2], NULL, 10),
                               argc >= 4 ? argv[3] : "TestApp");
    else if (!strcmp(argv[1], "release") && argc >= 3)
        ret = do_release(fd, (uint32_t)strtoul(argv[2], NULL, 10)) < 0 ? 1 : 0;
    else {
        usage(argv[0]);
        ret = 1;
    }

    close(fd);
    return ret;
}
