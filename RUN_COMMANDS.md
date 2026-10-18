# RAMScope Run Commands

> **WSL Limitation Note**: WSL2 runs inside a virtual machine. `/proc/kpageflags`, `/proc/kpagecount`, and `/proc/<pid>/pagemap` inspect WSL2 guest VM physical memory, not host Windows physical RAM. Kernel module compilation requires matching WSL2 kernel headers (`linux-headers-$(uname -r)`).

---

### 1. Backend Activation

**Ubuntu (WSL)**
```bash
cd /mnt/f/PROJECTS/ramscope/backend
source venv/bin/activate
pip install -r requirements.txt
```

---

### 2. RAM Mapping Authorization

**Ubuntu (WSL)**

* Check access to `/proc/kpageflags`:
```bash
sudo head -c 8 /proc/kpageflags > /dev/null && echo "kpageflags: OK" || echo "kpageflags: DENIED"
```

* Check access to `/proc/kpagecount`:
```bash
sudo head -c 8 /proc/kpagecount > /dev/null && echo "kpagecount: OK" || echo "kpagecount: DENIED"
```

* Check access to `/proc/<pid>/pagemap`:
```bash
sudo head -c 8 /proc/self/pagemap > /dev/null && echo "pagemap: OK" || echo "pagemap: DENIED"
```

* (Optional) Compile and load the kernel module (`/dev/ramscope`):
```bash
cd /mnt/f/PROJECTS/ramscope/kernel
make
sudo insmod ramscope.ko
ls -l /dev/ramscope
```

---

### 3. Start Backend

**Ubuntu (WSL)**

* Privileged mode (required for physical PFN & pagemap access):
```bash
cd /mnt/f/PROJECTS/ramscope/backend
sudo $(which python) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

* Standard mode (basic `/proc/meminfo` metrics only):
```bash
cd /mnt/f/PROJECTS/ramscope/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

### 4. Start Frontend

**PowerShell (Windows)**
```powershell
cd F:\PROJECTS\ramscope
npm run dev
```

**Ubuntu (WSL)**
```bash
cd /mnt/f/PROJECTS/ramscope
npm run dev
```

*Frontend URL: `http://localhost:3000`*

---

### 5. Stop Everything

* **Stop Backend / Frontend**: Press `Ctrl + C` in their respective terminal windows.
* **Unload Kernel Module** (Ubuntu WSL):
```bash
sudo rmmod ramscope
```
