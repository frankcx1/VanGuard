# Setting up on the Surface Pro

First-run instructions for moving this project from the laptop to the Surface
Pro for Business 13-inch (12th Edition, Intel). Follow in order.

---

## 1. Put the files in place

**The repo comes from GitHub, the docs come from OneDrive.**

```powershell
New-Item -ItemType Directory -Force C:\vibe | Out-Null
cd C:\vibe
gh auth login                       # once, on this machine
gh repo clone frankcx1/VanGuard
Copy-Item "$env:OneDrive\Sprinter" C:\vibe\Sprinter -Recurse
```

Clone the repo rather than copying it from OneDrive — you get the full history
and a working remote in one step.

For the docs, **copy them out to a local path; do not work inside the OneDrive
folder.** OneDrive syncing a live `.git` directory can corrupt it, and Files
On-Demand can turn files into placeholders mid-operation. OneDrive is the
transfer medium here, not the working directory.

Paths matter: `CLAUDE.md` and `PLAN.md` refer to the docs as `../Sprinter/`, so
keeping both under `C:\vibe\` makes those references resolve.

Verify git history survived the trip:

```powershell
git -C C:\vibe\VanGuard log --oneline
```

You should see two commits, `M0:` and `Add Track P:`.

**Note:** the four walkthrough `.mp4` files in `Sprinter\Training\` were left on
the laptop deliberately — 7 GB of video that nothing in VanGuard reads. The
transcripts came across. Sneakernet the videos later only if you want the Master
Index Training tab working here.

---

## 2. Prerequisites

```powershell
python --version    # need 3.11+
git --version
```

If Python is missing, install 3.12 from python.org (not the Store build — it
sandboxes paths in ways that complicate Bluetooth and file access).

---

## 3. Answer the two open questions

These are the last unknowns in PLAN.md §10 and they gate the model work.

**RAM SKU** — the device ships in 16 / 32 / 64 GB:

```powershell
Get-CimInstance Win32_ComputerSystem |
  Select-Object @{n='RAM_GB';e={[math]::Round($_.TotalPhysicalMemory/1GB)}}
```

**NPU present and driver version:**

```powershell
Get-PnpDevice -FriendlyName "*AI Boost*","*NPU*","*Neural*" |
  Select-Object FriendlyName,Status,DriverVersion
```

**Does OpenVINO actually see the NPU?** This is the one that matters — Panther
Lake (Core Ultra Series 3) is new, and OpenVINO support for a new NPU generation
lands with a lag.

```powershell
pip install openvino
python -c "import openvino as ov; print(ov.__version__); print(ov.Core().available_devices)"
```

You want `NPU` in that list, alongside `CPU` and `GPU`. If it's missing, install
the latest Intel NPU driver from Intel's site and re-check before concluding
anything. **This gates P3, not P1** — the simulator and dashboard don't care, so
don't let a driver problem stall the build.

Record all three answers in `BUILD_LOG.md`.

---

## 4. Environment

```powershell
cd C:\vibe\VanGuard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install fastapi uvicorn aiosqlite pyyaml
```

Add per milestone rather than all at once:

- **P1–P2** (simulator, storage, dashboard): the four above. Nothing else needed.
- **P3** (inference): `pip install openvino openvino-genai optimum-intel nncf`
- **M1–M2** (live BLE): `pip install bleak`
- Master Index app, if you want it here too: `pip install flask pypdf openpyxl
  pymupdf rapidocr-onnxruntime`

Model export needs roughly 30 GB free disk for the download plus INT4
conversion. Check before starting P3.

---

## 5. Start working

Open Claude Code in `C:\vibe\VanGuard`. It will pick up `CLAUDE.md`
automatically, which carries the project context, the corrections to the brief,
and the ground rules.

Good opening prompt:

> Read PLAN.md and CLAUDE.md, then start P1: the simulator and storage layer.

**Next milestone is P1** — `SimSource` with coulomb counting, a real LiFePO4
voltage curve, fridge duty cycling, solar peaking at 200–300W, and the seeded
scenario presets. No van hardware required. See PLAN.md §7 for the physical
model and §8 Track P for the sequence.

---

## 6. GitHub

The repo is public at **<https://github.com/frankcx1/VanGuard>**, which satisfies
the brief's requirement for a public commit trail as provenance.

Commits are authored under the account's `users.noreply.github.com` address so
they attribute to the profile without exposing a personal email. That's set
repo-locally, so anything you commit here inherits it automatically — but it
does **not** carry to other repos. Check with:

```powershell
git -C C:\vibe\VanGuard config user.email
```

If you clone fresh on the Pro (§1), the config travels with the clone only if
you set it again — `gh repo clone` does not copy local config. Re-run:

```powershell
git config user.email "199670682+frankcx1@users.noreply.github.com"
git config user.name "frankcx1"
```

To make this the default everywhere, tick **"Keep my email address private"** in
<https://github.com/settings/emails>.

### 2FA note

Access to this account was recovered once via a recovery code after an
authenticator was lost. Keep a passkey registered as the primary method and the
current recovery codes somewhere durable — a password manager, not `Downloads`.
