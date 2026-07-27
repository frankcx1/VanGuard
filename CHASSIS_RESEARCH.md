# Chassis Telemetry Research — 2022 Sprinter 3500XD (VS30/907)

*Truth table per SUGGEST.md §7. Nothing here is integration code; no work
may proceed against an `[UNVERIFIED]` signal. Tags:*
`[VERIFIED-VEHICLE]` observed on this van · `[VERIFIED-DOC]` authoritative
doc for the platform · `[VERIFIED-EXTERNAL]` credible source, untested ·
`[UNVERIFIED]` plausible only · `[UNAVAILABLE]` tested and inaccessible.

## Recommended first adapter

**Read-only OBD-II dongle (BLE or WiFi, e.g. OBDLink MX+ / Veepeak) +
`python-OBD` on the Surface Pro.** Rationale: the port exists on every
2022 Sprinter [VERIFIED-EXTERNAL — klavkarr port locator for 907/910];
standard-PID reads are passive request/response (no CAN writes beyond the
diagnostic query itself); the dongle unplugs cleanly; failure cannot affect
the house system. Cost ≈ $30–100. Cadence: 1–2 s per PID round-robin.

**Explicitly rejected for vNext:** any write PID, UDS routine, coding,
ECU reset, or CAN injection (SUGGEST §7.3); the Mercedes-Benz **Fleet
API / Fleet Partner API** (cloud, OAuth, commercial agreement — violates
no-cloud-at-runtime; note consumer **mbrace telematics was discontinued
2026-01-01**); passive CAN taps (deferred — more capable but demands
harness work and platform-specific DBC knowledge).

## Signal truth table

| Signal | Value to VanGuard | Path | Confidence | Decision |
|---|---|---|---|---|
| Engine running (RPM > 0) | high — fusion findings, arrival | OBD PID 0x0C | [VERIFIED-EXTERNAL] std PID | sim now, live at C2 |
| Vehicle speed | high — motion state | OBD PID 0x0D | [VERIFIED-EXTERNAL] std PID | sim now, live at C2 |
| Chassis battery voltage | high — charging-path anomaly | OBD adapter supply / PID 0x42 | [VERIFIED-EXTERNAL] | sim now, live at C2 |
| Coolant temperature | medium | OBD PID 0x05 | [VERIFIED-EXTERNAL] std PID | sim now |
| Fuel level | high — departure check, range | OBD PID 0x2F | [UNVERIFIED] — diesel Sprinters inconsistently report 0x2F; must test on this van | sim now; verify at C2 before trusting |
| DEF/AdBlue level | medium — departure check | Mercedes-proprietary UDS DID | [UNVERIFIED] — not a std PID; third-party MB scanners read it, DIDs undocumented | sim now; best-effort research later |
| Odometer | medium | OBD PID 0xA6 (newer std) or MB UDS | [UNVERIFIED] on this platform | sim now |
| DTC count / codes | high — departure check, honesty | OBD Mode 03 | [VERIFIED-EXTERNAL] std | sim now, live at C2 |
| Ignition/key state | medium | inferred from RPM + voltage profile | [UNVERIFIED] as a direct signal | derive, don't claim |
| Engine hours | low | MB UDS | [UNVERIFIED] | defer |
| Intake/ambient temp | low | OBD PID 0x0F/0x46 | [VERIFIED-EXTERNAL] | defer |
| Tire pressures | medium | MB UDS (TPMS) | [UNVERIFIED] | defer |
| Door-open / gear / brake / key presence | low-medium | MB-proprietary CAN | [UNVERIFIED] | defer; likely needs passive CAN, not OBD |
| GPS/heading/elevation | high | independent USB NMEA receiver | [VERIFIED-EXTERNAL] | separate adapter (already planned) |

## Safety analysis

OBD-II standard-PID polling is a request/response diagnostic protocol the
vehicle is designed to serve; it does not alter ECU state. Risks to manage
at C2: keep polling cadence modest (≥1 s), stop polling when the bus is
asleep (avoid keep-awake battery drain — measure), and verify the chosen
dongle does not attempt initialization writes. Gate (SUGGEST §16 C2): the
first live value must agree with the instrument cluster before anything
downstream consumes it.

## Current status

`SimChassisSource` (implemented inside the van model, source `chassis`)
emits: engine_running, ignition, speed, chassis_v, fuel_pct, def_pct,
coolant_c, odometer_mi, dtc_count — all read-only, all marked simulated by
the platform's existing stamps. Live C2 handshake is deferred until the
dongle is purchased and the van is available; nothing in the app assumes
it succeeded.
