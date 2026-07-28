# VanGuard — Filming Run Sheet

*Keep this nearby while recording. Everything on screen is live; only the
fault timing is scripted.*

## Launch (one command, ~2 min to ready)

```powershell
cd C:\vibe\vangaurd
.\scripts\demo.ps1 -Scenario driveway -NPU -Presentation -Kiosk
```

- `-NPU` — model genuinely serves on the NPU (rail: LOCAL AI: NPU · Qwen3-4B)
- `-Presentation` — badge reads SIMULATED VAN · REAL LOCAL AI; Starlink auto-online
- `-Kiosk` — fullscreen Edge, zero chrome (**Alt+F4** exits)
- Stop everything: `.\scripts\demo.ps1 -Stop`

## Option A — 🎬 Story mode (guided, ~3–4 min, presenter-paced)

Click **🎬 Story** in the rail (or open `http://127.0.0.1:8000/#story`).
Next/◀ are pinned bottom-right and never move. 15 steps:

| # | Spotlight | What happens / say-over |
|---|---|---|
| 1 | Rail | the promise: local model, NPU, data stays on device |
| 2 | Battery | coulomb-counted battery, live runtime math |
| 3 | Power Flow | watts reconcile; switches are live |
| 4 | Climate+Network | comfort + Starlink that the battery feels |
| 5 | Insight | rules verdict · model words · signed patrols |
| 6 | Outlook | sunrise forecast, assumptions disclosed |
| 7 | Trip/Chassis | read-only Mercedes data, fused |
| 8 | Ask | **auto-asks** "what's charging the battery?" (NPU answers ~10s) |
| 9 | Ask | **auto-asks** the cooktop question (calculator verdict, instant) |
| 10 | Chassis | **starts the drive** — engine, alternator, Starlink on |
| 11 | Alerts | *wait here ~40s*: fault at 0:30, alert appears |
| 12 | Guardian | *wait ~30s more*: DETECTED→…→ACTED (sheds Starlink) |
| 13 | Ask | **auto-asks** "why did you turn Starlink off?" |
| 14 | Diagnostics | the audit: N tool calls · 0 external |
| 15 | — | **parks + resets take** · "Monitor. Understand. Protect." |

Steps 11–12 are the only ones where you *wait for reality* — narrate over it.

## Option B — the 70-second cut (recommended for LinkedIn)

One autonomous event, one visibly local voice exchange, one receipt.

| Clock | Beat | Say-over |
|---|---|---|
| 0:00–0:07 | Establish the dashboard | "This Surface Pro is monitoring a simulated Sprinter — but the voice, the model, the NPU inference, and the decisions are real." |
| 0:07–0:15 | Point at the rail | "Local Qwen on the NPU, voice stays local, no cloud model — even with Starlink connected." |
| 0:15–0:20 | Press **▶ Drive** | "Let's go for a drive — and stage a failure." |
| 0:20–0:45 | Fault at 0:30 → alert fires | "The charging path just failed. Mercedes sees nothing wrong — only the fused view catches it." |
| 0:45–1:00 | **Guardian event card** takes over the strip: DETECTED → VERIFIED → POLICY MATCHED → ACTIONED → RECOVERY CONFIRMED, load reduced, forecast improved, decision receipt underneath | "The Guardian can't fix a charging path, so it does the one legitimate thing: sheds the loads it can no longer afford. Detected, verified, actioned, recovery confirmed — every stage logged." |
| 1:00–1:15 | Tap the amber **why did you do that?** chip (it appears by itself after the action) — or ask it by voice via 🎤 | the answer is read back from the Guardian log, with the local pipeline banner over the reply |
| 1:15–1:20 | Footer + receipt line | "Telemetry, voice, reasoning, decisions — processed on this device. Zero external calls." |

**The offline beat (optional, +8s):** switch Network to **Off** — the rail
flips to **NO UPLINK · LOCAL AI ACTIVE**. Ask the voice question *then*.
Local AI isn't a fallback for bad connectivity; it just doesn't need the
internet. (In the drive take Guardian already suspends Starlink for you —
same message, cleaner narrative.)

## Option C — the 90-second Drive take (freeform)

| Clock | What the camera sees |
|---|---|
| 0:00 | Press **▶ Drive** (Trip tile). Engine starts, ~500W alternator, Starlink on |
| 0:30 | Scripted fault: house charging stops; chassis stays healthy (14.1V, DTC 0) |
| ~0:40 | ⚠ Alert: "moving with no alternator input"; Insight names it |
| ~0:55–1:10 | **Guardian acts**: DETECTED → VERIFIED → DECIDED ("can't repair; conserving") → ACTED: Suspend Starlink (~24W) |
| ~1:15–1:30 | CONFIRMED: battery net power before → after; sunrise forecast before → after |

Then (optional): hold 🎤 and ask **"Why did you turn Starlink off?"** — the
NPU answers from the Guardian log.

Press **⏸ Park** = full take reset: van back home, trip zeroed, fault
cleared, Guardian cooldowns wiped, autonomy re-armed to **Protect**.
Repeat as many takes as you need — identical every time.

Contrast shot: set autonomy to **Advise** before a take → Guardian
recommends the same plan but touches nothing.

## Dictation (tablet-first, no keyboard needed)

**Tap 🎤** — the backend synthesizes Win+H, so Windows Fluid Dictation
(Copilot+ on-device, live punctuation cleanup) opens straight into the
ask box. Speak, tap the flyout's mic (or 🎤 again) to stop, tap **Ask**.
One-time setup: in the voice-typing flyout's ⚙, enable "fluid dictation".

Fallback: if the dictate endpoint is unavailable the 🎤 becomes a local
Whisper recorder (whisper-small, click to start / click to send).

Both paths stay fully on-device. Avoided on purpose: browser Web Speech
API — it ships audio to a cloud service.

## Good voice/typed questions (all answered on-device)

The four chips on screen: cooktop 25 min? · power until sunrise? ·
anything abnormal? · ready to depart?  After any Guardian action an amber
**why did you do that?** chip appears on its own for ~15 minutes.

Also good spoken: "What is charging the battery right now?" *(NPU, real
numbers)* · "What should we do nearby?" *(offline POIs)* · "Why did you
turn Starlink off?"

Voice questions get the full pipeline on screen: **● LISTENING LOCALLY**
while dictating, `VOICE → WINDOWS ON-DEVICE DICTATION → QWEN3-4B ON NPU →
VERIFIED TOOLS` while thinking, and a green *"✓ processed entirely on this
device · N local tool calls · 0 external calls"* receipt under the answer.

## Numbers you can quote (measured, BENCHMARKS.md)

- NPU: 27 tok/s @ 18.4 W · GPU: 37 tok/s · Whisper STT local
- ≈ 0.02 Wh per question → ~190,000 questions per battery charge
- One cooktop dinner ≈ 35,000 questions

## If something looks off

- Patrol text ≠ live tiles → hit **Check now** (patrol is up to 5 min old)
- ⚠ STALE chip → poller died: `demo.ps1 -Stop` then relaunch
- Model feels slow → NPU is ~727ms to first token (authentic); drop `-NPU`
  for GPU snappiness (rail then honestly says GPU)
- Fresh stage between scenes: `demo.ps1 -Stop` + relaunch (~2 min)
