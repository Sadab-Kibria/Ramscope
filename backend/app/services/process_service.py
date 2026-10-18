import os
import psutil
from typing import List, Optional
from app.models.ram import ProcessInfo, ProcessPagesResponse
from app.linux.pagemap import PagemapReader
from app.linux.kpageflags import KpageflagsReader
from app.linux.proc_meminfo import get_system_page_size, read_proc_meminfo

class ProcessService:
    def __init__(self):
        self.kflags = KpageflagsReader()
        self.pagemap_reader = PagemapReader(self.kflags)

    def _read_smaps_pss(self, pid: int) -> Optional[int]:
        rollup_path = f"/proc/{pid}/smaps_rollup"
        if os.path.exists(rollup_path):
            try:
                with open(rollup_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("Pss:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return int(parts[1]) * 1024
            except Exception:
                pass

        smaps_path = f"/proc/{pid}/smaps"
        if os.path.exists(smaps_path):
            total_pss_kb = 0
            found = False
            try:
                with open(smaps_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("Pss:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                total_pss_kb += int(parts[1])
                                found = True
                if found:
                    return total_pss_kb * 1024
            except Exception:
                pass

        return None

    def list_processes(self, limit: int = 200) -> List[ProcessInfo]:
        results: List[ProcessInfo] = []
        page_size = get_system_page_size()
        meminfo = read_proc_meminfo()
        total_ram = int(meminfo.get("MemTotal", 1))

        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info', 'username']):
            try:
                info = proc.info
                pid = info['pid']
                if pid <= 0:
                    continue

                mem = info.get('memory_info')
                rss = int(mem.rss) if mem else 0
                vsz = int(mem.vms) if mem else 0

                pss = self._read_smaps_pss(pid)

                cmdline_list = info.get('cmdline') or []
                cmdline = " ".join(cmdline_list) if cmdline_list else ""

                resident_pages = (rss // page_size) if page_size > 0 else 0
                mem_pct = round((rss / total_ram * 100.0), 2) if total_ram > 0 else 0.0

                results.append(ProcessInfo(
                    pid=pid,
                    name=info.get('name') or f"pid_{pid}",
                    cmdline=cmdline[:120],
                    rss=rss,
                    pss=pss,
                    vsz=vsz,
                    memory_percent=mem_pct,
                    resident_pages=resident_pages,
                    user=info.get('username') or "",
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        results.sort(key=lambda p: (p.pss if p.pss is not None else p.rss), reverse=True)
        return results[:limit]

    def get_process_pages(self, pid: int, max_pages: int = 50000) -> ProcessPagesResponse:
        return self.pagemap_reader.get_process_pages(pid, max_pages=max_pages)
