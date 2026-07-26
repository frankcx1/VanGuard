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

## 2026-07-25 — P2: Dashboard + API

What I built:
- `api/main.py` — the `vanguard-api` process (FastAPI). Routes:
  `/api/status` (freshness/staleness), `/api/telemetry/latest` (readings +
  derived bundle), `/api/telemetry/history` (windowed series, bucket-mean
  decimated to ≤300 points, auto-switching raw → 1m past 48h). **Every
  payload carries `"simulated"`** from the configured source — the guardrail
  is stamped server-side, and the SIM badge is driven only by that stamp.
- `web/` — the final dashboard, not a mockup: dark, big tiles (SOC hero with
  status chip, voltage, signed net power, solar + daily yield, DC load),
  24h SVG sparklines with hover crosshair + tooltip, an all-readings table
  (the accessibility/table view), staleness chip, and the honest DC-load
  state: "unavailable on shore power" instead of a wrong number. Zero
  dependencies, zero CDN — fully offline, per ground rules.
- Colors are the validated dark-mode steps of the bundled dataviz reference
  palette (series hues fixed per entity; status colors reserved). Node isn't
  installed so the palette validator script couldn't run locally; the exact
  set + order used is the one documented as passing all gates (worst
  adjacent CVD ΔE 8.4 dark). [verified-external against the skill's docs]
- `sim.warmup_h` config — the poller's sim can join a day in progress, so a
  fresh boot doesn't cold-start sparklines at scenario t=0. Also the knob
  that makes filmed takes start mid-story.
- `VANGUARD_CONFIG` env override so both processes point at one config file.

What broke:
- Decimation off-by-one: float stride accumulation emitted 301 points for a
  300 cap. Rewrote with integer bucket boundaries (`k*n//max`).

Verification:
- `scripts/verify_p2.py` — **13/13**: freshness, integrity stamp on every
  endpoint, decimation cap, raw→1m switchover, param validation, static
  serving, and the shore-power honesty path end-to-end over the API
  (`load_w: null` while the shunt shows +518W charging).
- `scripts/verify_p1.py` still **20/20** after the warmup change.
- Live two-process smoke test: poller + uvicorn against one WAL db,
  seeded 24h + `warmup_h: 24` continuation, headless-Edge screenshot
  eyeballed: SIM badge, staleness fresh, sparklines showing fridge steps,
  absorption spikes, solar bell. The two processes coexist on WAL with no
  lock errors at 5s cadence.

Next: P3 — inference (export INT4, NPU vs GPU vs CPU benchmark) — the NPU is
already confirmed enumerating. P4 — chat + tools against the simulator.

---

## 2026-07-25 — P3: Inference — the NPU story, measured

What I built:
- `inference/export.py` — reproducible INT4 export. Primary model chosen per
  PLAN §6: **Qwen3-4B-Instruct-2507** (modern 4B, native tool calling,
  Apache-2.0); Mistral-7B-v0.2 stays the documented fallback. Export is
  NPU-friendly (symmetric, channel-wise, `--sym --group-size -1 --ratio
  1.0`) [verified-external — OpenVINO NPU docs]; 2.1 GB artifact.
- `inference/serve.py` — `InferenceEngine`: device-order fallback
  (NPU→GPU→CPU from config), records serving device + TTFT + tokens/s per
  request.
- `inference/bench.py` — the three-way benchmark with battery-gauge power
  sampling (honest n/a on AC).

What broke:
- First export attempt: `python -m optimum.exporters.openvino` **exited 0
  having done nothing** (wrong entrypoint; runpy warning was the tell).
  Fixed to `optimum-cli export openvino` and added a hard post-check so a
  silent no-op can never read as success again. "Do not assume a command
  worked because it printed nothing" — it can even print success.

Results (full table + caveats in BENCHMARKS.md; run on battery):
- **NPU: 27.2 tok/s, TTFT 727 ms, 18.4 W, 0.023 Wh/query** (compile 85 s)
- **GPU: 36.7 tok/s, TTFT 186 ms, 23.4 W, 0.020 Wh/query**
- **CPU: 14.5 tok/s, TTFT 1517 ms, 24.5 W, 0.060 Wh/query**

The honest, non-obvious result PLAN §5 hoped for: GPU wins speed outright,
NPU wins sustained draw, **energy per query is nearly a wash** — race-to-idle
eats the NPU's wattage edge at single-query lengths. CPU loses everything
but load time. Recommendation recorded in BENCHMARKS.md: GPU for interactive
chat, NPU for the resident kiosk service.

P3 was the last milestone gated on platform unknowns. Track P now has data,
dashboard, and a measured local model. Next: P4 — chat + tool loop against
the simulator, audit log, the cooktop answer.

---

## 2026-07-25 — P4: Chat + tools. The cooktop question answers correctly.

What I built:
- `api/tools.py` — the six phase-1 tools (PLAN §7), read-only by
  construction, every invocation audited to `tool_audit` (args, result
  hash, serving device, duration). `get_history` returns stats not series
  (98 bytes for a 4h window — context discipline). `get_tanks` is the
  honest stub. `get_loads` returns null + reason on shore power.
- `api/chat.py` — OpenAI-compatible `/v1/chat/completions` (the future
  Master Index seam, PLAN §11). Native Qwen3/Hermes tool-calling loop:
  render via the model's own chat template with tool schemas → parse
  `<tool_call>` blocks → execute audited → feed back → max 3 rounds.
  Engine loads lazily off the event loop; generation in a worker thread.
- Dashboard: "Ask VanGuard" chat tile (device + tok/s + tools-used meta
  under every answer) and the Tool audit tile — the governance beat,
  on-screen: sees everything · touches nothing.

What broke (three real findings, each now a regression check):
1. **ov_genai silently re-applies the chat template** to raw prompts
   (`GenerationConfig.apply_chat_template` defaults true) — my rendered
   prompt got double-wrapped and the model never saw its tools ("I lack
   real-time data"). Fixed: explicit `apply_chat_template = False`.
2. **Greedy INT4 4B fumbles marginal comparisons.** Given "24 min to
   floor" it answered both "25 < 24 → yes" and, previous run, flipped
   verdicts mid-answer. Fix that actually holds: `estimate_runtime` now
   takes `duration_min` and returns `soc_after_pct` +
   `stays_above_20pct` — **the tool renders the verdict, the model renders
   the language.** Verification asserts the spoken verdict equals the
   tool's boolean.
3. Verbosity/repetition: fixed with verdict-before-writing prompt rules +
   `repetition_penalty 1.1`.

Verification: `scripts/verify_p4.py` — **23/23**, including the money shot
against dusk_low (SOC 38%, dusk, no PV):
> "No, you cannot run the induction cooktop for 25 minutes without
> dropping below 20% battery. … At 1700W draw, the system will reach 20%
> SOC in 24 minutes … after 25 minutes, the battery will be at 19.6%."
Correct, marginal (19.6% vs the 20% floor — genuinely close), math shown,
tools used (`get_battery_state`, `estimate_runtime`), audited, served by
GPU at ~38 tok/s, `simulated: true` stamped. Live smoke test on the full
two-process system + headless screenshot of chat/audit tiles eyeballed.

**Track P is complete. The system is filmable** (PLAN §8.1 beats 3, 4, and
the benchmark overlay). Remaining before the cold open: shoot discipline —
that beat needs M2/M3 live or replayed-real data, not SimSource.

Next: Track M — M1 hardware handshake (BT-2 + van access), or video/
SHOT_LIST.md prep, Frank's call.

---

<!-- Template for subsequent entries:

## YYYY-MM-DD — Mx: <title>

What I tried:
What broke:
What fixed it:
Screenshot:

-->
