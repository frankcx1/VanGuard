# VanGuard — project instructions for Claude Code

Read `PLAN.md` before doing anything substantive. It is the authoritative plan
and it already resolves most questions you might be tempted to re-derive.

## What this is

A local, fully-offline AI monitoring and advisory system for a 2022 Mercedes
Sprinter 3500XD camper van. Telemetry from the van's power system → SQLite →
FastAPI → a dashboard and a chat interface backed by a local LLM running on the
Intel NPU of a Surface Pro. No cloud at runtime.

The original brief lives at `../Sprinter/VanGuard_Project_Brief.md`. **PLAN.md
supersedes it where they conflict** — see "Corrections" below.

## Ground rules (non-negotiable)

- **No cloud at runtime.** Downloads and package installs during the build are
  fine. Once running, the system must work with zero connectivity.
- **Read only, phase 1.** The AI can see everything and touch nothing. No
  actuation of chargers, inverters, or relays. Write access is phase 2 and is
  gated behind explicit human confirmation.
- **Log every tool invocation** to the `tool_audit` table.
- **Greenfield.** Do not import or reference any prior Microsoft-era code.
- **Document as you go.** Append to `BUILD_LOG.md`, failures included — the log
  is part of the deliverable, not an afterthought.

## Corrections to the brief — do not re-derive these

The brief was written before the hardware was verified. Three things in it are
wrong and were corrected in PLAN.md:

1. **There is no Victron hardware and no Cerbo GX.** The brief's entire
   telemetry section (Modbus TCP on port 502, Victron register lists) does not
   apply. The van is an all-Renogy "Rego 440" stack.
2. **The battery has no communication port.** It is Renogy *Core Series*, and
   Core vs Smart Lithium is precisely the comms distinction — no RS485, not
   retrofittable.
3. **SOC is only reachable over Bluetooth LE**, from the Shunt 300. There is no
   wired path to it. This is the project's largest risk.

Do not buy or plan around a Renogy Communication Hub. The van has exactly one
RS485 device (the DCC50S), which makes the hub a pass-through. A BT-2 dongle is
the correct purchase.

## Source of truth for hardware

`../Sprinter/` — OGA invoices, Renogy manuals, walkthrough transcripts, wiring
plan. The invoice at `Sprinter/2024 05 31 OGA Sale and Invoices - OCR text.txt`
lines 55-90 is the definitive component list.

**Never guess a register map or a device spec.** Check it against those docs or
against a cited external source, and tag claims `[verified]`,
`[verified-external]`, or `[UNVERIFIED]` the way PLAN.md does. Frank
specifically wants inferred values marked rather than presented as fact.

## Architecture in one line

Everything sits behind a swappable `TelemetrySource` (`live` | `sim` | `replay`)
selected in `config/devices.yaml`. This is the hinge of the whole project: it
lets the dashboard, tool loop, and NPU benchmarks be built and filmed before any
van hardware exists.

**Integrity guardrail:** when the source is not `live`, the dashboard must show
a persistent `SIM` badge and the API must stamp `"simulated": true` on every
payload. This is not optional — the project is being filmed, and a screenshot
must never be able to misrepresent simulated data as live van data.

## Where things stand

- **M0 complete** — plan written, repo initialized. Two commits.
- **Next: P1** — the simulator and storage layer. See PLAN.md §8, Track P.
- Track P requires no van hardware and runs entirely on the Surface Pro.
- Track M (live BLE) is gated on M1, which is gated on a BT-2 dongle and van
  access.

**First run on the Surface Pro?** Execute `SETUP_PRO.md` top to bottom before
anything else. It is a runbook written for you, not for a human: prerequisites,
clone, git identity, and the two open platform questions (RAM SKU, and whether
OpenVINO enumerates the NPU), each with a success criterion and a failure
branch. Record results in `BUILD_LOG.md` as you go.

Note the warning at the top of it about interactive commands — `gh auth login`
needs a human at a browser and will hang if run in the foreground. Run it in the
background and hand Frank the one-time code.

## Working style

- Build runnable things rather than describing them. Verify each piece actually
  works before moving on.
- Be decisive, but transparent about what is verified versus inferred.
- Prefer local, offline, self-hosted approaches — that is the entire point here.
- Keep tool outputs compact. The NPU uses static shapes with a ~2–4k context
  limit, so tools must return numbers and units, not prose.
