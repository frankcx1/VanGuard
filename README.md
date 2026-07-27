# VanGuard

A single-screen monitoring and AI-assistance dashboard for a 2022 Sprinter
3500XD camper van — built to demonstrate the practical value of **private,
on-device, offline AI**: it monitors a power system, interprets telemetry,
answers spoken or typed questions, and keeps every byte on the machine.

> **Disclaimer:** VanGuard is currently a simulated demonstration. It is not
> a certified battery management, vehicle control, electrical protection,
> fire detection, or life-safety system. Do not use its estimates as a
> substitute for manufacturer guidance, installed safety equipment, or
> qualified electrical inspection.

## Current state — read this first

- **The van's hardware is not connected yet.** All telemetry comes from a
  physically-modelled simulator (coulomb-counting battery, real LiFePO4
  voltage curve, solar bell, fridge duty cycle). The UI stamps
  `"simulated": true` on every payload, shows a persistent **SIM DATA**
  badge, and all "controls" act only on the simulator.
- **The AI is real.** A local Qwen3-4B (INT4, OpenVINO) answers questions on
  this machine's Intel silicon — measured, not simulated (see
  `BENCHMARKS.md`: NPU 27.2 tok/s @ 18.4 W; GPU 36.7 tok/s). Speech-to-text
  is local Whisper. The dashboard only ever displays the execution device
  the loaded runtime actually reports — never an assumption.
- **The arithmetic is never the model's job.** Deterministic services
  (`api/tools.py`, `api/outlook.py`, `api/insight.py`) compute all
  electrical values, forecasts, and verdicts; the model interprets
  questions, picks audited read-only tools, and explains structured
  results. Every answer carries a provenance label.
- **No cloud, by construction.** No CDN, fonts, analytics, or external
  endpoints exist in the code. The inference endpoint is loopback-only.
  With no model exported the app still works: a deterministic engine
  answers, labeled "no model active".

## Running it

```powershell
# one command from cold to filmable (seeds history, starts poller + API,
# pre-warms the model, opens the dashboard):
.\scripts\demo.ps1                       # sunny_midday
.\scripts\demo.ps1 -Scenario driveway    # parked in Kirkland, WA
.\scripts\demo.ps1 -Scenario dusk_low    # the cooktop "no"
.\scripts\demo.ps1 -Stop
```

Scenarios (`sim/scenarios.py`, seeded + deterministic — a re-shoot gets the
same numbers): `sunny_midday`, `dusk_low`, `overnight_drain`, `shore_power`,
`cloudy_marginal`, `road_trip` (Tofino, BC drive), `driveway` (Kirkland, WA).

Manual start: `python -m poller` and `python -m uvicorn api.main:app`
(two processes; a crashed model service never costs telemetry history).
Config: copy `config/devices.example.yaml` → `config/devices.yaml`
(gitignored) or point `$env:VANGUARD_CONFIG` at one.

## Demo Story mode

Click **🎬 Story** in the status rail: a guided 8-step sequence drives the
*live* dashboard (real requests, all audited) with presenter-paced
Next/Back — ends on "Monitor. Understand. Act. Even when the cloud is out
of reach."

## Architecture

```
poller (writes)                       api (reads + serves)
  TelemetrySource  live|sim|replay      /api/telemetry/*   dashboard (vanilla JS)
  SimSource: physical van model         /api/insight       deterministic rules → NL
  commands table  (human, sim-gated)    /api/outlook       forecast/calc service
        │                               /api/alerts        severity stack
        └── SQLite WAL (samples, ───►   /v1/chat/completions  local LLM + tools
             samples_1m, tool_audit,    /api/transcribe    local Whisper STT
             commands, meta)            /api/runtime       honest runtime telemetry
```

- Everything hangs off the swappable `TelemetrySource` (`live|sim|replay`);
  the future BLE hardware adapter (Renogy BT-2 + Shunt 300) replaces the
  simulator without touching anything downstream. `live` refuses all
  control commands — actuation is phase 2, gated on human confirmation.
- The model is a config value (`inference.model_dir`, `device_order`), not
  an architecture decision. Runtime status (`/api/runtime`) reports the
  device the pipeline actually loaded on; "NPU" appears only when the NPU
  actually served.
- Operating modes (Camp / Sleep / Drive / Storage / Emergency) are policy
  data that shift reserve and alert thresholds, not visual labels.

## Verification

```powershell
.venv\Scripts\python.exe scripts\verify_p1.py   # simulator + storage (20)
.venv\Scripts\python.exe scripts\verify_p2.py   # API + integrity stamps (13)
.venv\Scripts\python.exe scripts\verify_p4.py   # tools, audit, tool-calling e2e (23)
.venv\Scripts\python.exe scripts\verify_p5.py   # demo mode, voice, controls (31)
.venv\Scripts\python.exe scripts\verify_p6.py   # insight, outlook, fallback, modes (32)
```

All deterministic except the explicitly-marked model/voice end-to-end
stages (`--skip-model` / `--skip-voice` to omit). `BUILD_LOG.md` is the
full history, failures included. `PLAN.md` is the authoritative plan;
§12.5 maps every demo feature to its real-hardware path.
