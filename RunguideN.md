# RAMScope — Complete Linux Run Guide (`RunguideN.md`)

This guide covers:
1. **Part 1:** First-time setup & running inside an **Ubuntu VirtualBox VM** (starting from only a shared folder `sf_Ramscope`, with no `~/Ramscope` folder created yet).
2. **Part 2:** **1-second update workflow** when you edit files in Windows (`sf_Ramscope`) — **without** re-downloading Python or Node packages.
3. **Part 3:** Running directly on a **Native / Dual-Boot Linux System** (bare-metal hardware RAM).

---

## Part 1: Running Inside a Linux VM (Starting from Scratch with `sf_Ramscope`)

Assume you just booted your Ubuntu VM and enabled the VirtualBox shared folder (`sf_Ramscope` mounted at `/media/sf_Ramscope`).

### Step 1 — Check Shared Folder Access (One-Time)
```bash
ls /media/sf_Ramscope
```
> **If you see `Permission denied`:** add your user to the `vboxsf` group, then **log out and log back in** (or reboot the VM once):
> ```bash
> sudo usermod -aG vboxsf $USER
> ```

---

### Step 2 — Install Required Ubuntu Packages (One-Time)
Install compiler tools, matching kernel headers, `rsync`, Python `venv`, and Node.js 20+:
```bash
sudo apt update
sudo apt install -y build-essential linux-headers-$(uname -r) python3-venv python3-pip rsync curl

# Check Node.js version (Next.js 16 needs Node >= 20.9):
node -v 2>/dev/null || true
```
If `node` is missing or older than `v20.9`, install Node.js 20 LTS once:
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node -v && npm -v
```

---

### Step 3 — Create `~/Ramscope` & Copy Project Cleanly
Never build directly inside `/media/sf_Ramscope` (VirtualBox shared folders break Linux symlinks and kernel builds). Use `rsync` to copy the project while skipping Windows `venv` / `node_modules`:

```bash
mkdir -p ~/Ramscope

rsync -av \
  --exclude 'venv' \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude '.next' \
  --exclude '__pycache__' \
  /media/sf_Ramscope/ ~/Ramscope/
```

---

### Step 4 — Build & Load the Kernel Module (`ramscope.ko`)
```bash
cd ~/Ramscope/kernel
make clean
make
make test

# Load the kernel driver into Linux
sudo rmmod ramscope 2>/dev/null || true
sudo insmod ramscope.ko

# Verify /dev/ramscope is active and run the 32 MB lock/release self-test
ls -l /dev/ramscope
sudo ./test_ioctl
cat /dev/ramscope
```

---

### Step 5 — Set Up Backend & Frontend Dependencies (One-Time Only)
Because these are created inside `~/Ramscope` on Linux, you **only do this once**:

```bash
# 1. Create Linux Python virtual environment & install backend packages
cd ~/Ramscope/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate

# 2. Install frontend Node packages
cd ~/Ramscope
npm install
```

---

### Step 6 — Run the Full Application (2 Terminals)

**Terminal 1 — Start FastAPI Backend (with `sudo` for full hardware PFN & pagemap access):**
```bash
cd ~/Ramscope/backend
sudo ~/Ramscope/backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Start Next.js Frontend:**
```bash
cd ~/Ramscope
npm run dev
```

Open **`http://localhost:3000`** in your browser.
- Top-right header should show **`/dev/ramscope Active`** and **`Elevated Access (Root)`**.
- Try reserving e.g. `32 MB` in the **Physical RAM Allocation & Reservation** panel, run `free -m` in Ubuntu to see real OS memory drop by 32 MB, and watch the cyan locked block appear on the 2D map.

---

## Part 2: Fast Re-Run After Editing `sf_Ramscope` on Windows (No Re-Downloading!)

When you edit code on Windows, `/media/sf_Ramscope` updates automatically.
**Do NOT delete `~/Ramscope`!** If you keep `~/Ramscope/backend/venv` and `~/Ramscope/node_modules` intact, `rsync` copies **only the changed code files in under 1 second** — no `pip install` and no `npm install` needed.

### Optional: Create a 1-Command Sync Script (Create Once)
Run this once in Ubuntu to create `~/sync.sh`:
```bash
cat << 'EOF' > ~/sync.sh
#!/usr/bin/env bash
set -e
echo "Syncing changed files from /media/sf_Ramscope -> ~/Ramscope ..."
rsync -av \
  --exclude 'venv' \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude '.next' \
  --exclude '__pycache__' \
  --exclude 'kernel/*.o' \
  --exclude 'kernel/*.ko' \
  --exclude 'kernel/*.mod*' \
  --exclude 'kernel/.*.cmd' \
  --exclude 'kernel/Module.symvers' \
  --exclude 'kernel/modules.order' \
  --exclude 'kernel/test_ioctl' \
  /media/sf_Ramscope/ ~/Ramscope/
echo "Sync complete!"
EOF
chmod +x ~/sync.sh
```

### Now Whenever You Change Code on Windows:

- **Case A — You only edited Frontend (`.tsx`/`.ts`) or Backend (`.py`) files:**
  ```bash
  ~/sync.sh
  ```
  *(That's it! Both `uvicorn --reload` and `npm run dev` automatically reload your updated code — zero package downloads.)*

- **Case B — You edited `kernel/` (`.c` / `.h` / `Makefile`):**
  ```bash
  ~/sync.sh
  cd ~/Ramscope/kernel
  make && make test
  sudo rmmod ramscope 2>/dev/null || true
  sudo insmod ramscope.ko
  ```

- **After Rebooting the Ubuntu VM Later:**
  Your `venv`, `node_modules`, and `ramscope.ko` are already built on disk. After a reboot, you only run:
  ```bash
  sudo insmod ~/Ramscope/kernel/ramscope.ko
  # Terminal 1:
  cd ~/Ramscope/backend && sudo ~/Ramscope/backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
  # Terminal 2:
  cd ~/Ramscope && npm run dev
  ```

---

## Part 3: Running on a Native / Dual-Boot Linux System (Bare-Metal Hardware)

On a native or dual-boot Ubuntu installation, Linux runs directly on your laptop/PC hardware, so RAMScope inspects and locks **100% real bare-metal physical RAM** (including real BIOS reserved frames and PCI memory holes).

### Important Before Starting: Disable UEFI Secure Boot
Most dual-boot laptops have **Secure Boot** enabled in BIOS/UEFI. With Secure Boot ON, Linux blocks `sudo insmod ramscope.ko` (`Operation not permitted` / `Key was rejected by service`).
- Restart into BIOS/UEFI (`F2` / `F10` / `Del` / `Esc`) → set **Secure Boot = Disabled** → save and boot Ubuntu.

---

### Step 1 — Install Prerequisites (One-Time)
```bash
sudo apt update
sudo apt install -y git build-essential linux-headers-$(uname -r) python3-venv python3-pip curl

# Install Node.js 20 LTS if node < 20.9
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

---

### Step 2 — Clone the Repository (or Copy from USB/Disk)
```bash
git clone <YOUR_GITHUB_REPO_URL> ~/Ramscope
cd ~/Ramscope
git switch allocation
```
*(If your Windows partition is mounted in dual-boot Ubuntu, you can also `rsync` it just like in Part 1 Step 3.)*

---

### Step 3 — Compile & Load the Kernel Module
```bash
cd ~/Ramscope/kernel
make clean && make && make test
sudo insmod ramscope.ko

# Verify bare-metal RAM detection & 32 MB lock self-test
sudo ./test_ioctl
cat /dev/ramscope
dmesg | tail -n 10
```

---

### Step 4 — Install Backend & Frontend Packages (One-Time)
```bash
# Backend
cd ~/Ramscope/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate

# Frontend
cd ~/Ramscope
npm install
```

---

### Step 5 — Launch Backend & Frontend
**Terminal 1 (Backend):**
```bash
cd ~/Ramscope/backend
sudo ~/Ramscope/backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 (Frontend):**
```bash
cd ~/Ramscope
npm run dev
```

Open **`http://localhost:3000`**.

---

### Stopping Everything Cleanly (VM or Native Linux)
1. Press `Ctrl + C` in the Frontend terminal and Backend terminal.
2. Unload the kernel module (automatically frees all active reservations back to Linux):
   ```bash
   sudo rmmod ramscope
   ```
