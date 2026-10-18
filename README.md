# RAMScope — Physical RAM Visualization & Monitoring System

RAMScope is an educational Linux physical-memory visualization and monitoring system that exposes the physical-memory layer normally abstracted away by virtual memory.

---

## Architecture Overview

```
                        Linux Physical RAM
                                │
                                ▼
                    Linux Kernel Subsystems
         (/proc/meminfo, /proc/kpageflags, /proc/<pid>/pagemap)
                                │
                                ▼
                     RAMScope Kernel Module
                (C Character Device: /dev/ramscope)
                                │
                                ▼
                      Python FastAPI Backend
             (RAM Service, Page Service, Process Service)
                                │
                      REST API + WebSocket
                                │
                                ▼
                 Next.js 16 + React 19 Frontend
               (Clean Light 2D Canvas Memory Map)
```

---

## Key Features & Operating Modes

### 1. Normal Mode (Standard User Access)
* **Real Global RAM Statistics**: Reads real system RAM metrics from `/proc/meminfo` and `os.sysconf("SC_PAGE_SIZE")` (`MemTotal`, `MemAvailable`, `MemFree`, `Buffers`, `Cached`, `Slab`).
* **Real Physical Page Calculation**: `Total Pages = Total RAM / Page Size` (e.g. 4,164,734 pages for 16 GB RAM).
* **Aggregated Memory Grid**: 2D Canvas rendering of physical address space with customizable bucket resolutions (128, 256, 512, 1024 blocks).
* **Real Process Memory Monitoring**: Live tracking of PID, Name, RSS, PSS, VSZ, and memory percentage.

### 2. Privileged Mode (`sudo` / `CAP_SYS_ADMIN`)
* **Hardware PFN Inspection**: Directly queries physical page frames via `/dev/ramscope` IOCTL or `/proc/kpageflags` and `/proc/kpagecount`.
* **Kernel Page Flags**: Decodes Linux kernel page flags (`Anon`, `Active`, `Slab`, `Buddy`, `Reserved`, `Mmap`, `CompoundHead`, `Dirty`, etc.).
* **Process Virtual-to-Physical Address Translation**: Parses `/proc/<pid>/pagemap` to map virtual pages to hardware PFNs.
* **Process RAM Highlight**: Visually highlights all physical page frames allocated to a selected process on the RAM canvas.

---

## Setup & Running Instructions

### 1. (Optional) Build and Load the Kernel Module on Linux
```bash
cd kernel
make
sudo insmod ramscope.ko

# Verify
dmesg | tail -n 10
```

### 2. Run the FastAPI Backend
```bash
# Navigate to the backend directory
cd backend

# (Optional) Create and activate a virtual environment
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows (PowerShell):
# .\venv\Scripts\Activate.ps1

pip install -r requirements.txt

# Run with standard permissions:
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Or on Linux with elevated permissions for hardware PFN inspection:
sudo $(which python) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The FastAPI Swagger interactive documentation is accessible at: [http://localhost:8000/docs](http://localhost:8000/docs).

### 3. Run the Next.js Frontend
```bash
# In the project root directory
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

#### Environment Variables
By default, the frontend connects to `http://127.0.0.1:8000`. To customize the backend URL, create a `.env.local` file:
```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

---

## API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Root health status and privilege summary. |
| `GET` | `/docs` | OpenAPI / Swagger interactive API documentation. |
| `GET` | `/api/status` | Reports Linux platform status, root privileges, and kernel module access. |
| `GET` | `/api/ram` | Returns real system RAM stats (`totalBytes`, `usedBytes`, `availableBytes`, `pageSize`, `totalPages`, `maxPfn`). |
| `GET` | `/api/pages?resolution=512` | Returns aggregated physical RAM page frames and bucket states. |
| `GET` | `/api/page/{pfn}` | Inspects detailed flags and process mappings for a single PFN. |
| `GET` | `/api/processes?limit=200` | Lists running processes with real RSS, PSS, VSZ, and memory percentage. |
| `GET` | `/api/process/{pid}` | Retrieves memory statistics for a specific PID. |
| `GET` | `/api/process/{pid}/pages` | Translates virtual address spaces into physical PFNs for the specified PID. |
| `WS` | `/ws/live` | Real-time WebSocket streaming RAM updates every 1.5 seconds. |
