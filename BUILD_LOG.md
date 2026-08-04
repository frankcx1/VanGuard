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

## 2026-07-26 — P5: Demo mode — charging source, alerts, climate, voice, trip

Frank's scenario list from last night, built as demo mode (each feature's
path to real hardware recorded in PLAN §12.5):

- **Charging From tile** — ☀️ Solar / 🚐 Alternator measured at the DCC50S,
  🔌 Shore always labeled *(inferred)* because the charger is CAN-only.
  Sim grew an alternator (active while driving, capped at the DCC50S's 50A).
- **Alerts** — thresholds in config (SOC 30/15%, volts, time-to-empty,
  staleness), banner on the dashboard, `/api/alerts`.
- **Climate** — cabin temp + HVAC sim where the A/C's ~900W draw hits the
  battery model (turn on Cool, watch net power dive — the demo moment).
  Controls are **human-only and sim-gated**: commands go through a
  `commands` table the poller applies; audited as device=HUMAN; a live
  source refuses at both the API (403) and the poller (phase-1 read-only
  default). The AI's get_climate is read-only.
- **Voice — fully real, zero cloud.** Browser records raw 16kHz PCM (no
  cloud speech APIs), `/api/transcribe` runs whisper-base.en on OpenVINO
  (GPU). Verified end-to-end with Windows SAPI-synthesized speech:
  transcript came back **verbatim**.
- **Trip keeper** — simulated GPS along a Pacific Rim Hwy route into
  Tofino, BC (Frank's pick; the Pisgah dataset survives as
  `pois_pisgah.json`), trip odometer, and get_nearby_pois over an
  **offline curated POI dataset** — no cloud places API, honestly labeled.
  Three new read-only tools (9 total): get_climate, get_trip_status,
  get_nearby_pois.

What broke / got tightened:
- track_miles teleport filter (1mi) ate real driving segments when poll
  cadence stretched under CPU load — loosened to >5mi with adaptive stride.
- The model freelanced a runtime claim ("9 hours at 1500W", real answer
  1.3h) in an open-ended trip question — system prompt now forbids stating
  any runtime estimate_runtime didn't produce. Cooktop e2e re-verified.
- Alert test seeded 6h of dusk_low → SOC 31%, one point above the 30%
  threshold. Test bug, not code; seeded 8h.

Verification: verify_p5 **23/23** (including the SAPI→Whisper round trip
and the live-source 403/refusal gates), and full regression: P1 20/20,
P2 13/13, P4 23/23. Road-trip dashboard screenshot eyeballed: charging
tile, climate controls, Tofino POIs, mic button, HUMAN rows in the audit.

---

## 2026-07-26 (later) — Driveway scenario, °F, one-screen layout, and a
## fabrication catch

- **`driveway` scenario** — parked at approximate central-Kirkland coords
  (deliberately not a real address; public repo) with an Eastside
  recreation POI set. Regional POI datasets (`pois_*.json`) are merged and
  **auto-selected by position** — no config, distance does the work.
- **Fahrenheit** across the dashboard (battery temp, cabin, setpoint input
  50–90°F converting to °C at the API). Tools now return pre-converted
  `*_f` fields so the model never does unit math.
- **One-screen layout** at Frank's request/screenshot: fixed 4×3 grid,
  `body` locked to 100vh, readings/audit/chat scroll inside their tiles,
  Ask input moved to the top of the chat tile. Falls back to normal
  scrolling under 1100px.
- **Fabrication caught and fixed structurally.** Asked "how warm is it
  inside?", the model answered "68°F" with **zero tool calls** and a fake
  "values from get_climate" citation (real: 72.9°F). A strict-retry prompt
  didn't cure it. Structural fix: every chat request auto-fetches a
  **climate/trip snapshot through the audited tools** and injects it into
  context — those values can't be invented anymore. Power/battery data is
  deliberately NOT in the snapshot: when it was, the model stopped calling
  estimate_runtime and freehanded the cooktop math wrong (said "no" at 91%
  SOC; truth is yes with a 96-minute margin). Starved of power numbers, it
  must use the tools — verified both paths.
- Full regression after all of it: P4 23/23, P5 20/20 fast checks.

---

## 2026-07-26 (evening) — P6: "intelligence, not merely telemetry"

Frank brought an external review (LLM-written, hadn't read the repo).
Triaged rather than swallowed: its centerpiece — deterministic calculations
with the model only explaining — was already built and tested; its "make
the AI simulated / don't claim NPU" premises were wrong for this project
(our inference is real and measured, and we only ever display the device
the runtime reports). The genuinely good ideas got built:

- **Status rail**: OFFLINE · SIM DATA · LOCAL AI: <device from /api/runtime>
  · DATA STAYS ON DEVICE (tooltip: design guarantee, not a network audit) ·
  MIC READY · operating mode · 🎬 Story · time.
- **Power-flow panel** consolidating solar/alternator/shore (still
  click-to-switch) → battery → house DC / AC-via-inverter / cooktop toggle,
  with a live reconciliation line ("174W in − 30W out ≈ +144W battery").
- **VanGuard Insight** — `api/insight.py`, deterministic rules → NL:
  power story, 100%-but-charging explainer, hot/cold cabin with proposed
  (confirm-gated, sim-labeled) HVAC action, driving-without-alternator,
  sensor-conflict data-quality notes. Explain / What changed? / Read aloud
  (local speechSynthesis) / Dismiss.
- **Power Outlook** — `api/outlook.py`: runtime-to-reserve, SOC at sunrise
  (clear-sky bell scaled to today's observed peak), discretionary Wh,
  confidence that degrades with staleness, assumptions listed. Real 3840Wh
  capacity, not the review's generic 5kWh.
- **Operating modes** as policy data (camp/sleep/drive/storage/emergency →
  reserve + alert thresholds), persisted, audited.
- **Alert stack** with severities incl. advisory + data-quality.
- **Diagnostics drawer** — readings + audit + honest AI-runtime panel move
  behind "30 readings · all fresh · N local tool calls · 0 external calls".
- **Chat upgrades**: suggested-question chips, provenance label on every
  answer ("calculation + local model (GPU)" / "no model active"), evidence
  expander showing the actual tool calls.
- **Deterministic fallback** (`api/deterministic.py`): no model → same
  audited tools, template prose, correct cooktop verdict, labeled.
- **Demo Story mode**: 8 presenter-paced steps driving the live dashboard
  (includes simulating the cooktop via the new audited appliance command);
  ends "Monitor. Understand. Act. Even when the cloud is out of reach."
- Accessibility: focus-visible, aria-live on insight/alerts/story, reduced
  motion, semantic controls. README rewritten with the safety disclaimer.

**Story-mode shakedown (late evening).** Running the story steps against the
live system caught two model failures and forced the endgame architecture:

1. The scripted question "why is the battery charging when it says 100%?"
   met a battery at 89% — and the model *played along with the false
   premise*, inventing maintenance-mode lore. Fixed the script question and
   added a correct-the-premise prompt rule; the structural fix below is what
   actually made it stick (it now answers "91%, not 100%").
2. The 4B inverted the cooktop verdict AGAIN even with the calculator's
   result injected into context (three designs tried: prompt rules,
   snapshot injection, synthetic tool exchange). Conclusion recorded:
   **this model cannot be trusted to restate a verdict.** Final
   architecture: the server detects runtime/energy questions, runs
   estimate_runtime, and composes the verdict sentence deterministically —
   provenance "deterministic calculation · verdict computed, never
   generated". The model handles every other question over a full audited
   snapshot (all five domains — fabrication is now structurally impossible
   for current-state numbers), with sign conventions pre-worded by the
   tools (state: "charging", charging_from: [...]) after it misread +55A
   as discharge.

Also: story deep-links (#story, #story=N — visual jumps, actions fire only
on real Next clicks). verify_p4 restructured: calculator path asserted
verdict-always-equals-tool; separate model-path e2e for state questions.
P4 25/25.

Verification: new `verify_p6.py` — **32/32** (outlook math incl. the
review's 46%-overnight scenario landing at 6% by sunrise; insight rules;
alert severities; provenance; no-model fallback answering the cooktop
question correctly; runtime honesty — nothing loaded → no device claimed;
mode policies; appliance command). Full fast regression green (P1/P2/P4/P5).

---

## 2026-07-27 — P7: Watchdog patrols + presentation polish

- **Watchdog** (`api/watchdog.py`): the API process patrols on a schedule
  (config `watchdog.interval_min`, demo 5 min). Each patrol pulls state
  through the audited read-only tools (device=WATCHDOG in the audit),
  renders the verdict deterministically (insight + outlook + alerts →
  nominal/attention/warning/critical), then the local model writes the
  1-2 sentence report FROM those findings — same language-layer-only
  discipline as chat; no model → deterministic text stands. Logged to a
  `patrols` table; surfaced in the Insight panel with status chip, last
  check time, cadence, count today, source, and a "Check now" button.
  First NPU patrol: 2.7s, report quoted the findings' numbers verbatim.
- Rail badge now names the model: "LOCAL AI: NPU · Qwen3-4B" (label
  derived from the loaded model dir, shown only for the runtime-confirmed
  device).
- Earlier same day: presentation mode (-Presentation) for filming — UI
  sim labels hidden, data-layer `simulated` stamps preserved; -NPU switch
  serves for real on the NPU; outlook source-persistence fix (alternator/
  shore project forward — no false 0%-by-sunrise while the engine runs);
  battery-box live runtime readout; A/C toggle; network panel with
  5G/Wi-Fi/Starlink Mini (real gRPC-shaped telemetry + real 12V draw).

Verification: p6 grew to 40 checks (patrol verdict/report/audit, model
label, persistence forecasts); full fast regression green.

---

## 2026-07-27 — P8: VanGuard Guardian — from monitoring to autonomy

Built from the second external review (this one had actually read the
system). The screen now visibly does the missing half: recognize risk,
pick a policy-approved response, act, verify, explain.

- `api/guardian.py`: **deterministic policy engine** — the LLM is never in
  this loop. Autonomy ladder (observe/advise/ask/protect/emergency,
  user-selected, default protect), action registry with permission classes
  (auto / confirm / interlock; vehicle+BMS are the permanent never-class),
  cooldowns, hysteresis (2 consecutive detections; interlocks act on 1),
  episodes detected→verified→decided→acted→confirmed logged to
  `guardian_events`. Actions go through the same sim-gated audited command
  queue (device=GUARDIAN); live sources refuse. **Low sensor confidence
  withholds autonomy** — knowing when not to act is a feature.
- Detectors: overnight reserve breach (sheds Starlink + idle inverter,
  proposes HVAC-off), voltage-sag interlock (<12V under >800W AC → stop
  cooktop; demo interlock, not certified protection), alternator-gap
  advisory (restraint: flags, never "repairs"), sensor-conflict withhold.
- `get_guardian_log` tool + snapshot inclusion so "why did you turn those
  off?" is answered from the record, not confabulated. First live run of
  the full loop, unprompted: detected 1%-by-sunrise vs 20% policy → shed
  dish + inverter (~42W) → **confirmed: drain 73W→30W, sunrise forecast
  1%→17%** — and the NPU model explained it correctly on request.
- UI: Guardian strip in the Ask panel (armed state, autonomy selector,
  decision timeline, approve/dismiss for ask-level, policy line),
  presentation badge is now **SIMULATED VAN · REAL LOCAL AI** (reviewer's
  suggestion — disclosure as a flex), LIVE timestamp on power flow,
  "verdict: deterministic rules · explanation: Qwen3-4B (NPU)" label,
  standalone inverter tile folded into Power Flow, `overnight_guardian`
  scenario, intentionally-off Starlink no longer reads as "stale".
- Chassis research logged in PLAN §12.5: OBD-II dongle is the local path
  for front-of-van telemetry; Mercedes Fleet API exists but is cloud.

Verification: new `verify_p8.py` **20/20** (detectors, hysteresis, full
protect episode with real queued commands + GUARDIAN audit rows +
before/after confirmation, no episode spam, ask-level approval flow,
observe-level restraint). Full regression green.

---

## 2026-07-27 — P9: Whole-van fusion — chassis domain + cross-system findings

Frank dropped SUGGEST.md (a formal vNext proposal; Track G was essentially
P8 already). Implemented the high-value selections; deliberately skipped
adapter manifests, integrator profiles, and trend analysis (need real
trips/customers).

- **Chassis domain (simulated, read-only by definition)**: engine_running,
  ignition, speed, chassis bus voltage (14.1V running / 12.65V rest), fuel
  %, DEF %, coolant, odometer, DTC count — fuel burns and coolant warms
  only while the engine runs. Real adapter path documented in
  `CHASSIS_RESEARCH.md`: OBD-II BLE dongle + python-OBD, read-only,
  standard PIDs first; fuel/DEF flagged [UNVERIFIED] until tested on this
  van; Mercedes Fleet API noted and rejected (cloud). Compact CHASSIS
  block in the Trip tile; `get_chassis` tool + snapshot (12 tools now).
- **Fusion findings** (the point of the whole exercise):
  - *Charging-path anomaly*: chassis says engine running + 14.1V bus, house
    says 0W alternator input, battery not full → advisory naming the
    evidence, blaming nothing, acting on nothing. Suppressed when SOC>95
    (charge legitimately tapered). `charging_path_fault` scenario: DTC=0 —
    Mercedes sees nothing wrong; only the fused view does.
  - *Arrival cleanup*: one-shot moving→parked+ignition-off transition with
    travel loads still burning → mode→Camp + shed Starlink/idle inverter,
    reserve recalculated. Live-verified: parks 36 min into the route.
- **Departure readiness**: deterministic checklist (battery, shore,
  inverter, fridge/freezer, climate, fuel, DEF, DTCs, sensor freshness) —
  routed server-side like runtime questions, never through the model;
  **unknowns render as NOT MONITORED, never PASS** (chassis offline →
  fuel/DEF/DTC not-monitored, verified). "ready to depart?" chat chip.
- `GUARDIAN_POLICY.md` documents the ladder, action classes, and loop.
- Field lesson while testing live: the Tofino route finishes in 36 min,
  not the estimated ~65 — the arrival demo seeded 1.0h had the van parked
  before Guardian ever saw motion, so the transition never fired. Seed
  corrected to 0.5h; an end-to-end drive→park guardian test now pins it.

Verification: `verify_p9.py` **23/23**; full regression green (p1/p2/p4/
p5/p6/p8). Reserve-protection also observed completing its full loop live
(122W→81W, sunrise 5%→20%, then *resolved* when the risk cleared).

**P9b (same evening) — OBD engine stream.** Everything else the BLE
dongle's standard PIDs would give, simulated coherently: speed → RPM,
load (with terrain wander) → boost and fuel rate, fuel rate → tank level,
tank → range at 16 mpg. Emitted on the chassis source (rpm,
engine_load_pct, boost_psi, fuel_rate_gph, range_mi), third CHASSIS line
while driving ("1930 rpm · 58% load · 10.8 psi boost · 17.1 mpg · range
258 mi"), get_chassis tool extended, research table gains the PID rows
(fuel rate 0x5E flagged [UNVERIFIED] on diesels). One paid lesson: class
constants pasted mid-__init__ broke the module — and a parked GPS now
correctly reports near-zero speed jitter (the old 0.2-sigma noise
occasionally tripped the parked check when RNG order shifted).
verify_p9 → **27/27**, full regression green.

---

## 2026-07-27 — P10: filming polish — the visible Guardian event

Final pre-filming review verdict: breadth is done; make three things
unmistakable on compressed LinkedIn video — voice is local, Guardian can
prevent a developing problem, every decision is explainable and audited.
No new subsystems; presentation-layer truth-telling on machinery that
already existed.

- **Guardian event card**: during an episode the compact strip yields to
  a camera-sized card — risk numbers (projected sunrise SOC vs policy
  reserve, voltage, alternator input…), the action taken with watts
  shed, `✓ RECOVERY VERIFIED · battery −122W → −81W · sunrise 5% → 20%`,
  and a one-line **decision receipt** (fresh readings + confidence,
  Mode · Level, "decision deterministic · explanation on NPU", 0 external
  calls). Assembled server-side (`/api/guardian` → `card`) strictly from
  logged `guardian_events` — the card *cannot* disagree with the audit
  trail because it is the audit trail. Timeline relabeled for camera:
  DETECTED → VERIFIED → POLICY MATCHED → ACTIONED → RECOVERY CONFIRMED,
  now shown through the confirmed stage. Structured data (action labels,
  savings_w) added to decided/acted/proposed events to feed it.
- **"Why did you do that?"** appears as an amber first-class chip on its
  own for 15 min after any Guardian action — the question a viewer has
  at exactly that moment. Chips curated down to four static + this one
  (the clipped sixth chip is gone).
- **Visible local voice pipeline**: 🎤 shows `● LISTENING LOCALLY`; the
  pending answer shows `VOICE → WINDOWS ON-DEVICE DICTATION → QWEN3-4B
  ON NPU → VERIFIED TOOLS` (labels the *actual* path — Whisper fallback
  says LOCAL WHISPER, device read from the runtime, never assumed); the
  reply carries a green `✓ processed entirely on this device · N local
  tool calls · 0 external calls` receipt. Flag is consumed per-send and
  cleared on aborted recordings so a typed question can never wear the
  voice banner.
- **NO UPLINK · LOCAL AI ACTIVE** replaces `⛔ OFFLINE` in the rail when
  the network is off but the model is exported/loaded — local AI is not
  a fallback for bad connectivity. Footer (presentation):
  "Telemetry · voice · reasoning · decisions — processed on this device".
- Guardian policy text moved behind a `policy details ▾` expander;
  normal state is quieter, event state is bigger.
- FILMING.md gains the recommended **70-second cut** and the optional
  offline beat.

Verification: verify_p8 extended with five card checks → **25/25**;
verify_p9 **35/35**; full stack relaunched clean.

## YYYY-MM-DD — Mx: <title>

What I tried:
What broke:
What fixed it:
Screenshot:

-->

## 2026-07-28 — favicon

Added `web/favicon.svg` — camper van in the dashboard's fixed entity colors
(solar orange body, SOC-blue roof panel) — and linked it from `index.html`.
Inline SVG, no binary asset, served by the existing `/static` mount; verified
at 16/32/96 px via headless-Edge render. Browser tabs and the Edge `--app`
window now show the van instead of the default globe.

---

## 2026-08-01 — P11: The take — app rebuilt to the production shot list

Frank delivered `VanGuard_Scripts_ShotList.docx` (Cut A ~2:57 YouTube, Cut B
~72s LinkedIn). It rewrites the demo drive's story: not a mysterious mid-drive
charging fault, but **"I forgot the switch"** — the alternator→house charge
switch never flipped, rear A/C running for the dogs, battery crossing 20% on
a fixed clock from the Drive press, and a two-stage priority shed. The old
+30s scripted `_drive_fault` is **replaced** (Frank's call), and verify_p9's
fault checks updated to assert a no-take drive stays healthy.

Built:
- **Take profiles** (`sim/scenarios.py: Take/TAKES`, `-Take` on demo.ps1):
  `forgot_switch` (crossing +20s) and `forgot_switch_fast` (+12s). Plumbed
  through config → SimSource → seed_db.
- **Van model**: `charge_switch_on` (the physical switch; False = the story —
  chassis healthy, house input 0W), rear A/C on as a Drive-press side effect
  (~900W, the honest drain), SOC **pinned at its mark while parked** so the
  event clock starts at the press regardless of setup time
  (`Battery.pin_for_take` — the one sanctioned exception to "SOC is never
  assigned", disclosed here), dish pre-armed online+warm (~24W steady, so
  Stage 1 sheds the shot-list number, not 58W boot draw), **Park = full take
  reset** (SOC re-pinned, A/C off, dish warm again, switch still forgotten).
  Shunt SOC emission stepped at 0.1% (was 1%) so the crossing is visible.
- **Guardian battery-saver** (`detect_battery_saver`): SOC ≤ 20% + net drain
  → staged shed in the owner's priority order, ONE action per stage with
  12s re-verify between: Stage 1 Starlink (~+28s), Stage 2 rear A/C (~+40s).
  `hvac_off` stays confirm-class globally; the battery-saver risk carries an
  **auto_override** — the declared exception (comfort loses to the battery
  below 20%), noted in the policy panel. Card gains STAGE n, PROTECTED:
  fridge · freezer (structurally unsheddable — not in the registry), and an
  `escalating` flag that holds the why-chip until the final stage. Risk
  runs exclusively while active (one calm card, no overlapping episodes);
  detector set is config-narrowable (`guardian.detectors`) so
  alternator-gap/reserve don't talk over the story during a take.
- **Screen demeanor** (`/api/guardian → screen`): `alarm` (red border pulse,
  1.1s) under 20% before any action → `easing` (slow amber breath) once
  Stage 1 acts → calm/none after recovery confirms. Pure overlay, honors
  prefers-reduced-motion (FILMING.md notes the Windows setting).
- **Alert discipline for the take** (config, not hardcode): soc_warn at
  20.0 (the crossing IS the single warning), tte_warn tightened,
  alt-missing downgraded to advisory, reserve-forecast off — battery-saver
  owns the under-20 story on screen. SOC alerts show one decimal below 25%;
  battery hero likewise below 30%.
- **Cadence**: take config runs poll + guardian at 1s (loop clamp was 10s);
  UI polls guardian at 2s and telemetry at 2s so the beats don't lag.
- Story mode steps 10–12 rewritten to the new narrative; FILMING.md
  rewritten around the take; video/SHOT_LIST.md marked superseded by the
  docx.

What broke / got tuned:
- First timing run: crossing +22s (start_soc 20.17 too high) → tuned to
  20.158 / 20.114 (fast) against the harness; targets now land +19–20s /
  +12s, Stage 1 +26–27s, Stage 2 +38–39s, chip right after Stage 2.
- reserve-forecast warning fired pre-drive at 20.2% (take lives at the
  reserve line by design) → the `reserve_warning` rule toggle above.
- Harness initially read the *previous* take's acted events after a Park
  (guardian_events window) → filter by press timestamp.
- **Live-stack race the fake-clock harness couldn't see:** on the real
  two-process stack, Park's guardian reset lands before the poller applies
  the drive-off command, so the arrival detector saw the moving→parked
  transition *after* the reset and re-shed the dish the reset had just
  restored — leaving the next take's Stage 1 with a booting dish. Fix:
  a take's detector list drops `arrival` (Park is the reset button between
  takes, not a story beat). Found only because the launch was tested for
  real after the harness passed.

Verification: new **`scripts/verify_take.py`** — 44/44: the full event
clock for both takes (fake 1s clock, real SimSource/Store/Guardian, no
sleeps), single-warning discipline, screen alarm→easing→calm sequence,
PROTECTED card, 0-external receipt, Park reset (SOC/A-C/dish/pulse), and
the filming flow itself — a second take pressed at an odd phase after a
Park reproduces crossing/Stage 1/Stage 2 **within 1s**. Full regression
green: p1 20/20, p2 13/13, p4, p5, p6, p8 25/25, p9 35/35.

---

## 2026-08-03 — P12: Tabbed view — the camera-friendly layout

Frank's call after reviewing the take: the one-screen grid is "an eyeful"
on video. Rebuilt the presentation as four tabs with the proven grid one
tap away (nothing was removed — same tiles, same IDs, same JS data flow).

- **Tabs**: 🚐 Van (Battery hero spanning two rows with a full-height
  sparkline, Power Flow wide, Climate/Network, Chassis + Drive, Outlook —
  the entire filmed take plays here) · ✨ AI (Insight, Ask + Guardian
  home) · 📋 Log (Alerts, Diagnostics) · 🗺️ Trip (route + offline POIs).
  Keys 1–4 switch tabs, G toggles the view; `#tab=<name>` and `#grid`
  deep-link; the toggle persists in localStorage. Tile-to-tab mapping is
  a `data-tab` attribute; per-tab layouts are one 12-column CSS grid.
- **The structural piece — Guardian never hides behind a tab**: the live
  block (`#g-live`: timeline + STAGE card + approve row) **reparents into
  a fixed overlay** whenever an episode is live and the AI tab isn't
  showing; back home when it is. The why-chip mirrors onto the overlay —
  one tap jumps to the AI tab and asks. This preserves the shot-list
  choreography: everything through Stage 2 on the Van tab, one deliberate
  cut to AI for the voice beat.
- **Split the old Trip tile**: Chassis (+ Drive/Park button) now a Van-tab
  tile; Trip keeps odometer/position/POIs on its own tab. IDs unchanged —
  refreshTrip needed zero changes.
- Story mode steps carry a `tab:` field and auto-switch before
  spotlighting; the Guardian step now stays on Van and lets the overlay
  carry the moment.
- Grid mode verified untouched (screenshot) — it simply gained the split
  chassis tile.

Verified live on the real stack (headless-Edge frames at 1920×1080): all
four tabs + grid render; a full take on the Van tab shows the red-pulse
border + single "battery low: 20.0%" banner at the crossing, the overlay
sliding up with STAGE 1 (Shed Starlink dish · 25W) then STAGE 2 (Shed
rear A/C · 900W) + PROTECTED line + receipt, the why-chip on the overlay,
and the rail flipping to NO UPLINK · LOCAL AI ACTIVE after the dish shed.
One non-regression note: the launcher's model pre-warm hit a transient
500 (startup race with the watchdog's first patrol loading the engine);
the next request served fine and the rail reported GPU correctly — the
pre-warm's warn-and-continue handling is doing its job.

**Van-tab rev 2 (same day, Frank's screenshot review):** Battery had too
much real estate. New arrangement — left column Battery over Climate in
equal halves; right column Power Flow at 4/6 height with
presentation-scale type (17px nodes, 19px watt values, 40px battery-box
net number, 34px arrows), and Outlook + Chassis sharing one full-width
band beneath it (Chassis block centered, 14px). Implemented as a 6-row
grid template so left and right columns split independently.

**Van-tab rev 3 (same day, second screenshot pass):** Power Flow promoted
to the hero panel outright — 9/12 of the height (grid moved to a 12-row
template), type up another step (19px nodes / 22px values / 48px net /
40px arrows); Outlook + Chassis compressed to a 3/12 band (they had more
room than content). Climate and Network now split their tile evenly: the
network block claims the lower half (`flex: 1`, content spread
space-evenly) instead of bottom-hugging under dead space, stats text up
to 14px.

---

## 2026-08-03 — P12b: E-bike chargers + the three-stage shed

Two findings and a feature, same session. First the verified answer to
Frank's question: **the van's A/C does NOT need the inverter** — it's a
Cruise N Comfort **HD12L VDC**, native 12V (OGA invoice line 20), on its
own heavy-duty DC breaker. The sim already modelled exactly that.

The feature (Frank's spec): the take should still open with the inverter
ON and real 110V work happening — and the Guardian should shed
**everything** except the cold chain. Invented demo device: **e-bike
smart chargers** in the garage — Bosch-style 2A ≈ 90W at the outlet
[UNVERIFIED — plausible class figures; explicitly an invented device],
reporting pack %, watts, and charging state the way the bike's BLE
service would (real adapter = phase-2 BLE client, same shape as the
BT-2 path). New `ebike` telemetry source, 🚲 E-bikes node in Power Flow
(on/off via the audited appliance command; auto-switches the inverter on
like the cooktop), pack % pinned at 58 while parked so every take opens
identical, tapers to a 6W float at full.

**The battery-saver ladder is now three stages** — Starlink (~24W) →
rear A/C (~900W) → the 110V circuit (inverter off, which drops the
e-bike chargers with it, ~120W): below 20% the ladder runs to its END,
one verified stage every ~12s, stop condition "nothing nonessential
left" rather than a noise-sensitive watt threshold (deterministic by
design — the old net<-50W escalation gate would have made Stage 3 timing
depend on fridge compressor phase). Only fridge + freezer survive, and
the closing frame shows battery net positive with everything else dark.
New action `shed_110v` (confirm-class, battery-saver auto-override, like
hvac_off). Shot-list clock: crossing +20s, stages +28s/+40s/+52s, chip
~+53s, calm ~+60s; fast variant +12/+19/+31/+43.

Layout fixes from live testing on Frank's window: the LIVE reconciliation
line centers in the Power Flow head (it was colliding with the House DC
node), hero-scale sizes trimmed one step so the 7-node loads column +
sparkline fit shorter windows (verified at 1600×860 and 1920×1080).

Verification: verify_take extended to **53/53** — three-stage clock both
takes, chip after Stage 3, closing frame (inverter off, e-bikes off,
fridge/freezer on, net positive), Park restoring 110V + pack mark, ±0s
take-to-take drift. Full regression green (p1/p2/p4/p5/p6/p8/p9).
NOTE: the shot-list docx (Technical Notes + the 2:01–2:23 beats) still
describes the two-stage version — flagged to Frank for a rev.

---

## 2026-08-03 — Shot-list docx rev'd to the three-stage shed

The open flag from P12b is closed: `OneDrive\VanGuard\
VanGuard_Scripts_ShotList.docx` now describes the three-stage ladder.
Technical Notes rewritten to the verified clock (crossing +20s, stages
+28/+40/+52s, chip +53s, recovery +60s; fast variant +12 / +19/+31/+43),
including the inverter-on / e-bike-chargers opening state and the Park
reset restoring the 110V circuit + pack mark. Cut A gains a STAGE 3 beat
at 2:13–2:23 ("E-bikes, you're charging on tomorrow's sunshine"), the
PROTECTED / voice / closing beats slide back ~10s, runtime ~2:57 → ~3:07.
Cut B's shed beat now names all three stages. FILMING.md's three stale
references (take span, "after Stage 2" voice beat, "two-stage shed" in
story mode) fixed to match. Backup of the pre-rev docx in the session
scratchpad.

**Cut B pacing (Frank's call):** Cut A may grow to ~3:07 — "if it's
compelling people will watch it" — but the LinkedIn short stays 60–70s.
Rev'd the docx again: the shed beat keeps all three stages but drops the
e-bike clause ("Then the whole 110-volt circuit." — the designated trim
line "Doodles, you can sit up front" kept verbatim), and the closer beat
trims to 0:52–1:08, dropping "three-minute" (the master isn't one
anymore). Cut B ~72s → ~68s.
