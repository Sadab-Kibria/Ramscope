obj-m += ramscope.o

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD  := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
	rm -f test_ioctl

test: test_ioctl
	gcc -O2 -Wall test_ioctl.c -o test_ioctl

.PHONY: all clean test
