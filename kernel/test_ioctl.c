#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <stdint.h>
#include <string.h>
#include "ramscope.h"

int main(int argc, char **argv)
{
    int fd = open("/dev/ramscope", O_RDWR);
    if (fd < 0) {
        /* Fall back to O_RDONLY if write not allowed */
        fd = open("/dev/ramscope", O_RDONLY);
    }
    if (fd < 0) {
        perror("Failed to open /dev/ramscope");
        return 1;
    }

    struct ramscope_ram_info info;
    if (ioctl(fd, RAMSCOPE_IOC_GET_RAM_INFO, &info) < 0) {
        perror("ioctl RAMSCOPE_IOC_GET_RAM_INFO failed");
        close(fd);
        return 1;
    }

    printf("=== RAMScope Kernel Module Test ===\n");
    printf("Total RAM:      %llu bytes (%.2f GB)\n", 
           (unsigned long long)info.total_ram_bytes, 
           (double)info.total_ram_bytes / (1024*1024*1024));
    printf("Free RAM:       %llu bytes (%.2f GB)\n", 
           (unsigned long long)info.free_ram_bytes, 
           (double)info.free_ram_bytes / (1024*1024*1024));
    printf("Available RAM:  %llu bytes (%.2f GB)\n", 
           (unsigned long long)info.available_ram_bytes, 
           (double)info.available_ram_bytes / (1024*1024*1024));
    printf("Page Size:      %u bytes\n", info.page_size);
    printf("Total Pages:    %llu\n", (unsigned long long)info.total_pages);
    printf("Max PFN:        %llu (0x%llx)\n", 
           (unsigned long long)info.max_pfn, (unsigned long long)info.max_pfn);

    /* Test querying first 10 PFNs */
    struct ramscope_pfn_info results[10];
    struct ramscope_pfn_query query = {
        .start_pfn = 1,
        .count = 10,
        .results = results,
    };

    if (ioctl(fd, RAMSCOPE_IOC_QUERY_PFNS, &query) == 0) {
        printf("\nInspecting PFNs 1-10:\n");
        for (int i = 0; i < 10; i++) {
            const char *status_str = "UNKNOWN";
            switch (results[i].status) {
                case RAMSCOPE_PAGE_STATUS_FREE:      status_str = "FREE"; break;
                case RAMSCOPE_PAGE_STATUS_USED:      status_str = "USED"; break;
                case RAMSCOPE_PAGE_STATUS_KERNEL:    status_str = "KERNEL"; break;
                case RAMSCOPE_PAGE_STATUS_RESERVED:  status_str = "RESERVED"; break;
                case RAMSCOPE_PAGE_STATUS_ALLOCATED: status_str = "ALLOCATED"; break;
                case RAMSCOPE_PAGE_STATUS_INVALID:   status_str = "INVALID"; break;
            }
            printf("  PFN %llu: Status=%-9s MapCount=%u RefCount=%u Flags=0x%llx\n",
                   (unsigned long long)results[i].pfn,
                   status_str,
                   results[i].mapcount,
                   results[i].refcount,
                   (unsigned long long)results[i].flags);
        }
    } else {
        perror("ioctl RAMSCOPE_IOC_QUERY_PFNS failed");
    }

    /* Test Reservation System */
    printf("\n=== Testing Memory Allocation (Step 6) ===\n");
    struct ramscope_reservation_req res_req;
    memset(&res_req, 0, sizeof(res_req));
    res_req.size_bytes = 4 * 1024 * 1024; /* 4 MB */
    strncpy(res_req.label, "RUET_TestApp", sizeof(res_req.label));

    if (ioctl(fd, RAMSCOPE_IOC_RESERVE, &res_req) == 0) {
        printf("✅ Successfully Reserved %llu bytes (%llu pages) for '%s'!\n",
               (unsigned long long)res_req.size_bytes,
               (unsigned long long)res_req.page_count,
               res_req.label);
        printf("   Region ID: %u, Starting PFN: %llu\n",
               res_req.region_id,
               (unsigned long long)res_req.start_pfn);

        /* Inspect the newly allocated PFN to verify status is ALLOCATED */
        struct ramscope_pfn_info alloc_info[1];
        struct ramscope_pfn_query chk_query = {
            .start_pfn = res_req.start_pfn,
            .count = 1,
            .results = alloc_info,
        };
        if (ioctl(fd, RAMSCOPE_IOC_QUERY_PFNS, &chk_query) == 0) {
            printf("   Inspected PFN %llu status: %s (status code %u)\n",
                   (unsigned long long)alloc_info[0].pfn,
                   alloc_info[0].status == RAMSCOPE_PAGE_STATUS_ALLOCATED ? "ALLOCATED (Correct)" : "OTHER",
                   alloc_info[0].status);
        }

        /* List Active Reservations */
        struct ramscope_reservation_list r_list;
        if (ioctl(fd, RAMSCOPE_IOC_LIST_RESERVATIONS, &r_list) == 0) {
            printf("\nActive Reservations in Kernel (%u):\n", r_list.count);
            for (uint32_t j = 0; j < r_list.count; j++) {
                printf("  [%u] Region %u: App='%s', Start PFN=%llu, Pages=%llu, Size=%llu bytes\n",
                       j + 1,
                       r_list.entries[j].region_id,
                       r_list.entries[j].label,
                       (unsigned long long)r_list.entries[j].start_pfn,
                       (unsigned long long)r_list.entries[j].page_count,
                       (unsigned long long)r_list.entries[j].size_bytes);
            }
        }

        /* Test Release */
        printf("\n=== Testing Memory Deallocation ===\n");
        struct ramscope_release_req rel_req = {
            .region_id = res_req.region_id,
        };
        if (ioctl(fd, RAMSCOPE_IOC_RELEASE, &rel_req) == 0) {
            printf("✅ Successfully Released Region %u! (%llu bytes freed)\n",
                   res_req.region_id,
                   (unsigned long long)rel_req.freed_bytes);
        } else {
            perror("ioctl RAMSCOPE_IOC_RELEASE failed");
        }
    } else {
        perror("ioctl RAMSCOPE_IOC_RESERVE failed (Run as root or check driver permissions)");
    }

    close(fd);
    return 0;
}
