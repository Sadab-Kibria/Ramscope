# RAMScope Run Commands

> **WSL Limitation Note**: WSL2 runs inside a lightweight virtual machine. `/proc/kpageflags`, `/proc/kpagecount`, and `/proc/<pid>/pagemap` inspect the WSL2 guest VM physical memory, not the host Windows physical RAM. Kernel module compilation requires matching WSL2 kernel headers (`linux-headers-$(uname -r)`).

---

## 🚀 Quick Start Summary

You need **two terminal windows**:
1. **Terminal 1 (WSL / Ubuntu)**: Runs the Python FastAPI Backend on `http://localhost:8000`.
2. **Terminal 2 (Windows PowerShell or WSL)**: Runs the Next.js Frontend on `http://localhost:3000`.

---

### 1. Terminal 1: Backend Setup & Activation

Open **Ubuntu (WSL)**:

```bash
cd /mnt/d/1_3_2_projects/3200/Ramscope/backend

# If virtual environment does not exist yet:
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install required Python packages
pip install -r requirements.txt
```

---

### 2. RAM Mapping Authorization & Checks (Optional but Recommended)

In **Ubuntu (WSL)**, verify privileged access to the physical memory interfaces:

* **Check access to `/proc/kpageflags`**:
  ```bash
  sudo head -c 8 /proc/kpageflags > /dev/null && echo "kpageflags: OK" || echo "kpageflags: DENIED"
  ```

* **Check access to `/proc/kpagecount`**:
  ```bash
  sudo head -c 8 /proc/kpagecount > /dev/null && echo "kpagecount: OK" || echo "kpagecount: DENIED"
  ```

* **Check access to `/proc/<pid>/pagemap`**:
  ```bash
  sudo head -c 8 /proc/self/pagemap > /dev/null && echo "pagemap: OK" || echo "pagemap: DENIED"
  ```

* **(Optional) Compile and load the kernel module (`/dev/ramscope`)**:
  ```bash
  cd /mnt/d/1_3_2_projects/3200/Ramscope/kernel
  make
  sudo insmod ramscope.ko
  ls -l /dev/ramscope
  ```

---

### 3. Terminal 1: Start Backend Server

In **Ubuntu (WSL)**:

* **Privileged Mode** *(Recommended — full access to physical PFNs, page flags, and pagemaps)*:
  ```bash
  cd /mnt/d/1_3_2_projects/3200/Ramscope/backend
  source venv/bin/activate
  sudo $(which python) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
  ```

* **Standard Mode** *(Basic mode — `/proc/meminfo` metrics only, no physical page inspection)*:
  ```bash
  cd /mnt/d/1_3_2_projects/3200/Ramscope/backend
  source venv/bin/activate
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
  ```

* Backend API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)  
* Backend Status: [http://localhost:8000/api/status](http://localhost:8000/api/status)

---

### 4. Terminal 2: Start Frontend Server

Open a **new terminal window** (Windows PowerShell or Ubuntu WSL):

#### Option A: Windows PowerShell (Recommended)
```powershell
cd D:\1_3_2_projects\3200\Ramscope

# Install dependencies (first time only)
npm install

# Start Next.js development server
npm run dev
```

#### Option B: Ubuntu (WSL)
```bash
cd /mnt/d/1_3_2_projects/3200/Ramscope

# Install dependencies (first time only)
npm install

# Start Next.js development server
npm run dev
```

* **Frontend Dashboard URL**: [http://localhost:3000](http://localhost:3000)

---

### 5. Stop Everything

* **Stop Backend & Frontend**: Press `Ctrl + C` in each terminal window.
* **Unload Kernel Module** (Ubuntu WSL, if loaded):
  ```bash
  sudo rmmod ramscope
  ```
