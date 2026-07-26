# VanGuard Build Log

Running log of the build. **Failures included** — that's the point.

---

## 2026-07-24 — M0: Plan written, repo initialized

Read the existing van documentation in `C:\vibe\Sprinter` before writing
anything, per the brief's step zero. That immediately invalidated the brief's
telemetry plan.

**The brief assumed Victron.** It specified a Cerbo GX on the van LAN, Modbus
TCP port 502, and Victron's published register list. The van has none of that —
it's an all-Renogy stack from Off Grid Adventure Vans. Brief question #1
("confirm the GX device model and LAN address") has no answer.

**Then the Renogy stack turned out to be less reachable than it first looked.**
The initial plan was to buy a Renogy Communication Hub G1 and put a USB-RS485
adapter on it to become Modbus master over the whole bus. Three findings killed
that in sequence:

1. The 300Ah battery is **Core Series**, and Core vs Smart Lithium *is* the
   comms distinction in Renogy's lineup — Core has no port and can't be
   retrofitted. The battery tells us nothing.
2. The **Shunt 300 is Bluetooth-only** — no RS485 port at any price. It can't
   join a wired bus.
3. The **inverter is CAN**, not RS485, so it can't share the DCC50S's bus.

That leaves exactly one RS485 device in the van. A hub whose purpose is
aggregating *multiple* RS485 devices onto one BT-2 is a $50 pass-through.
**Didn't buy it.** Bought a $30 BT-2 instead — and the result is better than
the wired plan: the whole telemetry layer is now one dongle plus the Surface
Pro's built-in Bluetooth. No wiring, no RJ45 pinout archaeology, no fused 12V
tap.

The sting: **SOC is only reachable over BLE**, and the Renogy ONE Core is
probably already holding that connection. Restructured the milestones to test
that first, before any model work. If it fails, this is a different project.

**Compute platform confirmed:** Surface Pro for Business 13-inch (12th Edition),
Intel Core Ultra Series 3, 50 TOPS NPU, x86-64. Briefly worried it was the
consumer Surface Pro 12-inch, which is Snapdragon/ARM and would have made
OpenVINO's NPU plugin unusable. It isn't. OpenVINO path is valid.

**Open flag:** recommended dropping Mistral-7B-Instruct-v0.2 as primary in
favor of a modern 3–4B with native tool calling. The brief's own "model is a
config value" rule makes this cheap to change and cheap to revert.

Next: order arrives → M1 hardware handshake, in the van, on the Pro.

---

## 2026-07-25 — Surface Pro setup (SETUP_PRO.md Tasks 1–4, in progress)

Working directory note: the repo landed in `C:\vibe\vangaurd` (folder name has
a transposed "au" vs the runbook's `C:\vibe\vanguard`). Relative paths
(`../Sprinter/`) are unaffected; flagged to Frank.

**Task 1 — prerequisites:**
- git 2.55.0.windows.3 — present
- Python — **not installed anywhere** (no PATH entry, no `py` launcher, no
  install under Program Files or LocalAppData; only the Store alias stub)
- gh — not installed
- node — not installed
- winget — available
- Frank approved installs: `winget install Python.Python.3.12` → Python
  3.12.10 (python.org build, per runbook — not the Store build), and
  `GitHub.cli` → gh 2.96.0. Both clean, no license-prompt hang (used
  `--accept-package-agreements --silent` in the background).

**Task 2 — clone + docs:** clone into `C:\vibe\vangaurd` succeeded (6 commits,
oldest `M0:`). `C:\vibe\Sprinter` copied from OneDrive — 65 files, matches
expected ~64. The four Training `.mp4`s absent by design.

**Task 3 — git identity:** repo-local `user.email` set to the noreply address,
`user.name` Frank Buchholz. Verified. Auth deferred to Task 6 per runbook.

**Task 4a — RAM SKU (PLAN.md §10 Q1): 64 GB.** Top SKU — no model-size
constraint from RAM at P3.

**Task 4b — NPU:** `Intel(R) NPU` device present, Status **OK**, driver
**32.0.100.4512** dated 2025-12-08.

**Task 4c — OpenVINO device enumeration (PLAN.md §10 Q2): PASS.**
OpenVINO **2026.2.1** (`2026.2.1-21919-ede283a88e3-releases/2026/2`),
`Core().available_devices` = **`['CPU', 'GPU', 'NPU']`**. The NPU is
enumerated — Panther Lake support is there, no driver update needed. P3 is
unblocked. The three-way NPU/GPU/CPU benchmark is on.

**Task 5 — dependencies:** venv at `.venv` (Python 3.12.10);
`fastapi uvicorn aiosqlite pyyaml` installed, all imports verified. P3/M1
extras deferred per runbook.

**Nothing failed; one workaround:** freshly-installed python/gh aren't on the
PATH of already-running shells — refreshed PATH from the registry once, and the
venv's absolute paths make it moot from here on.

Next: P1 — simulator + storage layer (PLAN.md §7, §8 Track P).

---

<!-- Template for subsequent entries:

## YYYY-MM-DD — Mx: <title>

What I tried:
What broke:
What fixed it:
Screenshot:

-->
