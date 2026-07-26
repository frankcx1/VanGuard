# Project VanGuard — PLAN.md

**Milestone M0 deliverable.** Written 2026-07-24, before any code.

Source of truth for hardware is `C:\vibe\Sprinter` (OGA invoices, Renogy manuals,
walkthrough transcripts). Every claim below is tagged **[verified]**,
**[verified-external]**, or **[UNVERIFIED]**. Do not write integration code
against anything tagged UNVERIFIED without checking it first.

---

## 1. Headline correction to the brief

The project brief's telemetry section assumes a **Victron ecosystem behind a
Cerbo GX, reachable over the van LAN via Modbus TCP on port 502.**

**There is no GX device in this van, and no Victron hardware of any kind.** The
van is an all-Renogy "Rego 440" stack installed by Off Grid Adventure Vans.
Nothing in it speaks Modbus TCP, and nothing in it is on the LAN.

Brief question #1 ("confirm the GX device model and LAN address") therefore has
no answer. Section 5 below replaces the brief's telemetry plan.

Everything else in the brief survives: read-only phase 1, no cloud at runtime,
OpenVINO on the Intel NPU, FastAPI + dashboard + local chat, audit logging,
watt-hours-per-query as the video's data point.

---

## 2. Verified hardware inventory

From `2024 05 31 OGA Sale and Invoices - OCR text.txt:55-90` **[verified]**:

| Component | Model | Notes |
|---|---|---|
| Battery | Renogy 12V 300Ah **Core Series** LiFePO4, self-heating | 200A BMS |
| Inverter/charger | Renogy RIV1230RCL-1SS-G1, 3000W | ships with Renogy ONE Core monitor |
| Solar | 2 × 200W Renogy panels | 400W nominal |
| DC-DC / MPPT | Renogy **DCC50S** 12V 50A | alternator + solar charging |
| Shunt | Renogy **Battery Shunt 300** (RSHST-B02P300) | battery monitor |
| Protection | 300A ANL fuse, 60A ANL, bus bars | |

Not present, despite the manual being in the docs folder: **Communication Hub
G1**. Not on the invoice, not owned. See §4 — do not buy it.

### Van context that constrains the design **[verified from memory/docs]**

- Golden rule: battery ON first in any off-grid mode.
- Solar OFF when on shore power or chassis-charging (documented overcharge issue).
- Inverter reads BYPASS on shore power.
- Induction cooktop ≈ 1500W — the demo question's subject.
- No electronic tank level sensors on the invoice. **[UNVERIFIED — confirm visually]**
- Cruise N Comfort A/C is Tuya/Smart Life cloud; Webasto heater is Bluetooth
  SmartTemp. Neither is in scope for v1.

---

## 3. Telemetry reachability — what each device can actually give us

| Device | Interface | Reachable? | Confidence |
|---|---|---|---|
| **Shunt 300** | Bluetooth LE, own built-in radio, advertises as `RTMShunt300*` | **Yes — BLE** | [verified-external] |
| **DCC50S** | RS485 / Modbus RTU 9600 baud over RJ45, via BT-2 dongle | **Yes — BLE via BT-2** | [verified-external] |
| **Core 300Ah battery** | **None.** Core Series has no comms port | **No** | [verified-external] |
| **Inverter RIV1230RCL** | CAN bus (RV-C style) on RJ45 + Bluetooth | Not in v1 | [verified] |
| **Renogy ONE Core** | Wi-Fi + BLE Mesh, cloud-oriented | No documented local API | [verified-external] |
| Tanks / heater / A/C | — | Stubbed | — |

Three findings drove this:

1. **Core Series vs Smart Lithium is precisely the comms distinction** in
   Renogy's product line. Smart Lithium has the RJ45/RS485 port; Core Series
   does not, and the BMS hardware differs so it cannot be retrofitted. The
   battery will tell us nothing directly.
2. **The Shunt 300 is BLE-only** (spec sheet: "Bluetooth LE, Bluetooth Mesh"),
   with no RS485 port. It cannot be put on a wired bus at any price.
3. **The inverter is CAN, not RS485**, so it can't share a bus with the DCC50S.

Consequence: **SOC — the number the entire demo depends on — is only available
over Bluetooth LE.** There is no wired path to it. This is the project's
single largest risk and M1 exists to retire it.

### What we get, and what we can derive

Directly from the shunt: battery voltage, net current (signed), SOC, power,
temperature, cumulative charge/discharge counters.

Directly from the DCC50S: PV voltage / current / power, alternator input,
charge current out, controller temperature, daily yield.

Derived:
- `net_power_w` = shunt power (signed; positive = charging)
- `load_w` = (charge sources in) − (net battery power) — **valid off-grid only.**
  On shore power the inverter/charger becomes a charge source we cannot see
  (CAN only), so load derivation breaks. Flag it in the UI rather than lying.
- `time_to_empty_h`, `time_to_full_h` from SOC + net current
- `solar_yield_wh_today` from DCC50S daily counters

**We cannot break loads down by circuit.** There is one shunt on the battery,
so DC load is a single aggregate number. The brief's "load breakdown if
available" is not available — drop it rather than fake it.

---

## 4. Bill of materials

| Item | Cost | Verdict |
|---|---|---|
| **Renogy BT-2 Bluetooth Module** (RS485/RJ45 version) | ~$30 | **BUY — required for DCC50S** |
| Shunt 300 connectivity | $0 | Nothing needed; built-in BLE |
| Renogy Communication Hub G1 | ~$50 | **DO NOT BUY** |
| USB-RS485 (FTDI FT232RL) + RJ45 breakout + Cat5e | ~$25 | Hedge only, if BLE fails M1 |

**Why not the Hub:** its entire purpose is aggregating *multiple* RS485 devices
onto one BT-2. After the three findings above, the van contains exactly **one**
RS485 device (the DCC50S). The shunt can't attach to it, the battery has no
port, and the inverter is CAN. It would be a $50 pass-through. Revisit only if
a Smart Lithium battery or a second RS485 device is ever added.

Get **BT-2, not BT-1** — BT-1 is RS232 and will not talk to the DCC50S.

---

## 5. Compute platform

**Microsoft Surface Pro for Business, 13-inch (12th Edition), Intel** **[verified-external]**

- Intel Core Ultra Series 3 (Panther Lake), **x86-64** — full OpenVINO support
- Intel AI Boost NPU, **50 TOPS**
- Intel Arc (Xe3) integrated GPU
- LPDDR5x — **64 GB** [verified 2026-07-25, `Win32_ComputerSystem`]

Note this is the *Business 13-inch* line, distinct from the consumer Surface
Pro 12-inch, which is Snapdragon/ARM and would have made OpenVINO's NPU plugin
unusable. The Intel SKU is the correct choice for this project.

### Two caveats that shape M4

**Panther Lake is new.** OpenVINO support for a new NPU generation lands with a
lag. Before any model work:

```powershell
python -c "import openvino as ov; print(ov.__version__); print(ov.Core().available_devices)"
```

`NPU` must appear in that list. If it doesn't, update the Intel NPU driver
before concluding anything. This gates M4 entirely.

**Do not assume the NPU wins the benchmark.** LLM token generation is
memory-bandwidth-bound, not compute-bound, so 50 TOPS does not translate the
way it does for vision models. Expect the **Arc iGPU to win tokens/sec and the
NPU to win watts-per-token**. For a van, watts-per-token is the metric that
matters — which makes the three-way benchmark a real experiment and gives the
video an honest, non-obvious result. Log which device served each request.

---

## 6. Model stack

**Recommendation: do not use Mistral-7B-Instruct-v0.2 as the primary.**

The brief specifies it, and the brief also concedes the consequence: v0.2 has
no native function calling, so tool use must be hand-rolled as JSON-in-a-system-
prompt with retry-on-malformed. That is a permanent tax on the most failure-prone
part of the system, paid to use a 2023 model.

Since the brief correctly mandates that **the model is a config value, not an
architecture decision**, this costs nothing to change and nothing to revisit.

- **Primary:** a modern 3–4B instruct model with *native tool calling*. Faster
  time-to-first-token, cleaner structured output, and far more headroom inside
  the NPU's 2–4k static-shape context window once tool results are injected.
- **Fallback:** Mistral-7B-Instruct-v0.2 INT4, exactly as the brief specifies,
  if the smaller model can't hold the reasoning quality for the cooktop question.

Export path is unchanged either way:

```
optimum-cli export openvino --model <model-id> --weight-format int4 ov_<name>_int4
```

Serving: OpenVINO GenAI behind a small FastAPI service exposing an
OpenAI-compatible `/v1/chat/completions`. Device selection abstraction tries
NPU → GPU → CPU, records which device served each request.

**Context discipline is a hard requirement, not a nicety.** NPU pipelines use
static shapes. Tool outputs must be compact — return numbers and units, not
prose. Budget: system prompt + tool schema ≤ 800 tokens, tool results ≤ 400
tokens, leaving room for history.

---

## 7. Architecture

```
  Shunt 300 ──BLE──┐
                   ├──┐
  DCC50S ──BT-2────┘  │
                      ├──> [ TelemetrySource ] ──> poller ──> SQLite (WAL)
  sim / replay ───────┘         (swappable)                       │
                                                                  v
                                   FastAPI ──> /api/telemetry/*  ──> dashboard (SPA)
                                        │
                                        └──> /v1/chat/completions ──> OpenVINO GenAI
                                                    │                  (NPU→GPU→CPU)
                                                    └──> tools ──> SQLite + audit table
```

Two processes: `vanguard-poller` and `vanguard-api`. Keeping the poller separate
means a crashed model service never costs us telemetry history.

### Telemetry source abstraction — the POC hinge

Everything downstream of `TelemetrySource` is identical whether the numbers come
from a real shunt or a simulator. Three implementations behind one interface:

- **`LiveSource`** — BLE, the real thing. Requires M1 to pass.
- **`SimSource`** — physically-modelled synthetic van. No hardware at all.
- **`ReplaySource`** — plays back a recorded `.jsonl` capture at 1× or N×.

Selected by `config/devices.yaml: source: live|sim|replay`. This is not
scaffolding to be thrown away — it's how we get deterministic test fixtures,
how the demo survives a BLE dropout on camera, and how the whole app gets built
and filmed before the BT-2 arrives.

**Integrity guardrail:** when `source != live`, the dashboard renders a
persistent **`SIM`** badge and the API stamps `"simulated": true` on every
payload. Non-negotiable — a screenshot of this thing must never be able to
misrepresent itself as live van data.

### Making the simulator look real

Fake telemetry reads as fake when it's smooth. Real telemetry is steppy, noisy,
and quantized. The sim must model:

- **Battery as coulomb counter.** SOC integrates net current over time — it is
  never set directly. Everything else follows from that.
- **A real LiFePO4 voltage curve**, not a linear ramp. The curve is famously
  flat: ~13.4V resting at 100%, ~13.1V at 50%, ~12.9V at 20%, then a cliff.
  Charging pushes to 14.4V bulk → absorption → ~13.6V float. A linear V-vs-SOC
  ramp is the single most obvious tell to anyone who knows these batteries.
- **Voltage sag under load**, proportional to current draw, recovering on release.
- **Solar as a bell curve** over the day, scaled by a weather factor and panel
  derate. Anchor to reality: the forum screenshot in `Renogy and Power/` shows
  this van's actual observed Pmax at **200–300W** against 400W nominal. Peak
  the sim there, not at 400W.
- **Fridge duty cycling.** The Alpicool C40 compressor pulls ~45–60W and cycles
  roughly 30–50% depending on ambient. This is what makes a load graph *look*
  right — a sawtooth, not a flat line.
- **Discrete load events**: cooktop 1500W AC (≈1700W DC after inverter losses,
  ~133A at 12.8V), water pump bursts, MaxxFan, lights.
- **Sensor noise and quantization** matched to the real devices' resolution.

**Scenario presets** — the part that actually matters for filming, because you
cannot wait for the battery to reach 40% at dusk to shoot a take:

| Preset | State | Purpose |
|---|---|---|
| `sunny_midday` | SOC 85%, 290W PV, light load | dashboard hero shot |
| `dusk_low` | SOC 42%, 0W PV, 35W base load | **the cooktop question** |
| `overnight_drain` | SOC falling, no PV | time-to-empty tile |
| `shore_power` | charging, loads underivable | proves the honest "unavailable" state |
| `cloudy_marginal` | SOC 30%, intermittent PV | the answer should be *no* |

Scenarios are seeded and deterministic, so a take is **reproducible** — you can
re-shoot the same shot and get the same numbers.

**Upgrade path:** once M1 passes, record 48h of real telemetry to a capture file
and drive `ReplaySource` from that. The demo then runs on genuine van data,
merely time-shifted — maximum realism, zero fabrication.

### Repo layout

```
VanGuard/
  PLAN.md                 <- this file
  BUILD_LOG.md            <- running log, failures included
  BENCHMARKS.md           <- NPU vs GPU vs CPU results
  config/
    devices.yaml          <- BLE MACs, poll cadence, model id, device order
  poller/
    source.py             <- TelemetrySource interface
    ble.py                <- LiveSource: bleak transport
    renogy_shunt.py       <- Shunt 300 parser
    renogy_dcc50s.py      <- DCC50S Modbus-over-BLE register map
    store.py              <- SQLite writer, downsampling
  sim/
    van_model.py          <- SimSource: coulomb counting, LiFePO4 curve, solar
    loads.py              <- fridge duty cycle, cooktop, pump, fan
    scenarios.py          <- seeded presets (dusk_low, sunny_midday, ...)
    replay.py             <- ReplaySource: playback of recorded captures
    captures/             <- recorded .jsonl telemetry (real, once M1 passes)
  api/
    main.py               <- FastAPI, telemetry routes
    chat.py               <- OpenAI-compatible proxy
    tools.py              <- tool implementations + audit
  inference/
    export.py             <- optimum-intel export helper
    serve.py              <- OpenVINO GenAI wrapper, device selection
    bench.py              <- benchmark harness
  web/                    <- dashboard SPA, dark, big tiles
  video/
    SHOT_LIST.md
    CAPTION_SCRIPT.md
```

### Data model

```sql
CREATE TABLE samples (           -- raw, 48h retention
  ts INTEGER NOT NULL,           -- unix seconds
  source TEXT NOT NULL,          -- 'shunt' | 'dcc50s'
  metric TEXT NOT NULL,
  value REAL NOT NULL
);
CREATE TABLE samples_1m (        -- 1-minute averages, 30d retention
  ts INTEGER, source TEXT, metric TEXT,
  avg REAL, min REAL, max REAL, n INTEGER
);
CREATE TABLE tool_audit (        -- every tool invocation, phase 1 and beyond
  ts INTEGER NOT NULL,
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  result_hash TEXT NOT NULL,
  device TEXT,                   -- which inference device served the request
  duration_ms INTEGER
);
```

### Tool schema (phase 1 — read only)

| Tool | Status vs brief |
|---|---|
| `get_battery_state()` | as specified — SOC, V, A, W, temp |
| `get_solar_state()` | as specified — PV W, daily yield |
| `get_loads()` | **narrowed** — single aggregate DC load, off-grid only |
| `get_history(metric, window)` | as specified |
| `get_tanks()` | **stub** — no sensors; manual entry or drop |
| `estimate_runtime(load_watts)` | as specified |

The AI can see everything and touch nothing. No write registers are exposed,
and the BLE transport is read-only by construction in v1.

---

## 8. Milestones

Two tracks. **Track P runs to completion without any van hardware** and produces
a filmable system. Track M swaps in real telemetry. They converge at M2.

**M0 — Verified plan.** This document. Repo initialized, first commit before
any code. *Done.*

---

### Track P — POC / demo build (no hardware required)

Runs entirely on the Surface Pro. Nothing here waits on the BT-2 or on van
access. This is the initial MVP and the thing that gets filmed.

**P1 — Simulator + storage.** `SimSource` with the physical model from §7,
scenario presets, SQLite schema, downsampling, derived metrics. Verify by eye
that a 24h run produces a plausible-looking graph — flat LiFePO4 voltage curve,
sawtooth fridge load, solar bell peaking ~290W.

**P2 — Dashboard.** The real dashboard, dark, big tiles, 24h sparklines, `SIM`
badge. Because P1 sits behind `TelemetrySource`, this is the *final* dashboard,
not a mockup — it will light up on live data unchanged.

**P3 — Inference. The NPU story, and it is 100% real.**
Confirm OpenVINO enumerates `NPU`. Export INT4. Benchmark NPU vs GPU vs CPU:
tokens/sec, TTFT, watts. Write BENCHMARKS.md.
**Nothing about this milestone is simulated** — real model, real NPU, real
silicon, real numbers. The van's telemetry source is irrelevant to it.

**P4 — Chat + tools against the simulator.** Full tool-calling loop, audit log,
audit view. The cooktop question answers correctly against `dusk_low` with the
math shown. End-to-end system, one adapter short of live.

**→ Filmable here.** See §8.1.

---

### Track M — Live hardware

**M1 — Hardware handshake. THE GATE.**
Prove one real number arrives from real hardware, on the Surface Pro, in the van.

- Read SOC from the Shunt 300 over BLE with `bleak`
- **Critical test: does it work while the Renogy ONE Core is powered on?**
  BLE peripherals typically accept one central connection at a time. The ONE
  Core is almost certainly already holding the shunt. The phone's DC Home app
  is a third contender.
- Read PV watts from the DCC50S via BT-2
- Confirm both can be polled in the same round-robin

If M1 fails, the project changes shape — see §9. Track P is unaffected either
way, which is the point of building it first.

**M2 — Live poller.** Implement `LiveSource` against the same interface P1
already proved. asyncio, **20–30s cadence** (not the brief's 5–10s; BLE must
round-robin sequentially and a van has no need for faster). Flip
`source: live` and the dashboard, tools, and chat from Track P light up
unchanged. Cross-check every value against the DC Home app before trusting it.

**M3 — Record the replay corpus.** Capture 48h of real telemetry to
`sim/captures/`. From here the demo can run on genuine van data, time-shifted.

**M4 — Kiosk, mount, capture.** Edge kiosk mode, 12V USB-C PD feed, mounted,
in-van footage.

**Stretch:** local STT voice input, offline solar forecast, water bowl sensor.

---

## 8.1 What can be filmed, and when

The brief's beat sheet splits cleanly. Three of five beats need **no van at
all** — they need the Pro and a working system, which is exactly what Track P
delivers.

| Beat | Needs | Film after |
|---|---|---|
| 3. Build montage (20s) — data flowing, model loading, terminal benchmarks | Pro only | **P3** |
| 4. Governance flex (5s) — "sees everything, touches nothing", audit log | Pro only | **P4** |
| Benchmark overlay graphic — "one question costs X watt-hours" | Pro only | **P3** |
| 1. Cold open (3s) — cooktop question answered | Pro + van interior shot | P4 for the answer, van for the setting |
| 2. Reveal (8s) — pan to campsite, "no signal" | Van + location | M4 |
| 5. Kicker (5s) | Van + location | M4 |

**On honesty in the edit.** The NPU story is genuinely real at P3 — the model,
the silicon, the tokens/sec, the watt-hours are all measured, not staged. Only
the *battery numbers* are synthetic, and only until M2. So:

- Shoot the build montage, the benchmark overlay, and the governance beat now.
  Nothing in them is simulated.
- The cold open makes a claim about **live van data**. Shoot it after M2, or
  after M3 with a real recorded capture driving replay. Do not shoot the cold
  open against `SimSource` and present it as live.

The `SIM` badge exists partly so this line can never be crossed by accident on
camera.

**Watt-hours per query** is measurable at P3 without the van: benchmark loop on
battery power, read the Pro's own battery drain via
`Get-CimInstance -Namespace root\wmi BatteryStatus`. Once M2 lands, re-measure
via the van's shunt — the system measuring its own cost of thinking through its
own telemetry pipeline, which is the better version of the shot.

### Machine split

Work that can happen on **this desktop now**: all of P1 and P2 (simulator,
storage, dashboard), tool implementations, parser code against fixtures, and
model export (INT4 conversion is CPU/RAM work, no NPU needed).

Work that **must happen on the Surface Pro**: P3 and P4 (NPU compilation,
benchmarking, and the filmed inference story), all of M1/M2 (BLE hardware),
kiosk mode, and all capture.

Since Track P is the filming target and P3 is Pro-only, the Pro should come
online before the BT-2 does — it is the longer pole.

Port by cloning the repo. Keep `config/devices.yaml` machine-local and
gitignored — it will hold BLE MAC addresses.

---

## 9. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| **BLE contention with Renogy ONE Core** | **Project-defining** | M1 tests it first. Fallbacks: wired USB-RS485 to DCC50S + SOC estimated by coulomb-counting from current; or displace the ONE Core |
| BLE range/reliability in a metal van | Dropouts | Mount the Pro near the electrical bay; poller retries with backoff; dashboard shows sample staleness |
| OpenVINO lacks Panther Lake NPU support | M4 slips | Check before M4. GPU fallback is fully acceptable and may be faster anyway |
| NPU 2–4k context too tight | Tool calls truncate | Compact tool outputs; GPU fallback for long context; log serving device |
| Register maps wrong for our firmware | Bad numbers | Cross-check every value against the DC Home app before trusting it |
| Load derivation invalid on shore power | Misleading UI | Detect charging state; show "unavailable on shore power" rather than a wrong number |
| RAM SKU too small | Model won't fit | Unknown until measured; 16GB is workable for INT4 3–7B |
| **Sim and live diverge** — code works on `SimSource`, breaks on real data | Track P's value evaporates | Sim emits the *same units, ranges, and quantization* as the real devices, including noise and dropouts. Sim must be able to emit stale/missing samples too |
| Demo shown as live by accident | Credibility | `SIM` badge on the dashboard, `"simulated": true` in every API payload, §8.1 shot discipline |
| BLE drops out mid-take on camera | Ruined shot | `ReplaySource` on a real capture gives a deterministic, reproducible take |

---

## 10. Open questions

1. ~~**RAM SKU** — 16, 32, or 64GB?~~ **Closed 2026-07-25: 64 GB** [verified —
   `Win32_ComputerSystem` on the Pro]. No RAM constraint on model size at P3.
2. ~~**NPU driver version** and whether OpenVINO enumerates `NPU`.~~
   **Closed 2026-07-25:** Intel(R) NPU present, Status OK, driver
   **32.0.100.4512** (2025-12-08). OpenVINO **2026.2.1** enumerates
   **`['CPU', 'GPU', 'NPU']`** [verified — run on the Pro]. P3 unblocked.
3. **Are there any tank level sensors?** Visual check. Determines whether
   `get_tanks` is real or dropped.
4. **Mount location and 12V USB-C PD feed** for the Pro (brief Q3).
5. **Mic** for the voice stretch goal (brief Q4).
6. **Van access window** — M1 and everything after it require the physical van.

---

## 11. Relationship to the existing Master Index app

`C:\vibe\Sprinter\_MasterIndex\app.py` is a working 7-tab Flask app with van
docs, transcripts, an electrical panel map, and an "Ask" tab currently wired to
the cloud Anthropic API.

**VanGuard stays a separate greenfield repo**, per the brief's ground rules.
The integration seam comes later and is one line: point the Master Index "Ask"
tab at VanGuard's OpenAI-compatible `/v1/chat/completions`. That converts the
existing app to fully-offline AI for free, and keeps two clean systems rather
than one tangled one.

---

## 12.5 Demo mode and the road to real (added 2026-07-26, P5)

P5 added demo-mode features Frank asked for. Each is honest about what's
simulated and has a defined path to real hardware:

| Feature | Demo (now) | Real (later) |
|---|---|---|
| Charge-source tile | derived from DCC50S PV/alt watts; shore is **inferred** and labeled so | same code on live data (M2) |
| Alerts | thresholds in config, banner + `/api/alerts` | unchanged on live data |
| Cabin temp | simulated | **BLE thermometer (~$20 Govee/SwitchBot)** — add to the M1 order alongside the BT-2 |
| Climate control | sim-only; human-only buttons; poller-level refusal on live sources | phase 2. Real A/C is Tuya/Smart Life **cloud** (needs Tuya local-key work); heater is Webasto BLE SmartTemp (undocumented protocol). Both research items, not v1 |
| Voice | **fully real already** — Whisper base.en on OpenVINO (GPU), browser records raw PCM, zero cloud | maybe NPU serving; better mic at M4 kiosk |
| Trip keeper | simulated GPS on a Tofino route; **offline curated POI dataset** | **USB GPS (u-blox NMEA, ~$15)** — M1 order; POI data stays offline by design (bigger regional dataset is a data problem, not code) |
| Actuation rule | commands table: human-initiated, audited as HUMAN, sim-gated | phase 2 keeps the same queue + explicit confirmation |

## 12. Ground rules (carried forward from the brief)

- **Greenfield repo.** No prior Microsoft-era code, ever.
- **No cloud at runtime.** Downloads during build are fine; once running,
  zero connectivity required.
- **Read only, phase 1.** The AI sees everything and touches nothing. Write
  access is phase 2, gated behind explicit human confirmation.
- **Every tool call logged** to `tool_audit`.
- **Document as you go.** BUILD_LOG.md, failures included.
