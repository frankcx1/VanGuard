# VanGuard vNext — Guardian + Whole-Van Intelligence

**Status:** Proposed build plan, not yet approved  
**Target:** VanGuard vNext after the current P7 demo baseline  
**Working theme:** **One van. One local intelligence layer.**  
**Primary capability:** Correlate house-system telemetry with Mercedes chassis state, detect developing problems, apply local policy, and safely recommend or perform narrowly authorized corrective actions.

---

## 1. Executive proposal

VanGuard currently demonstrates private, on-device AI over the **house side** of a 2022 Mercedes Sprinter 3500XD camper van: battery, solar, alternator input, shore state, inverter, loads, climate, network, trip context, forecasts, voice, and an audited local Qwen model.

vNext should expand VanGuard in two directions:

1. **Guardian:** turn monitoring into a closed operational loop:
   **detect → verify → decide → act or ask → confirm → explain**.
2. **Whole-Van Intelligence:** add a read-only Mercedes/chassis telemetry source and fuse it with the existing house-system data.

The objective is not to build another page of gauges. It is to let VanGuard understand relationships that neither subsystem can explain alone.

Examples:

- The engine is running and chassis voltage is healthy, but the house battery is still discharging.
- The van has arrived and shut down, but travel-mode loads remain active and will violate the overnight reserve.
- Alternator charging has declined across several trips even though route, battery SOC, and ambient conditions are comparable.
- A chassis or house sensor has become unreliable, so VanGuard withholds action rather than acting on low-confidence data.

The result should remain a single-screen, offline-capable, auditable application whose safety-critical arithmetic and policy decisions are deterministic. The local model interprets requests and explains verified findings; it does not invent measurements, calculate electrical limits, or directly control the vehicle.

---

## 2. Product thesis

> **VanGuard is the local intelligence layer above the van’s disconnected systems.**

The owner should not need to think in terms of “front of van” and “back of van.” Those are implementation boundaries.

VanGuard should present one operational state:

- Is the van healthy?
- Is energy moving where it should?
- Will the current configuration make it through the night?
- Is a fault likely in the chassis, charging path, house system, or sensor layer?
- Did VanGuard take an action?
- Why did it take that action?
- Did the action improve the condition?
- What data, if any, left the device?

This is the capability a van-life integrator could eventually configure across different builds and component vendors.

---

## 3. Current baseline to preserve

vNext must build on the current system rather than replace it.

Preserve these architectural invariants:

- `TelemetrySource` remains the source abstraction.
- `live | sim | replay` remain first-class operating modes.
- The poller and API remain separate processes over SQLite WAL.
- The dashboard remains locally served and dependency-free at runtime.
- No cloud endpoint is required for telemetry, inference, speech, or control.
- Every payload remains stamped with its real source and simulation status.
- The UI names an inference device only when the runtime confirms it.
- Electrical calculations, forecasts, thresholds, and verdicts remain deterministic.
- The LLM remains a language and tool-selection layer, not the safety controller.
- All tool calls, patrols, proposals, confirmations, actions, and results are audited.
- Live vehicle integrations begin read-only.
- A missing or uncertain value is labeled unavailable or low-confidence rather than inferred as fact.
- The application remains useful when the local model is unavailable.

---

## 4. vNext goals

### 4.1 Guardian operational loop

Add a visible Guardian capability that can:

1. Detect a developing problem.
2. Validate that the supporting readings are fresh and mutually consistent.
3. Classify the risk and affected subsystem.
4. Evaluate the active operating-mode policy.
5. Select the least disruptive eligible response.
6. Ask for confirmation or execute a preauthorized simulated action.
7. Verify the post-action state.
8. Report what happened in plain language.
9. Preserve the complete evidence and decision trail.

### 4.2 Read-only Mercedes/chassis telemetry

Create a new chassis telemetry boundary without assuming the eventual transport.

Candidate transports may include OBD-II, Mercedes-specific diagnostics, a passive CAN interface, GPS, or another read-only adapter. **No transport or signal is considered available until verified against the specific 2022 Sprinter 3500XD.**

### 4.3 Whole-van state fusion

Correlate chassis, house, location, time, and operating-mode data into one normalized `VanState`.

### 4.4 Integrator-ready configuration

Move vehicle-specific and house-system-specific knowledge into configuration and adapter layers so the core Guardian logic is not hard-coded to one van.

### 4.5 Stronger demonstration story

Produce a repeatable 60–90 second scenario in which VanGuard predicts a problem, applies policy locally, takes or proposes a corrective action, verifies the result, and explains the decision without using a cloud model.

---

## 5. Non-goals

vNext is **not**:

- A certified battery-management system.
- An automotive safety controller.
- A replacement for Mercedes diagnostics.
- A fire, carbon-monoxide, collision, or life-safety system.
- A system that transmits commands onto the Mercedes CAN bus.
- A system that starts the engine or changes drivetrain behavior.
- A claim that every desirable Mercedes signal is accessible.
- A generalized fleet-management cloud.
- A redesign into separate “chassis” and “house” applications.
- Permission for the LLM to make free-form control decisions.
- Permission to hide simulation state in public demonstrations.

---

## 6. Proposed architecture

```text
House telemetry                         Chassis telemetry
┌──────────────────────────┐            ┌────────────────────────────┐
│ HouseTelemetryProvider   │            │ ChassisTelemetryProvider   │
│                          │            │                            │
│ Renogy Shunt             │            │ SimChassisSource           │
│ DCC50S                    │            │ ReplayChassisSource        │
│ Inverter                  │            │ LiveChassisSource          │
│ Climate / appliances     │            │   transport TBD            │
│ Network loads            │            │   read-only initially      │
└─────────────┬────────────┘            └──────────────┬─────────────┘
              │                                        │
              └──────────────────┬─────────────────────┘
                                 ▼
                    ┌────────────────────────┐
                    │ VanStateFusion         │
                    │                        │
                    │ normalized signals     │
                    │ freshness/confidence   │
                    │ context classification │
                    │ cross-system findings  │
                    └────────────┬───────────┘
                                 ▼
                    ┌────────────────────────┐
                    │ Guardian Engine        │
                    │                        │
                    │ deterministic rules    │
                    │ forecasts              │
                    │ policy evaluation      │
                    │ action eligibility     │
                    │ verification           │
                    └───────┬────────┬───────┘
                            │        │
                    proposal│        │evidence
                            ▼        ▼
                  ┌──────────────┐  ┌──────────────────┐
                  │ Action Queue │  │ Local AI         │
                  │              │  │                  │
                  │ sim adapters │  │ Qwen explanation │
                  │ future house │  │ local Whisper    │
                  │ adapters     │  │ voice response   │
                  └──────┬───────┘  └────────┬─────────┘
                         │                   │
                         └─────────┬─────────┘
                                   ▼
                           Dashboard + Audit
```

### 6.1 New interfaces

Suggested conceptual interfaces:

```text
HouseTelemetryProvider
ChassisTelemetryProvider
VanStateFusionService
SignalQualityService
ContextClassificationService
GuardianPolicyService
GuardianDecisionService
ActionEligibilityService
ActionExecutionService
ActionVerificationService
DecisionAuditService
TrendAnalysisService
```

Existing services should be reused where possible:

```text
TelemetrySource
PowerCalculationService
AnomalyDetectionService
InsightService
LocalInferenceProvider
SpeechRecognitionProvider
SpeechSynthesisProvider
AuditService
RuntimeTelemetryProvider
```

### 6.2 Source identity

Every normalized reading must retain:

- source domain: `house | chassis | location | user | derived`
- source adapter
- metric name
- value and unit
- timestamp
- freshness
- confidence
- `simulated | replay | live`
- verification status
- optional raw identifier
- optional reason when unavailable

Derived conclusions must retain links to their supporting readings.

---

## 7. Chassis telemetry research contract

Claude Code is currently researching Mercedes-side access. That research should produce a **truth table**, not immediate integration code.

### 7.1 Required research output

Create `CHASSIS_RESEARCH.md` with one row per candidate signal:

| Signal | Operational value | Standard OBD-II | Mercedes-specific | Transport | Read-only confirmed | Update rate | Confidence | Source | Decision |
|---|---|---:|---:|---|---:|---:|---|---|---|

Tag every claim:

- `[VERIFIED-VEHICLE]` — observed on this specific van.
- `[VERIFIED-DOC]` — supported by an authoritative document for the exact platform.
- `[VERIFIED-EXTERNAL]` — supported by a credible external source but not yet tested.
- `[UNVERIFIED]` — plausible only; no implementation work allowed.
- `[UNAVAILABLE]` — tested and not accessible through the selected path.

### 7.2 Candidate signals to investigate

These are research targets, not promised capabilities:

- Ignition state
- Engine-running state
- Vehicle speed
- Parked / moving state
- Chassis-system voltage
- Charging-system or alternator status
- Engine RPM
- Fuel level
- DEF level
- Coolant temperature
- Intake or ambient temperature
- Odometer
- Trip distance
- Engine hours
- Diagnostic trouble codes
- Door-open state
- Tire-pressure data
- Gear / park state
- Brake state
- Key presence
- GPS, heading, speed, and elevation from an independent receiver

### 7.3 Hard safety constraint

The initial chassis adapter must be passive or read-only.

No Mercedes command, write PID, UDS routine, coding operation, ECU reset, CAN injection, or actuation path belongs in vNext.

---

## 8. Unified `VanState`

Create a typed normalized state that combines the latest valid values across domains.

Illustrative shape:

```json
{
  "timestamp": "2026-07-27T16:07:12-07:00",
  "context": {
    "operating_mode": "Camp",
    "vehicle_motion": "parked",
    "ignition": "off",
    "occupancy": "unknown",
    "location_source": "usb_gps",
    "overall_confidence": "high"
  },
  "chassis": {
    "engine_running": false,
    "vehicle_speed_mph": 0,
    "chassis_voltage_v": 12.7,
    "fuel_pct": null,
    "def_pct": null,
    "dtc_count": null
  },
  "house": {
    "soc_pct": 85,
    "battery_voltage_v": 13.32,
    "battery_current_a": 9.4,
    "solar_w": 181,
    "alternator_input_w": 0,
    "house_load_w": 55,
    "inverter_w": 0
  },
  "quality": {
    "stale_signals": [],
    "conflicts": [],
    "unavailable_signals": ["fuel_pct", "def_pct", "dtc_count"]
  }
}
```

Null values must remain null. The local model must not fill them.

---

## 9. Cross-system findings

Create deterministic findings that require both chassis and house context.

### 9.1 Charging-path anomaly

**Condition**

- Engine is running or vehicle is moving.
- Chassis voltage is within the configured expected range.
- Alternator/DC-to-DC charging is expected.
- House alternator input remains below a configured minimum for a sustained window.
- House battery is not near a charge state that would legitimately suppress charging.

**Finding**

> Mercedes electrical state appears active, but no meaningful alternator energy is reaching the house system.

Do not identify a failed component without further evidence.

Possible classifications:

- chassis source unavailable
- charging path unavailable
- DCC50S input absent
- house battery refusing charge
- sensor disagreement
- insufficient evidence

### 9.2 Arrival-state cleanup

**Condition**

- Motion changes from moving to parked.
- Ignition changes from on to off.
- Drive-mode loads remain active.
- Operating mode changes or should change to Camp.

**Response**

- Recalculate overnight reserve.
- Identify travel-only or nonessential loads.
- Propose or perform eligible shutdowns.
- Create an arrival summary.

### 9.3 Departure readiness

Produce a local checklist from available signals:

- chassis voltage
- fuel and DEF, if available
- active DTCs, if available
- house SOC
- refrigeration state
- shore disconnected
- inverter state
- climate state
- network state
- sensor freshness

Unknown conditions must appear as **not monitored**, not PASS.

### 9.4 Long-term charging degradation

Compare like-for-like driving windows and look for a sustained decline in house charging performance after normalizing for:

- house SOC
- controller temperature
- trip duration
- engine-running time
- electrical load
- ambient conditions, when available

The deterministic service identifies the trend. The model explains it.

### 9.5 Sensor-confidence interlock

When required supporting data is stale, contradictory, implausible, or missing:

> **Autonomous action withheld — insufficient telemetry confidence.**

This is a successful Guardian outcome, not an error state.

---

## 10. Guardian autonomy model

### 10.1 User-selectable ceiling

Use a visible autonomy ladder:

| Level | Name | Behavior |
|---:|---|---|
| 0 | Observe | Monitor, detect, and audit only |
| 1 | Advise | Explain risk and recommend action |
| 2 | Ask | Prepare an eligible action and require confirmation |
| 3 | Protect | Execute preauthorized, reversible, noncritical actions |
| 4 | Emergency | Execute only explicit deterministic emergency interlocks |

The active level is a maximum permission, not a promise that action will occur.

### 10.2 Action classes

#### Class A — observe only

Examples:

- Mercedes/chassis state
- diagnostic codes
- charging-path classification
- trend analysis
- sensor-quality findings

#### Class B — recommend

Examples:

- inspect the charging path
- connect shore power
- reduce discretionary load
- change operating mode
- seek qualified service

#### Class C — ask before acting

Initially simulation-only:

- enable or disable inverter
- suspend Starlink
- change climate setpoint
- disable a nonessential house load
- transition Camp / Sleep / Storage mode

#### Class D — preauthorized protective action

Initially simulation-only and reversible:

- suspend Starlink when overnight reserve is threatened
- disable an unused inverter
- stop a simulated cooktop when a deterministic electrical envelope is violated
- shed configured nonessential loads
- restore a prior state after recovery when policy permits

#### Prohibited

- starting or stopping the engine
- altering vehicle drivetrain state
- writing to Mercedes ECUs
- bypassing a BMS
- changing manufacturer protection thresholds
- operating from low-confidence telemetry
- allowing the LLM to create a new action
- allowing an explanation failure to block a deterministic safety action

---

## 11. Guardian decision contract

Every decision must produce a structured record before any action is proposed.

```json
{
  "decision_id": "guardian-...",
  "timestamp": "...",
  "status": "proposed",
  "risk": {
    "type": "overnight_reserve_violation",
    "severity": "warning",
    "current_value": 13,
    "threshold": 20,
    "unit": "soc_pct_at_sunrise"
  },
  "evidence": [],
  "confidence": "high",
  "policy": {
    "operating_mode": "Camp",
    "autonomy_level": 3,
    "matched_rule": "camp.reserve.protect"
  },
  "selected_action": {
    "action": "suspend_starlink",
    "reversible": true,
    "preauthorized": true,
    "estimated_saving_w": 24
  },
  "alternatives_considered": [],
  "requires_confirmation": false,
  "simulated": true
}
```

After execution, append:

- command accepted or rejected
- adapter that handled it
- before state
- after state
- verification window
- recovery confirmed: yes/no/unknown
- rollback performed: yes/no
- explanation source
- complete audit references

---

## 12. Deterministic safety boundary

The Guardian engine, not Qwen, owns:

- thresholds
- arithmetic
- forecasts
- sensor validation
- action eligibility
- policy matching
- action priority
- hysteresis
- cooldown periods
- execution
- verification
- rollback criteria
- fail-safe behavior

The local model may:

- interpret a user question
- select approved read-only tools
- summarize a structured decision
- explain evidence and tradeoffs
- produce a spoken report
- answer “Why did you do that?”
- correct a false premise using the current audited snapshot

The local model may not:

- invent chassis or house state
- calculate an authoritative electrical limit
- select an action not supplied by the policy engine
- override an ineligible action
- lower a confidence requirement
- claim an action happened before verification
- write directly to any hardware adapter

---

## 13. Guardian dashboard changes

The default dashboard should continue to fit on one screen.

### 13.1 Guardian strip

Use the open area in `Ask VanGuard` before a conversation begins.

Normal state:

```text
GUARDIAN    ARMED · CAMP POLICY · LEVEL 2 ASK

Last patrol       4:03:50 PM
Next patrol       2m 41s
Current risk      None
Telemetry         43 fresh · 0 conflicts
Allowed actions   Recommend · prepare reversible house actions
```

Active event:

```text
DETECTED → VERIFIED → POLICY MATCHED → ACTIONED → RECOVERY CONFIRMED
```

### 13.2 Distinguish timestamps

Clearly label:

- `LIVE NOW`
- `LAST PATROL`
- `LAST DECISION`
- `LAST VERIFIED ACTION`

Avoid making a prior patrol report look inconsistent with current live readings.

### 13.3 Insight hierarchy

Split the existing tile into:

1. **Current interpretation**
2. **Last Guardian patrol**
3. **Active decision or recommendation**
4. **Explain / What changed? / Read aloud**
5. **Evidence**

Avoid duplicate paragraphs that restate the same power flow.

### 13.4 Chassis presence without a second dashboard

Add a compact chassis/context region, not a full gauge cluster:

```text
CHASSIS
Parked · ignition off · 0 mph
12.7 V chassis · DTC unavailable
Last update 2s ago · read-only
```

The main panel should emphasize cross-system findings rather than raw Mercedes values.

### 13.5 Public-demo disclosure

Use:

> **SIMULATED VAN · REAL LOCAL AI**

Do not remove simulation disclosure from a publicly shared recording.

---

## 14. New deterministic demo scenarios

All scenarios must be seeded and reproducible.

### 14.1 `arrival_cleanup`

- Vehicle transitions from driving to parked.
- Ignition turns off.
- Starlink remains on.
- Inverter remains idle.
- Camp reserve would be marginal overnight.

Expected result:

- VanGuard changes context to Camp.
- It identifies two travel/nonessential loads.
- It proposes or performs the actions allowed by the selected autonomy level.
- Forecast updates.
- Decision is audited.

### 14.2 `charging_path_fault`

- Engine running.
- Vehicle moving.
- Chassis voltage normal.
- House alternator input remains 0 W.
- House SOC falls under load.

Expected result:

- Charging-path anomaly.
- No unsupported claim that the alternator itself has failed.
- Conservative Drive policy.
- Optional shedding of permitted house loads if reserve is threatened.

### 14.3 `overnight_guardian`

- SOC low enough that current loads predict sunrise SOC below Camp reserve.
- Solar is zero until morning.
- Starlink and inverter idle are active.

Expected result:

- Before forecast shown.
- Guardian selects lowest-impact reversible actions.
- Load decreases.
- After forecast shown.
- Recovery confirmed.

### 14.4 `voltage_sag_protect`

- Simulated cooktop starts.
- Battery voltage sags beyond a configured envelope for a sustained window.
- Current draw is high.

Expected result:

- Deterministic protective rule stops the simulated cooktop or inverter.
- Voltage recovery is measured.
- Qwen explains the event after the action.

### 14.5 `sensor_conflict_withhold`

- Chassis state says driving.
- Speed signal is stale.
- Battery current and power direction disagree.
- Temperature jumps implausibly.

Expected result:

- Action withheld.
- Confidence downgraded.
- User told which signals must recover.

### 14.6 `charging_degradation_replay`

- Replay several comparable trips.
- Charging rate falls over time.

Expected result:

- Trend service identifies the decline.
- Local model summarizes the evidence without naming an unproven failed part.

---

## 15. vNext Story mode

Create a new presenter-paced Story sequence:

1. Show Starlink connected while local AI remains on the NPU.
2. Display **SIMULATED VAN · REAL LOCAL AI**.
3. Begin a drive with normal chassis and alternator charging state.
4. Introduce a charging-path fault: chassis healthy, house charging absent.
5. Guardian detects and verifies the cross-system mismatch.
6. User asks by voice: “Why isn’t my house battery charging?”
7. Qwen explains the deterministic finding and evidence.
8. Transition to arrival and overnight reserve risk.
9. Guardian selects permitted house-load actions.
10. Power flow and sunrise forecast improve.
11. User asks: “Why did you turn those off?”
12. Open the audit showing before state, rule, action, after state, NPU inference, and zero cloud model calls.
13. End:

> **Monitor. Understand. Protect. Even beyond the reach of the cloud.**

Actions in Story mode must invoke the same real application paths used outside Story mode.

---

## 16. Implementation tracks

Run two tracks in parallel and converge only after each passes its own gate.

# Track G — Guardian

### G0 — Decision schema and policy contract

Build:

- autonomy-level configuration
- action classes
- policy schema
- Guardian decision record
- evidence references
- confirmation requirements
- action-verification record

Gate:

- no action can execute without a valid deterministic decision record
- no LLM-generated action name can enter the queue

### G1 — Guardian simulator

Build:

- simulated eligible actions
- preauthorization rules
- action queue integration
- verification windows
- rollback behavior
- decision audit
- UI decision timeline

Gate:

- seeded scenarios replay identically
- before/after state and forecast reconcile
- every action remains explicitly simulated

### G2 — Confidence and withholding

Build:

- freshness rules
- conflict rules
- plausibility checks
- confidence aggregation
- “action withheld” decisions

Gate:

- required stale or conflicting signals always block applicable actions

### G3 — Guardian UX and voice explanation

Build:

- Guardian strip
- autonomy selector
- active decision panel
- “Why did you do that?” response
- local read-aloud report
- audit deep link

Gate:

- dashboard remains one screen at target viewport
- explanation failure cannot prevent decision logging or deterministic action

# Track C — Chassis

### C0 — Mercedes truth table

Deliver:

- `CHASSIS_RESEARCH.md`
- exact vehicle/platform assumptions
- candidate interfaces
- signal availability table
- read-only safety analysis
- recommended first adapter
- cost and wiring requirements
- explicit unavailable and unverified list

Gate:

- no live code against an `[UNVERIFIED]` signal
- no write-capable interface selected for vNext

### C1 — Chassis contract and simulator

Build:

- `ChassisTelemetryProvider`
- typed normalized metrics
- `SimChassisSource`
- `ReplayChassisSource`
- seeded driving and fault scenarios
- source/freshness/confidence metadata

Gate:

- the dashboard and Guardian logic work before live hardware exists

### C2 — Passive live handshake

Goal:

> Prove one real, read-only chassis value arrives from the specific van on the Surface Pro.

Preferred first values:

- vehicle speed or engine-running state
- chassis voltage
- engine RPM

Gate:

- observed value agrees with an independent vehicle display or trusted diagnostic tool
- adapter does not transmit control commands
- disconnect/failure leaves the house system operational

### C3 — Live source and capture

Build:

- `LiveChassisSource`
- bounded polling cadence
- adapter health
- reconnect behavior
- raw capture to `.jsonl`
- replay corpus

Gate:

- at least one complete real trip captured
- replay reproduces the same normalized events
- stale/disconnected states are correctly surfaced

# Convergence — Whole-Van Intelligence

### W0 — VanState fusion

Build:

- normalized whole-van snapshot
- context classification
- cross-system evidence links
- unified freshness/confidence

### W1 — Cross-system rules

Build:

- charging-path anomaly
- arrival cleanup
- departure readiness
- trend analysis
- sensor-confidence interlock

### W2 — Integrated demo

Build:

- new Story mode
- dashboard polish
- voice questions
- audit sequence
- public simulation disclosure

### W3 — Pilot hardening

Build:

- configurable vehicle profile
- configurable house-system profile
- adapter capability manifest
- installer diagnostics
- exportable support bundle
- redacted replay package

---

## 17. Adapter capability manifest

Every adapter should declare capabilities rather than forcing the core to infer them.

Example:

```yaml
adapter:
  id: mercedes_obd_readonly
  domain: chassis
  mode: live
  read_only: true
  commands_supported: []
  metrics:
    engine_running:
      available: true
      confidence: verified_vehicle
      cadence_s: 2
    vehicle_speed_mph:
      available: true
      confidence: verified_vehicle
      cadence_s: 1
    fuel_pct:
      available: false
      reason: not_verified
```

House action adapters should separately declare:

- action name
- simulated/live
- reversible
- confirmation required
- minimum confidence
- minimum autonomy level
- verification metric
- timeout
- rollback support

---

## 18. Integrator-oriented configuration

Do not build a full installer product in vNext, but avoid choices that prevent one.

Move these into profiles:

### Vehicle profile

- make/model/year/chassis
- available chassis adapter
- metric mappings
- expected signal ranges
- ignition/motion interpretation
- charging expectations

### House profile

- battery chemistry and capacity
- charge architecture
- inverter characteristics
- solar limits
- appliance loads
- critical/nonessential classification
- controllable actions
- verification metrics

### Policy profile

- Camp/Sleep/Drive/Storage/Emergency reserves
- autonomy ceiling
- preauthorized actions
- quiet hours
- comfort limits
- recovery rules
- notification behavior

Potential future profiles:

- Renogy + Mercedes Sprinter
- Victron + Mercedes Sprinter
- Transit-based builds
- ProMaster-based builds

These are future packaging targets, not vNext deliverables.

---

## 19. Verification plan

Add deterministic checks for:

### Guardian

1. No decision without evidence.
2. No action without policy eligibility.
3. Autonomy ceiling enforced.
4. Confirmation requirement enforced.
5. Prohibited action rejected.
6. Stale required signal blocks action.
7. Conflicting signal blocks action.
8. Lowest-impact eligible action selected.
9. Cooldown prevents action oscillation.
10. Hysteresis prevents threshold chatter.
11. Action result verified.
12. Failed verification produces warning and no false success.
13. Rollback behavior works where supported.
14. Every state transition is audited.
15. LLM unavailable does not disable Guardian.
16. LLM cannot create or alter actions.
17. Explanation matches the structured decision.

### Chassis

18. Source identity preserved.
19. Sim/replay/live stamps preserved.
20. Unsupported metrics remain null.
21. Disconnect produces stale/unavailable state.
22. Polling failure does not block house telemetry.
23. Chassis adapter performs no writes.
24. Normalized units are correct.
25. Replay is deterministic.

### Fusion

26. Engine-on plus no house charge triggers only after the sustained window.
27. High house SOC suppresses a false charging-path warning where configured.
28. Arrival transition fires once.
29. Departure readiness labels unknown items as not monitored.
30. Trend comparison uses like-for-like windows.
31. Low-confidence data withholds action.
32. Before/after forecast reconciles with load changes.
33. Current readings and prior patrol timestamps remain distinguishable.

### UI and public honesty

34. One-screen target preserved.
35. Simulation disclosure visible in public-demo mode.
36. NPU displayed only when runtime-confirmed.
37. Chassis is labeled read-only.
38. Audit exposes evidence, policy, action, and result.
39. Accessibility and reduced-motion checks pass.

---

## 20. Failure gates

Stop or narrow the build when any of these becomes true:

- Mercedes signals required for a scenario cannot be verified.
- The selected adapter cannot be operated read-only.
- The adapter destabilizes the vehicle network or conflicts with existing diagnostics.
- A signal’s cadence or reliability is too poor for the intended decision.
- A proposed action cannot be independently verified.
- Action oscillation cannot be prevented with deterministic hysteresis/cooldown.
- The one-screen dashboard becomes unreadable.
- The public demo cannot clearly distinguish simulated van telemetry from real local AI.
- A feature requires the LLM to perform safety arithmetic.
- A feature requires cloud connectivity at runtime.

A failed gate should produce a documented narrower scope, not a fabricated workaround.

---

## 21. Documentation changes

Update:

- `README.md` — vNext current state, Guardian disclaimer, chassis read-only status.
- `SYSTEM.md` — new providers, fusion service, Guardian engine, decision records.
- `PLAN.md` — verified chassis truth table, milestone status, hardware path.
- `BUILD_LOG.md` — `What I tried / What broke / What fixed it / Verification / Next`.
- `BENCHMARKS.md` — only if Guardian workload changes NPU residency or system draw.
- `SHOT_LIST.md` — new cross-system and corrective-action video.
- `CHASSIS_RESEARCH.md` — authoritative chassis investigation.
- `GUARDIAN_POLICY.md` — action classes, autonomy levels, deterministic rules.
- `ADAPTERS.md` — capability manifests and integration boundaries.

---

## 22. What not to say

Do not say:

- “VanGuard controls the Mercedes.”
- “VanGuard prevents electrical failures.”
- “The AI decides what is safe.”
- “The NPU runs the safety system.”
- “All vehicle telemetry is available through OBD-II.”
- “No data can ever leave the device.”
- “The app replaces the BMS or Mercedes diagnostics.”
- “VanGuard repaired the charging system.”
- “The alternator failed,” unless independent evidence proves it.
- “The action succeeded,” until post-action verification confirms it.
- “Live van data,” when the source is simulated or replayed.

Preferred language:

- “Read-only chassis telemetry.”
- “Deterministic policy engine.”
- “Local model explanation.”
- “Predicted reserve violation.”
- “Charging-path anomaly.”
- “Preauthorized reversible house action.”
- “Action withheld because telemetry confidence was insufficient.”
- “Simulated van telemetry; real local inference.”
- “Not a certified safety system.”

---

## 23. Definition of done

vNext is complete when:

1. The app displays one normalized van state spanning house and chassis domains.
2. Chassis data is available through sim and replay even if live research remains incomplete.
3. At least one real read-only chassis value has been proven on the specific van, or the live milestone is explicitly deferred with the reason documented.
4. Guardian implements the full detect/verify/decide/act-or-ask/confirm/explain loop.
5. All Guardian decisions are deterministic and evidence-backed.
6. The local model never owns electrical arithmetic or action eligibility.
7. At least three cross-system findings work.
8. At least two simulated corrective actions are preauthorized and reversible.
9. Low-confidence telemetry visibly withholds action.
10. Every decision and action has a complete audit trail.
11. The dashboard remains one-screen and tablet-friendly.
12. The public Story mode visibly discloses simulated van telemetry.
13. Voice can ask why a decision occurred and receive a grounded local explanation.
14. The system continues to function without the model.
15. The system continues to function without the chassis adapter.
16. All deterministic verification suites pass.
17. Documentation states exactly what is live, simulated, replayed, measured, inferred, unavailable, and unverified.
18. The final demo communicates:

> **A local device can understand disconnected systems, predict trouble, apply policy, take narrowly authorized corrective action, verify the result, and explain everything without sending operational data to a cloud model.**

---

## 24. Recommended first build sequence

1. Approve this proposal or mark sections to cut.
2. Complete `CHASSIS_RESEARCH.md`; do not start live integration from assumptions.
3. Define the Guardian decision and policy schemas.
4. Build `SimChassisSource` and whole-van scenarios.
5. Build Guardian action eligibility and simulated corrective actions.
6. Add confidence-based action withholding.
7. Add the Guardian strip and decision timeline.
8. Add cross-system findings over simulated chassis data.
9. Prove one passive real Mercedes signal.
10. Capture a real trip and feed it through replay.
11. Re-shoot Story mode with the integrated whole-van narrative.
12. Decide whether vNext remains a demonstration or becomes an integrator pilot.

---

## 25. Product checkpoint after vNext

After the vNext demo, evaluate a small integrator discovery effort.

Evidence worth collecting:

- Do builders want one local intelligence layer across chassis and house systems?
- Which electrical ecosystems matter first?
- Which signals and corrective actions create real service value?
- Would installers pay for configuration, diagnostics, or a white-label dashboard?
- Is the strongest wedge owner experience, service diagnostics, energy management, or privacy?
- What parts require certification, warranty review, or vendor partnership?
- Can a read-only version deliver enough value before real control exists?

Do not build a multi-vendor platform until at least one integrator validates the need and identifies a concrete first deployment.
