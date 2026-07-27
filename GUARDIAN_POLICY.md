# Guardian Policy

*The deterministic autonomy contract (P8/P9). The language model is never
in this loop — it explains decisions afterward from the logged record.*

## Autonomy ladder (user-selected ceiling; a maximum, not a promise)

| Level | Behavior |
|---|---|
| Observe | monitor, detect, audit only |
| Advise | explain risk and recommend |
| Ask | prepare eligible action, require confirmation |
| Protect *(default)* | execute preauthorized reversible actions; confirm-class still asks |
| Emergency | additionally execute the hard interlocks |

Autonomy is **sim-only**: on a `live` source Guardian downgrades itself to
recommendations regardless of level (phase 2 adds narrowly scoped adapters
behind per-action authorization).

## Action classes

- **auto** (Protect+): suspend Starlink dish · disable idle inverter ·
  switch operating mode to Camp. Reversible, non-comfort, house-side only.
- **interlock** (Protect+, single-detection): stop cooktop on voltage sag
  (<12.0 V under >800 W AC). A demo interlock — not certified protection.
- **confirm** (always asks): climate changes; charging-source changes.
- **never** (not in the registry at all): vehicle controls, engine
  start/stop, Mercedes ECU writes, BMS/protection limits, any action on
  low-confidence telemetry, any action invented by the LLM.

## The loop

`detect → verify (hysteresis: 2 consecutive checks; interlocks and one-shot
transitions act on 1) → decide (policy + eligibility + cooldown) → act
(audited command queue, device=GUARDIAN) → confirm (before/after net watts
and sunrise forecast) → resolved`. Every stage is a row in
`guardian_events`; withheld/proposed/dismissed are first-class stages.

**Sensor confidence gates everything**: stale or self-contradictory battery
telemetry withholds all action and says so. This is a success state.

## Risk detectors (deterministic)

1. **Overnight reserve breach** — forecast SOC at sunrise below the active
   mode's reserve while discharging → shed Starlink + idle inverter
   (auto), recommend climate-off (confirm).
2. **Voltage-sag interlock** — battery <12.0 V under >800 W AC → stop
   cooktop immediately.
3. **Charging-path anomaly** *(fusion)* — chassis says engine running and
   chassis bus healthy, but no alternator energy reaches the house and the
   battery isn't full → advisory, no action, no component blamed
   (classifications: DC-DC path / DCC50S input / battery refusing charge /
   sensor disagreement / insufficient evidence).
4. **Arrival cleanup** *(fusion, one-shot)* — moving→parked with ignition
   off while travel loads (Starlink, idle inverter) remain → switch mode
   to Camp, shed travel loads, recalculate the overnight reserve.
5. **Withhold** — conflicting current/power or stale shunt data → no
   autonomous action until readings recover.

## Cooldowns

Per-action (2–30 min) to prevent oscillation; episodes cannot repeat while
a confirmed-but-unresolved risk persists.
