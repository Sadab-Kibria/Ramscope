import os
import sys
import platform
from app.models.ram import PrivilegeStatus

def check_privileges() -> PrivilegeStatus:
    is_linux = sys.platform.startswith("linux")
    is_root = False
    can_read_kpageflags = False
    can_read_kpagecount = False
    can_read_pagemap = False
    kernel_module_loaded = False

    if is_linux:
        try:
            is_root = (os.geteuid() == 0)
        except AttributeError:
            is_root = False

        # Check /proc/kpageflags
        try:
            if os.path.exists("/proc/kpageflags"):
                with open("/proc/kpageflags", "rb") as f:
                    f.read(8)
                can_read_kpageflags = True
        except (PermissionError, IOError):
            can_read_kpageflags = False

        # Check /proc/kpagecount
        try:
            if os.path.exists("/proc/kpagecount"):
                with open("/proc/kpagecount", "rb") as f:
                    f.read(8)
                can_read_kpagecount = True
        except (PermissionError, IOError):
            can_read_kpagecount = False

        # Check /proc/1/pagemap or /proc/self/pagemap
        try:
            test_pid = "self"
            if os.path.exists(f"/proc/{test_pid}/pagemap"):
                with open(f"/proc/{test_pid}/pagemap", "rb") as f:
                    f.read(8)
                can_read_pagemap = True
        except (PermissionError, IOError):
            can_read_pagemap = False

        # Check kernel device /dev/ramscope
        if os.path.exists("/dev/ramscope"):
            try:
                with open("/dev/ramscope", "rb") as f:
                    pass
                kernel_module_loaded = True
            except (PermissionError, IOError):
                kernel_module_loaded = False

    is_privileged = bool(is_root or can_read_kpageflags or kernel_module_loaded)

    warning_msg = None
    if not is_privileged:
        warning_msg = "Basic memory information available. Run the backend with elevated privileges for detailed physical-frame inspection."

    return PrivilegeStatus(
        platform_is_linux=is_linux,
        is_root=is_root,
        can_read_kpageflags=can_read_kpageflags,
        can_read_kpagecount=can_read_kpagecount,
        can_read_pagemap=can_read_pagemap,
        kernel_module_loaded=kernel_module_loaded,
        device_path="/dev/ramscope" if kernel_module_loaded else None,
        warning_message=warning_msg,
        privileged=is_privileged,
    )
