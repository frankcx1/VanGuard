# VanGuard — System Document

*As built, 2026-07-27. Companion to `README.md` (quickstart), `PLAN.md`
(the plan and hardware truth), and `BUILD_LOG.md` (the full history,
failures included).*

VanGuard is a single-screen monitoring and AI-assistance system for a 2022
Mercedes Sprinter 3500XD camper van, built to demonstrate **private,
on-device, offline-capable AI**: a local language model on a Surface Pro's
Intel silicon that watches a power system, interprets it continuously,
answers spoken or typed questions, and proposes actions — with every claim
backed by deterministic math and an audit trail.

The van's telemetry is currently **simulated** by a physically-faithful
model (the hardware adapters land in Track M). The AI, the inference
silicon, the speech recognition, the benchmarks, and every calculation are
**real**.

---

## 1. Topology

Two OS processes share one SQLite database (WAL mode — writer and reader
never block each other):

```
vanguard-poller (writes)                vanguard-api (reads + serves)
┌─────────────────────────┐             ┌─────────────────────────────────┐
│ TelemetrySource         │             │ FastAPI (loopback only)         │
│   live | sim | replay   │  SQLite     │  /api/telemetry/*  → dashboard  │
│ SimSource: physical van │──WAL──────► │  /api/insight,outlook,alerts    │
│ commands table (applies │  samples    │  /v1/chat/completions → LLM     │
│  human control, sim-only)│ samples_1m │  /api/transcribe → Whisper      │
│                         │  tool_audit │  /api/watchdog → patrols        │
└─────────────────────────┘  commands   │  /api/runtime → honest status   │
                             patrols    │  web/ vanilla-JS dashboard      │
                             meta       └─────────────────────────────────┘
```

Separation rationale: a crashed model service never costs telemetry
history. The dashboard is dependency-free vanilla JS served locally — no
CDN, fonts, analytics, or external endpoint exists anywhere in the code.

## 2. Telemetry layer

**`TelemetrySource`** (`poller/source.py`) is the hinge of the whole
design: `live | sim | replay` behind one interface, selected in config.
Everything downstream is identical regardless of source. `live` (Track M:
Renogy Shunt 300 + BT-2/DCC50S over BLE) refuses all control commands by
default. `replay` plays back recorded `.jsonl` captures at N×.

**`SimSource`** (`sim/`) is a physically-modelled synthetic van:

- **Battery = coulomb counter** (300Ah × 12.8V = 3,840Wh, per the OGA
  invoice). SOC integrates net current; it is never assigned. Voltage is a
  piecewise LiFePO4 OCV curve (famously flat: ~13.4V at 100%, ~13.1V at
  50%) plus IR sag, with the DCC50S's bulk→absorption→float stages on top.
- **Solar** is a clear-sky bell scaled to the van's *observed* peak
  (200–300W, not the 400W nameplate), with a cloudy-weather random walk.
- **Loads**: fridge and freezer as duty-cycling compressors (the sawtooth
  that makes graphs look real), water-pump bursts, scheduled events,
  toggleable appliances, HVAC, inverter idle, Starlink dish.
- **Charge sources**: solar, alternator (auto while driving; manual
  "engine idling" override), shore (inverter/charger, deliberately
  *invisible* to telemetry — see Honesty, §8).
- **Inverter** (simulated; the real RIV1230RCL is CAN-only, unreadable in
  v1): off by default (the van is 12V-only until switched on), inverting
  with ~88% conversion loss, and **BYPASS on shore power** — outlets feed
  from shore, zero DC drawn, matching the documented van behaviour.
- **Climate**: cabin temperature drifting toward ambient + solar gain;
  heater (~25W DC, diesel heat) and A/C (~900W DC) with hysteresis.
- **GPS**: fixed campsite or route-following (Pacific Rim Hwy → Tofino);
  regional offline POI datasets auto-selected by position.
- **Network** (§7) and sensor noise/quantisation/dropout per device.

Emissions are deterministic per seed — every scenario replays identically,
which is what makes filmed takes reproducible.

**Storage** (`poller/store.py`): `samples` raw 48h → `samples_1m`
downsamples 30d (incremental, high-water-marked), `tool_audit` (forever),
`commands`, `patrols`, `meta`.

## 3. Deterministic intelligence

All arithmetic lives in server-side services. The model never computes.

- **Tools** (`api/tools.py`): ten read-only, schema-validated tools
  (battery, solar, loads, history-as-stats, climate, trip, POIs, network,
  tanks-stub, `estimate_runtime`). Every invocation is audited (args,
  result hash, serving device, latency). Tools pre-interpret anything a
  small model misreads: signs become words (`state: "charging"`,
  `charging_from: ["solar"]`), temperatures ship pre-converted `*_f`
  fields, and `estimate_runtime` returns the yes/no verdict itself
  (`stays_above_20pct`) so no consumer recomputes it.
- **Outlook** (`api/outlook.py`): runtime-to-reserve, SOC-at-sunrise,
  discretionary energy, solar-remaining — with **source persistence**
  (solar ends at sunset; alternator/shore project forward while active),
  explicit assumptions, and confidence that degrades with stale data.
- **Insight** (`api/insight.py`): always-on rules → natural-language
  interpretation + recommendation + confirm-gated proposed action
  (absorption-at-100% explainer, hot/cold cabin, driving-without-
  alternator, sensor-conflict data-quality notes, reserve forecasts).
- **Alerts**: severity stack (critical/warning/advisory/data-quality)
  driven by mode-aware thresholds.
- **Watchdog** (`api/watchdog.py`): autonomous patrol every N minutes —
  audited tool sweep → deterministic verdict → the local model writes the
  one-sentence report *from those findings* → logged to `patrols` with
  timestamp, surfaced in the Insight panel ("last check · every 5 min ·
  N today · source"), plus a manual "Check now".

## 4. Local AI

- **Model**: Qwen3-4B-Instruct-2507, INT4 symmetric channel-wise, exported
  via `optimum-cli` to OpenVINO (2.1GB). A config value, not an
  architecture decision. Serving order `inference.device_order`
  (NPU/GPU/CPU); the UI displays only the device the runtime actually
  loaded on. Measured (on battery): **NPU 27.2 tok/s @ 18.4W · GPU 36.7
  tok/s @ 23.4W · CPU 14.5 tok/s** — full method in `BENCHMARKS.md`.
- **Voice**: whisper-base.en on OpenVINO. The browser records raw 16kHz
  PCM (no cloud speech APIs) and posts WAV to `/api/transcribe`.
- **Anti-fabrication architecture** (each layer earned by an observed
  failure — see BUILD_LOG 2026-07-26/27):
  1. Every chat request auto-fetches a **full audited snapshot** (battery,
     solar, loads, climate, trip, network) into context — current-state
     numbers cannot be invented, and false premises get corrected against
     real values.
  2. **Runtime/energy questions never reach the model.** The server
     detects them, runs `estimate_runtime`, and composes the verdict
     sentence deterministically (the 4B inverted verdicts it was quoting,
     three designs in a row). Provenance: *"deterministic calculation ·
     verdict computed, never generated."*
  3. Everything else: the model interprets the question, may call tools
     (Hermes-style, parsed and validated), and phrases answers — with a
     provenance label and an expandable evidence trace on every reply.
  4. No model exported → a deterministic responder answers from the same
     tools, labeled. The app never needs the LLM to function.

## 5. Control plane

All controls are **human-initiated, sim-gated, audited**. The UI enqueues
a command (`commands` table); the poller applies it to the source within
one poll; a `live` source refuses (phase-1 read-only, defense in depth at
both API and poller). The AI has no write path — `get_climate` is
read-only and actuation isn't in its tool set. Audit rows record HUMAN as
the device for every switch flip.

Controls: charge sources (solar connect/disconnect, alternator "engine
running", shore "plugged in"), inverter on/off (cooktop auto-starts it
with an explanatory note; turning it off kills AC appliances), cooktop /
fridge / freezer / A-C toggles, HVAC mode + setpoint (°F), network mode,
sensor offline toggles (click a device in Diagnostics — its rows go
genuinely stale and red), operating mode (Camp/Sleep/Drive/Storage/
Emergency — policy data that shifts reserve and alert thresholds).

## 6. Dashboard

Single screen, no page scroll (tiles scroll internally; graceful fallback
under 1100px). Dark, validated-palette, entity-fixed series colors.

- **Status rail**: OFFLINE/uplink badge · SIM DATA (unless presentation
  mode) · LOCAL AI: <device> · <model> · DATA STAYS ON DEVICE · MIC ·
  mode selector · 🎬 Story · clock.
- **Battery** (SOC hero, V/A/°F, time-to-empty/full, 24h sparkline) ·
  **Power Flow** (sources → battery → loads with live reconciliation
  line, runtime-to-reserve readout, and all the toggles) · **Climate** ·
  **Insight** (+ watchdog strip) · **Outlook** (+ assumptions expander) ·
  **Trip** (position, miles today, offline POIs) · **Ask VanGuard**
  (chips, mic, provenance + evidence per answer) · **Inverter** ·
  **Network** · **Alerts** · **Diagnostics** (summary + drawer: raw
  readings with freshness colors, tool audit, honest AI-runtime panel).
- **Demo Story mode**: 8 presenter-paced steps driving the live dashboard
  (deep links `#story`, `#story=N`).

## 7. Network subsystem

Simulated uplinks with realistic behaviour: **5G** (the Surface's own
modem — no van load), **local Wi-Fi** (campground-grade pipe), and a
roof-mounted **Starlink Mini** modeled on the real dish: local gRPC-API-
shaped telemetry (state, latency, throughput, obstruction fraction) and
real power behaviour (12–48V native, ~60W boot spike, ~17–25W steady —
a genuine battery load the power panel shows). Obstruction raises an
advisory. The uplink carries internet only; the AI never leaves the
device either way.

## 8. Honesty & safety design

- The API stamps `"simulated": true` on every payload whenever the source
  isn't `live` — including in presentation mode (`-Presentation` hides
  the **UI labels only**, for filming; the data layer never lies).
- Shore power is *inferred* and always labeled so — the real charger is
  CAN-only and invisible; on shore, derived house load honestly reads
  "unavailable" rather than a wrong number.
- The runtime endpoint reports only measured facts: a device is named
  only after the pipeline actually compiled and served there.
- Read-only phase 1 throughout; actuation (phase 2) keeps the same queue
  plus explicit human confirmation.
- Not a safety system. See the README disclaimer.

## 9. Verification

Six deterministic harnesses (`scripts/verify_p1..p6.py`), ~160 checks:
physics (coulomb consistency, flat-band voltage, duty cycles, BYPASS),
storage/retention, API integrity stamps, tool discipline (verdict always
equals the calculator's), voice round-trip (SAPI TTS → Whisper), controls,
network, forecasts (including the alternator-persistence and overnight-
reserve cases), watchdog, fallback, provenance, runtime honesty. Model and
voice end-to-end stages are explicit and skippable; everything else needs
no LLM.

## 9.5 Guardian & whole-van fusion (P8/P9)

**Guardian** is a deterministic policy engine — the model is never in this
loop. Autonomy ladder (Observe/Advise/Ask/Protect/Emergency, user-selected,
sim-only actions), per-action permission classes with cooldowns, episodes
`detect → verify → decide → act → confirm → resolved` logged to
`guardian_events` and executed through the same audited command queue
(device=GUARDIAN). Low sensor confidence withholds all action. The model
answers "why did you do that?" from `get_guardian_log`, never from memory.
Full contract: `GUARDIAN_POLICY.md`.

During an episode `/api/guardian` also returns a server-built **event
card** (risk numbers, action + watts shed, verified before→after result,
and a decision receipt: evidence freshness, Mode · Level, "decision
deterministic · explanation on NPU", 0 external calls) — assembled
strictly from logged `guardian_events`, so the on-screen card can never
disagree with the audit trail. The UI enlarges the Guardian strip into
this card while the episode is live and surfaces an automatic
"why did you do that?" chat chip for 15 minutes after any action. Voice
questions display their pipeline honestly (`● LISTENING LOCALLY`, then
`VOICE → WINDOWS ON-DEVICE DICTATION (or LOCAL WHISPER) → model ON
<device> → VERIFIED TOOLS`, then a processed-on-this-device receipt);
the offline rail state reads `NO UPLINK · LOCAL AI ACTIVE`.

**Chassis domain** (simulated; real adapter = read-only OBD-II, see
`CHASSIS_RESEARCH.md`) adds engine state, chassis voltage, fuel/DEF,
coolant, odometer, DTCs — enabling **fusion findings** neither subsystem
can produce alone: the charging-path anomaly (engine healthy, house
starved, nothing blamed), arrival cleanup (park transition → Camp policy +
travel-load shed), and a departure-readiness checklist where unknowns are
NOT MONITORED, never PASS.

## 10. Road to real hardware

`PLAN.md` §12.5 maps every demo feature to its hardware path. Highlights:
M1 gate = read SOC from the Shunt 300 over BLE while the Renogy ONE Core
is powered (the project's defining risk); BT-2 → DCC50S Modbus; USB NMEA
GPS; BLE cabin thermometer; BT smart switches for fridge/freezer; Tuya-
local / Webasto-BLE research for real climate control; Starlink via
`starlink-grpc-tools` against the actual dish. The UI, storage, services,
and AI stack are finished — hardware lands as new `TelemetrySource`
adapters and nothing above them changes.
