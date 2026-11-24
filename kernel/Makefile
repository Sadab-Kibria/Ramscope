obj-m += ramscope.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

test: test_ioctl.c ramscope.h
	$(CC) -O2 -Wall -Wextra test_ioctl.c -o test_ioctl

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
	rm -f test_ioctl

.PHONY: all clean test
