# Setting up on the Surface Pro

First-run instructions for moving this project from the laptop to the Surface
Pro for Business 13-inch (12th Edition, Intel). Follow in order.

---

## 1. Put the files in place

Both folders came over via OneDrive at `C:\Users\<you>\OneDrive\`. **Copy them
out to local paths — do not work inside the OneDrive folder.** OneDrive syncing
a live `.git` directory can corrupt it, and Files On-Demand can turn files into
placeholders mid-operation.

```powershell
New-Item -ItemType Directory -Force C:\vibe | Out-Null
Copy-Item "$env:OneDrive\VanGuard" C:\vibe\VanGuard -Recurse
Copy-Item "$env:OneDrive\Sprinter" C:\vibe\Sprinter -Recurse
```

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

## 6. GitHub — deferred, not forgotten

The repo isn't pushed anywhere yet; 2FA on the account got in the way and it
wasn't worth blocking the migration over. Git works entirely offline, so build
freely and push the whole history whenever you sort it out.

When you do:

1. Check which 2FA methods the account actually has at
   <https://github.com/settings/security>
2. Decide which account owns this — the one your browser is signed into, or the
   one matching how the commits are currently authored (`the personal account`).
   GitHub attributes commits by matching the author email to a **verified email
   on the account**, so a mismatch means the history won't link to your profile.
3. Before making it public, rewrite the two existing commits to that account's
   `<id>+<username>@users.noreply.github.com` address — much easier at two
   commits than at fifty.
4. `gh auth login` → `gh repo create VanGuard --public --source=. --push`

The brief wants a public commit trail as provenance, so the commit *dates*
matter. They're already recorded locally and will survive the eventual push.
