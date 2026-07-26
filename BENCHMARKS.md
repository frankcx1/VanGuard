# VanGuard inference benchmarks

**Nothing in this file is simulated** — real model, real silicon, measured
numbers (PLAN.md §8, P3).

## Environment

| | |
|---|---|
| Date | 2026-07-25 |
| Machine | Surface Pro for Business 13" (12th Ed), Core Ultra Series 3 (Panther Lake), 64 GB |
| NPU driver | 32.0.100.4512 (2025-12-08) |
| OpenVINO / GenAI | 2026.2.1 |
| Model | Qwen/Qwen3-4B-Instruct-2507 |
| Quantisation | INT4 symmetric, per-channel (NPU-friendly export), 2.1 GB on disk |
| Harness | `inference/bench.py` — 3 van-shaped prompts × 2 iterations per device, max 128 new tokens, greedy |
| Power source | **battery** (discharge rate from the machine's own gauge, `root\wmi BatteryStatus`, 1 Hz) |

## Results

| Device | Load/compile | TTFT (mean) | Tokens/sec | Mean draw | Energy/query |
|---|---:|---:|---:|---:|---:|
| **NPU** | 84.9 s | 727 ms | 27.2 | **18.4 W** | 0.023 Wh |
| **GPU** (Arc Xe3) | 13.3 s | **186 ms** | **36.7** | 23.4 W | **0.020 Wh** |
| **CPU** | 5.0 s | 1517 ms | 14.5 | 24.5 W | 0.060 Wh |

## The honest, non-obvious result

PLAN.md §5 predicted "GPU wins tokens/sec, NPU wins watts-per-token." Half
right:

- **The GPU wins speed outright** — 35% more tokens/sec and a 4× better
  time-to-first-token (186 ms vs 727 ms; the difference between a chat that
  feels instant and one that visibly thinks).
- **The NPU wins sustained power draw** — 18.4 W vs 23.4 W whole-system
  (~22% less while generating).
- **Energy per query is close to a wash** (0.020 vs 0.023 Wh): the GPU draws
  more but finishes sooner. The race-to-idle effect eats most of the NPU's
  wattage advantage at these batch-of-one query lengths.
- **CPU is the clear loser on every axis** except load time, at 3× the
  energy per query. It remains the fallback of last resort.

For scale: at 0.02 Wh/query, the van's 300 Ah / 3.8 kWh battery funds
~190,000 questions. One induction-cooktop dinner (≈ 0.7 kWh) costs the same
as ~35,000 of them. The AI is noise in the van's energy budget.

## Caveats (read before quoting)

- Power is **whole-system** discharge (screen on, Windows idle load
  included), not isolated accelerator power; no idle-baseline subtraction
  was done. Treat the watts column as comparative, not absolute.
- Short runs (6 queries/device). Thermal steady-state behaviour over long
  sessions is unmeasured; the NPU's low draw may matter more there.
- One model, one quantisation. The channel-wise symmetric INT4 chosen for
  NPU compatibility also runs on GPU/CPU, so the comparison is apples-to-
  apples — but a group-wise export might lift GPU quality/perf slightly.
- NPU compile is 85 s on first load per session — fine for a resident
  service, wrong for a CLI.

## Recommendation

Serving default stays config-driven (`inference.device_order`). Suggested:
**GPU first for interactive chat** (TTFT dominates perceived quality),
**NPU for the resident/kiosk service** where it leaves the GPU free for the
dashboard, draws less sustained power, and thermal headroom matters. Both
serve the same INT4 artifact; switching is a config edit.

*Watt-hours-per-query on the van's own telemetry (the better version of
this measurement) lands after M2, per PLAN.md §8.1.*
