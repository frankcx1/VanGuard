# Surface Pro setup runbook

**Audience: Claude Code, running on the Surface Pro for Business 13-inch
(12th Edition, Intel).** Frank will point you at this file on first run.

## Where you are starting

Frank creates `C:\vibe\vanguard`, runs `claude` from inside it, and points you
at this file. So on first run **your working directory is empty** — there is no
repo, no `CLAUDE.md`, nothing. Task 2 fixes that.

The repo is **public**, so cloning needs no credentials. Do not start with
`gh auth login`; it is interactive and it is not needed until you want to push.

Work through the tasks in order. Each has a command, a success criterion, and a
failure branch. **Record every result in `BUILD_LOG.md` as you go** — the RAM
figure and the OpenVINO device list in particular are open questions in
`PLAN.md` §10 and need to be closed out.

Do not skip verification steps. Do not assume a command worked because it
printed nothing.

---

## Interactive commands — read this first

Some commands below **require a human at the browser** and will hang forever if
you run them in the foreground. This exact trap cost an hour on the source
machine. For these, run in the background, read the one-time code from the
output file, and **hand the code to Frank in chat**:

- `gh auth login`
- any `winget install` that prompts for a license agreement

Everything else is safe to run normally.

---

## Task 1 — Prerequisites

```powershell
python --version
git --version
gh --version
node --version
```

**Success:** Python ≥ 3.11, git present, gh present.

**On failure:** report what's missing and let Frank install it. If he asks you
to, use `winget install Python.Python.3.12`, `winget install Git.Git`,
`winget install GitHub.cli`. Prefer the python.org build over the Microsoft
Store build — the Store build sandboxes filesystem and device paths in ways
that complicate Bluetooth access at M1.

---

## Task 2 — Land the code and docs

Clone **into the current directory** (`C:\vibe\vanguard`), not into a
subfolder. No authentication required — the repo is public.

```powershell
cd C:\vibe\vanguard
git clone https://github.com/frankcx1/VanGuard.git .
```

If that fails because the directory is not empty (Claude Code may have created
a `.claude` folder), use the equivalent that tolerates existing files:

```powershell
git init
git remote add origin https://github.com/frankcx1/VanGuard.git
git fetch origin
git checkout -t origin/main
```

Then bring the van documentation across:

```powershell
Copy-Item "$env:OneDrive\Sprinter" C:\vibe\Sprinter -Recurse
```

**Success:**

```powershell
git log --oneline                                  # 5+ commits, oldest is "M0:"
Get-ChildItem                                      # CLAUDE.md, PLAN.md, BUILD_LOG.md, SETUP_PRO.md
(Get-ChildItem C:\vibe\Sprinter -Recurse -File | Measure-Object).Count   # ~64 files
```

**Once the clone lands, read `CLAUDE.md` immediately** — it carries the ground
rules and the three corrections to the original brief. Then continue this
runbook from the copy now in your working directory.

Path layout this assumes:

```
C:\vibe\vanguard\      <- the repo (you are here)
C:\vibe\Sprinter\      <- van docs; CLAUDE.md refers to these as ../Sprinter/
```

**Notes:**
- The four `.mp4` walkthrough videos in `Sprinter\Training\` were deliberately
  left on the source laptop — 7 GB that nothing in VanGuard reads. Transcripts
  came across. Their absence is correct, not a sync failure.
- If `$env:OneDrive\Sprinter` is missing or files are 0 bytes, OneDrive hasn't
  finished syncing or is using Files On-Demand placeholders. Tell Frank; don't
  work around it.
- **Work from `C:\vibe\`, never from inside the OneDrive folder.** OneDrive
  syncing a live `.git` directory can corrupt it.

---

## Task 3 — Git identity, then auth

**Set the identity first — this is not optional and is easy to forget.** A
clone does not carry repo-local config, so without it, commits made here are
authored under whatever global identity exists and show as unlinked on GitHub:

```powershell
cd C:\vibe\vanguard
git config user.email "199670682+frankcx1@users.noreply.github.com"
git config user.name "Frank Buchholz"
```

**Success:** `git config user.email` returns the noreply address above.

The noreply address is deliberate — the repo is public and commits must not
carry a personal email. Do not "helpfully" change it to a real address.

### Auth — only needed to push

**INTERACTIVE. Defer this until you actually have something to push** (Task 6).
Nothing in Tasks 1–5 needs it.

When the time comes, run it in the **background**, read the one-time code from
the output file, and paste it into chat for Frank:

```powershell
gh auth login --hostname github.com --git-protocol https --web
```

The code expires in ~15 minutes; if it lapses, issue a new one — they are free.
Do not run this in the foreground; it will hang until it times out.

**Success:** `gh auth status` shows logged in as `frankcx1`.

The noreply address is deliberate — the repo is public and commits must not
carry a personal email. Do not "helpfully" change it to a real address.

---

## Task 4 — Close the two open unknowns

These are `PLAN.md` §10 questions 1 and 2. **Record the answers in
`BUILD_LOG.md` and report them to Frank.**

### 4a. RAM SKU

```powershell
Get-CimInstance Win32_ComputerSystem |
  Select-Object @{n='RAM_GB';e={[math]::Round($_.TotalPhysicalMemory/1GB)}}
```

Expect 16, 32, or 64. This determines the model size we can target at P3.

### 4b. NPU present, and driver version

```powershell
Get-PnpDevice -FriendlyName "*AI Boost*","*NPU*","*Neural*" |
  Select-Object FriendlyName,Status,DriverVersion
```

Expect an Intel AI Boost device with `Status: OK`.

### 4c. Does OpenVINO actually see the NPU?

**This is the one that matters.**

```powershell
cd C:\vibe\vanguard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install openvino
python -c "import openvino as ov; print(ov.__version__); print(ov.Core().available_devices)"
```

**Success:** `NPU` appears in the device list, alongside `CPU` and `GPU`.

**On failure (NPU missing):** this device is Core Ultra Series 3 (Panther
Lake), which is new enough that OpenVINO support may lag the hardware. Report
the OpenVINO version and the device list to Frank and suggest updating the
Intel NPU driver from Intel's site.

**Do not let this block you.** It gates P3 only. P1 and P2 are entirely
independent of it — carry on.

---

## Task 5 — Dependencies

```powershell
cd C:\vibe\vanguard
.\.venv\Scripts\Activate.ps1
pip install fastapi uvicorn aiosqlite pyyaml
```

That is everything P1 and P2 need. Install the rest only when the milestone
arrives, so a broken optional dependency never blocks the critical path:

| Milestone | Add |
|---|---|
| P3 inference | `openvino openvino-genai optimum-intel nncf` |
| M1–M2 live BLE | `bleak` |
| Master Index app (optional) | `flask pypdf openpyxl pymupdf rapidocr-onnxruntime` |

P3 model export needs roughly **30 GB free disk** for download plus INT4
conversion. Check before starting it.

---

## Task 6 — Report and begin

Post a summary to Frank containing:

1. RAM SKU
2. NPU device status and driver version
3. OpenVINO version and `available_devices` — **explicitly whether `NPU` is present**
4. Anything that failed or needed a workaround

Append the same to `BUILD_LOG.md`, then update `PLAN.md` §10 to strike
questions 1 and 2 and record the answers. Commit:

```powershell
git add -A
git commit -m "Record Surface Pro platform specs; close PLAN.md open questions 1-2"
```

Pushing needs auth — do the deferred `gh auth login` from Task 3 now, then:

```powershell
git push
```

If Frank is away and cannot complete the browser step, **commit anyway and
carry on**. The work is safe locally and pushes later.

Then **begin P1** — the simulator and storage layer. See `PLAN.md` §7 for the
physical model and §8 Track P for the sequence. In short:

- `SimSource` behind the `TelemetrySource` interface
- Coulomb counting — SOC integrates net current, never set directly
- A real flat LiFePO4 voltage curve, not a linear ramp
- Fridge duty cycling, solar bell curve peaking at 200–300W
- Seeded, deterministic scenario presets

Read `CLAUDE.md` first if you have not already — it carries the ground rules and
the three corrections to the original brief that must not be re-derived.

---

## If something is genuinely blocked

Do not invent a workaround that changes the architecture. The plan is the
product of verified hardware research; a blocker usually means the plan needs
updating, which is Frank's call. Report it, propose options, and wait.

Exception: P1 and P2 depend on nothing external. If you are blocked on hardware,
drivers, auth, or network, that is a signal to **go build the simulator**, not a
signal to stop.
