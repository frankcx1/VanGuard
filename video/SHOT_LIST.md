# VanGuard shot list

> **SUPERSEDED (2026-08-01):** the production scripts and shot list for the
> shoot live in `OneDrive\VanGuard\VanGuard_Scripts_ShotList.docx` (Cut A
> ~2:57 YouTube master, Cut B ~72s LinkedIn short, B1–B20 + pickups +
> graphics). The app-side run sheet for that document is **FILMING.md** —
> launch with `-Take forgot_switch`. This file remains for the earlier
> beat-by-beat material below.

Beats from the brief, split by what they need (PLAN.md §8.1). **Shootable
tomorrow: 3, 4, and the benchmark overlay — Pro only, nothing staged.**

Honesty rules on set (CLAUDE.md — non-negotiable):
- Dashboard shots run on `SimSource`; the **SIM badge stays in frame**. Do
  not crop it, do not present these shots as live van data.
- The inference/benchmark material is **100% real** — real model, real NPU,
  measured numbers. Say so with a straight face.
- The cold open (beat 1) claims live van data → **do not shoot the screen
  content until M2/M3**. Van-interior b-roll for it can be shot anytime.

## Setup (once)

```powershell
cd C:\vibe\vangaurd
.\scripts\demo.ps1                     # sunny_midday, hero dashboard
.\scripts\demo.ps1 -Scenario dusk_low  # cooktop-question take
.\scripts\demo.ps1 -Stop               # between scenarios
```

The launcher seeds a full day of history (sparklines populated from frame
one), pre-warms the model (no on-camera compile stall), and opens the
dashboard. Scenarios are seeded/deterministic — re-shoots reproduce the
same numbers.

## Beat 3 — build montage (~20s) · Pro only · READY

| Shot | Source | Notes |
|---|---|---|
| 3a. Dashboard alive: tiles, sparklines, fridge sawtooth | `demo.ps1` (sunny_midday) | F11 fullscreen Edge; SIM badge visible |
| 3b. Terminal: poller log lines scrolling | `python -m poller --config sim\captures\demo\devices_sunny_midday.yaml -v` in a visible terminal | real process, real writes |
| 3c. Model loading: run `python inference\bench.py --model-dir ov_qwen3_4b_instruct_2507_int4_npu --devices NPU --iters 1` | terminal | the 85s NPU compile + per-prompt tok/s lines are the shot |
| 3d. Benchmark table: open BENCHMARKS.md | editor/terminal | real measured numbers |

## Beat 4 — governance flex (~5s) · Pro only · READY

Ask a question in the chat tile (dusk_low scenario), then pan/cut to the
**Tool audit** tile: tool name, args, serving device, latency, result hash.
Caption: "sees everything, touches nothing." Every row on screen is a real
audited invocation.

Suggested on-camera question: *"Can I run the cooktop for 25 minutes?"* →
correct marginal **no** (24 min to the 20% floor, lands at 19.6%).

## Benchmark overlay graphic · Pro only · READY

Numbers from BENCHMARKS.md (measured on battery, 2026-07-25):
- NPU 27.2 tok/s @ 18.4 W · GPU 36.7 tok/s @ 23.4 W · CPU 14.5 tok/s
- **≈ 0.02 Wh per question** → the van's 3.8 kWh battery ≈ 190,000 questions
- One cooktop dinner ≈ 35,000 questions

## Beat 1 — cold open (3s) · NEEDS VAN + M2/M3 · defer screen content

Van-interior framing/b-roll can be shot tomorrow if the van is available;
the screen answering the cooktop question as *live data* waits for M2 (or
M3 replay of a real capture).

## Beat 2 — reveal (8s) & Beat 5 — kicker (5s) · NEEDS VAN + LOCATION · M4

## Demo-mode shots (P5, added 2026-07-26) · Pro only · READY

| Shot | Setup | The moment |
|---|---|---|
| Voice question | any scenario; hold 🎤, ask "what's my battery level?" | fully offline Whisper→LLM→tools round trip; caption "no cloud heard that" |
| A/C hits the battery | `demo.ps1 -Scenario sunny_midday`, press Cool | net power dives ~900W within one poll; ask "how long can the A/C run?" |
| Road trip | `demo.ps1 -Scenario road_trip` | Charging From shows ☀️+🚐 while driving; Trip tile counts miles into Tofino |
| Trip advice | road_trip parked, ask "what should we do nearby?" | POIs from the **offline** dataset, battery reality woven in |
| Low-battery warning | `demo.ps1 -Scenario dusk_low` (seeds to ~38%; wait or ask about loads) | alert banner: honest thresholds, not drama |

## Practical notes

- Chat serves on **GPU** by default (TTFT 186 ms — feels instant on
  camera). For an NPU-specific shot, use 3c's bench run; it prints the
  device per line.
- Staleness chip appears if the poller dies — if you see ⚠ STALE on
  camera, cut and restart with `demo.ps1`.
- Display scale: dashboard is a responsive grid; 1920×1080 fullscreen
  gives 4 tiles per row.
- `shore_power` scenario exists to film the honest "unavailable on shore
  power" load tile if the edit wants the integrity story.
