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

## 2026-07-25 — P1: Simulator + storage layer

What I built:
- `poller/source.py` — the `TelemetrySource` interface (the POC hinge), with
  the `simulated` property that drives the SIM badge / `"simulated": true`
  integrity guardrail.
- `sim/van_model.py` — `SimSource` + the physical model: coulomb-counting
  battery (SOC integrates net current, never assigned), piecewise LiFePO4 OCV
  curve, IR sag, DCC50S bulk→absorption→float stage machine, solar bell
  peaking at the van's *observed* 290W, per-metric noise + quantisation,
  dropout capability.
- `sim/loads.py` — fridge duty-cycle sawtooth (40% duty at 25°C ambient),
  water pump bursts, scheduled events (cooktop/lights/fan), inverter AC→DC
  losses.
- `sim/scenarios.py` — the five seeded presets from PLAN §7, deterministic.
- `sim/replay.py` — `ReplaySource`, .jsonl playback at N×, re-stamped to now.
- `poller/store.py` — SQLite WAL; `samples` (48h) / `samples_1m` (30d) /
  `tool_audit` (schema complete now, used at P4); incremental downsampling
  with a high-water mark; retention pruning; `latest()`/`history()` reads.
- `poller/derived.py` — net power, off-grid-only load derivation with
  shore-power detection *from observables* (returns None rather than lying),
  time-to-empty/full, daily solar yield.
- `poller/__main__.py` — the `vanguard-poller` process; `poller/config.py` +
  `config/devices.example.yaml` (real `devices.yaml` stays gitignored).

What broke:
- One verification check initially failed — my check's own time window was
  wrong (50h window on a clock advanced 49h reaches only 1h into the
  downsamples). Fixed the check, not the code.

Verification: `scripts/verify_p1.py` — **20/20 checks pass**, including:
determinism (same seed → byte-identical emissions), LiFePO4 flat band
[13.29, 13.35] V at rest, solar peak exactly 290W and zero at night, coulomb
consistency (ΔSOC 13.38% vs 13.38% from Ah counters), fridge duty 40%,
dusk_low drains 42.0%→34.4% in 4h with time-to-empty 21.7h, shore_power
honestly refuses load derivation, storage roundtrip + downsample + retention,
replay at 60×.

Screenshot: `sim/verify_p1_sunny24h.png` — flat voltage curve, fridge
sawtooth, 290W solar bell. Looks like a van, not like a sine wave.

Next: P2 — dashboard (dark, big tiles, 24h sparklines, SIM badge).

---

<!-- Template for subsequent entries:

## YYYY-MM-DD — Mx: <title>

What I tried:
What broke:
What fixed it:
Screenshot:

-->
