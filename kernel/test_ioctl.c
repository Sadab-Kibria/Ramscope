#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <stdint.h>
#include "ramscope.h"

int main(int argc, char **argv)
{
    int fd = open("/dev/ramscope", O_RDONLY);
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
                case RAMSCOPE_PAGE_STATUS_FREE:     status_str = "FREE"; break;
                case RAMSCOPE_PAGE_STATUS_USED:     status_str = "USED"; break;
                case RAMSCOPE_PAGE_STATUS_KERNEL:   status_str = "KERNEL"; break;
                case RAMSCOPE_PAGE_STATUS_RESERVED: status_str = "RESERVED"; break;
                case RAMSCOPE_PAGE_STATUS_INVALID:  status_str = "INVALID"; break;
            }
            printf("  PFN %llu: Status=%-8s MapCount=%u RefCount=%u Flags=0x%llx\n",
                   (unsigned long long)results[i].pfn,
                   status_str,
                   results[i].mapcount,
                   results[i].refcount,
                   (unsigned long long)results[i].flags);
        }
    } else {
        perror("ioctl RAMSCOPE_IOC_QUERY_PFNS failed");
    }

    close(fd);
    return 0;
}
