# VanGuard — Filming Run Sheet

*Companion to `OneDrive\VanGuard\VanGuard_Scripts_ShotList.docx` (the
scripts + shot list). Keep this nearby while recording. Everything on
screen is live; only the event schedule is scripted — and Park resets it.*

## Launch (one command, ~2 min to ready)

```powershell
cd C:\vibe\vangaurd
.\scripts\demo.ps1 -Scenario driveway -NPU -Presentation -Kiosk -Take forgot_switch
```

- `-Take forgot_switch` — arms the shoot's event schedule (see clock below);
  `forgot_switch_fast` is the +12s pacing variant if the drive stretch drags
- `-NPU` — model genuinely serves on the NPU (rail: LOCAL AI: NPU · Qwen3-4B)
- `-Presentation` — badge reads SIMULATED VAN · REAL LOCAL AI
- `-Kiosk` — fullscreen Edge, zero chrome (**Alt+F4** exits)
- Stop everything: `.\scripts\demo.ps1 -Stop`

## The take: `forgot_switch` (Cut A 1:16–2:33 / all of Cut B's demo)

Pre-drive state, however long the setup runs: battery held at its ~20.2%
mark, Starlink online and steady (~24W), **inverter on and inverting —
110V live, e-bike smart chargers pulling ~90W with the pack held at 58%**,
rear A/C off, solar producing. The story: the alternator→house charge
switch was never flipped (B7 is the physical insert shot) — so the moment
we drive, the house battery drains while Mercedes sees a perfectly
healthy engine.

**Event clock, relative to the ▶ Drive press** (verified by
`scripts\verify_take.py`; consecutive takes reproduce within ~1s):

| Clock | What the screen does |
|---|---|
| 0:00 | ▶ Drive: engine on, rear A/C on (~900W, for the Doodles), Starlink + inverter + e-bike chargers already on, house charge input **0W**, chassis healthy at 14.1V |
| ~+20s | SOC crosses **20.0%** — one warning alert, whole app chrome starts the **red pulse** |
| ~+27s | Guardian **STAGE 1**: DETECTED → VERIFIED → ACTED: *Shed Starlink dish* (~24W); pulse eases to a slow amber breath |
| ~+39s | Guardian **STAGE 2**: *Shed rear A/C* (~900W) — the battery-saver exception, executed autonomously below 20% |
| ~+52s | Guardian **STAGE 3**: *Shed the 110V circuit* — inverter off, which takes the e-bike chargers with it (~120W). Everything nonessential is now dark |
| ~+53s | Amber **why did you do that?** chip appears (held until the final stage, on purpose) |
| ~+60s | RECOVERY CONFIRMED: battery net goes **positive**, forecast improves, border calm — **one calm card**, PROTECTED: fridge · freezer green and untouched the whole way |

`forgot_switch_fast`: crossing ~+12s, stages ~+19s / ~+31s / ~+43s.

**The human fix (optional beat):** tapping **🚐 Alternator** in Power Flow
is the real-life recovery — it starts/uses the engine AND flips the
forgotten seat switch, so ~500W flows into the house battery and the
node lights. Works mid-drive (house input jumps from 0W) or parked
(engine idles). Do it *after* the Guardian story plays out, if at all —
flipping it before the 20% crossing prevents the crossing. Park
re-forgets the switch for the next take.

**⏸ Park fully resets the take:** SOC back to its mark (re-pinned), A/C
off, dish back online *and warm* (no 45s re-boot between takes), inverter
back on with the e-bike pack re-pinned at 58%, Guardian episodes/cooldowns
wiped, autonomy re-armed to **Protect**, van home, trip zeroed. Shoot as
many takes as needed — the timing is identical.

**The voice beat (2:33–2:49):** after Stage 3, tap the chip — or tap 🎤 and
ask *"why did you do that?"* out loud. The answer reads back from the
Guardian log over authentic NPU time (~10s; the long cut holds the wait).
Footer receipt: local pipeline, N tool calls, **0 external calls**.

**Consistency rule (from the shot list):** Frank's mouth never outruns the
screen; no version numbers spoken unless the rail badge shows them; the
Presentation badge reads SIMULATED VAN · REAL LOCAL AI at all times.

### What the take scripts (disclosed, for the record)

Telemetry stays physically modelled (coulomb-counted battery, real OCV
curve, real loads). The take arranges: start SOC at the tuned mark, SOC
pinned until the Drive press (the clock starts at the press, not at app
launch), dish pre-warmed, A/C-on as a Drive side effect, alert thresholds
tuned so the crossing is the single warning, and a narrowed Guardian
detector set so nothing talks over the battery-saver story. BUILD_LOG has
the details.

## The tabbed view (default — the camera-friendly layout)

Four tabs, big tiles: **🚐 Van** (Battery hero, Power Flow, Climate/Network,
Chassis + Drive, Outlook — the whole take plays here) · **✨ AI** (Insight,
Ask + Guardian home, presentation-scale type) · **📋 Log** (Monitoring —
all 60 channels grouped by system with sub-tabs — plus Alerts, Diagnostics)
· **🗺️ Trip** (trip status + the area overview from offline POI data + the
on-demand ☁ cloud expert). Keys **1–4** switch tabs, **G** toggles the
classic one-screen grid (also `#grid` in the URL; the toggle is remembered).

**The cloud expert (Trip tab) and the filmed claims:** "zero calls to the
internet" stays true on camera — the expert is strictly on demand (nothing
is sent until the Search press), it's disabled without an `ANTHROPIC_API_KEY`
env var, and every use is audited as EXTERNAL and counted separately in
Diagnostics. Don't press Search during a take unless the story wants it.

While a Guardian episode is live and you're not on the AI tab, the live
block — timeline, STAGE card, approve row — **slides up as an overlay over
whatever tab is showing**, so the Guardian moment can't hide behind a tab.
The amber *why did you do that?* chip appears right on the overlay after
the final stage: one tap jumps to the AI tab and asks. "open AI tab →"
does the same without asking.

On-camera flow for the take: everything through Stage 2 plays on **Van**
(the overlay included); the voice beat is one deliberate cut to **AI**.

## Story mode (guided, presenter-paced) — Option A

Click **🎬 Story** in the rail (or `http://127.0.0.1:8000/#story`). 15
steps; with the take armed, steps 10–12 play the forgot-switch beats
(press Drive → wait ~20s for the crossing → watch the three-stage shed).
Narrate over the waits; the app's clock is deterministic, yours needn't be.

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
anything abnormal? · ready to depart?  After the Guardian's final stage an
amber **why did you do that?** chip appears on its own for ~15 minutes.

Also good spoken: "What is charging the battery right now?" *(NPU, real
numbers)* · "Why did you turn Starlink off?" · "What should we do nearby?"
*(offline POIs)*

Voice questions get the full pipeline on screen: **● LISTENING LOCALLY**
while dictating, `VOICE → WINDOWS ON-DEVICE DICTATION → QWEN3-4B ON NPU →
VERIFIED TOOLS` while thinking, and a green *"✓ processed entirely on this
device · N local tool calls · 0 external calls"* receipt under the answer.

## Numbers you can quote (measured, BENCHMARKS.md)

- NPU: 27 tok/s @ 18.4 W · GPU: 37 tok/s · Whisper STT local
- ≈ 0.02 Wh per question → ~190,000 questions per battery charge
- One cooktop dinner ≈ 35,000 questions

## If something looks off

- Red pulse not animating → Windows "animation effects" is off
  (Settings → Accessibility → Visual effects) — the CSS honors
  reduced-motion
- Battery tile not moving after Drive → check the take actually armed:
  the launcher's READY line should say `take=forgot_switch`
- Patrol text ≠ live tiles → hit **Check now** (patrol is up to 5 min old)
- ⚠ STALE chip → poller died: `demo.ps1 -Stop` then relaunch
- Buttons flip back / commands fail → shouldn't happen if READY printed
  (the launcher smoke-tests the command path and auto-restarts the API
  once); tracebacks in `sim\captures\demo\api_stderr.log` (+ `.failed`)
- Model feels slow → NPU is ~727ms to first token (authentic); drop `-NPU`
  for GPU snappiness (rail then honestly says GPU)
- Fresh stage between scenes: `demo.ps1 -Stop` + relaunch (~2 min)
- **Launch fresh on the day of the shoot** — don't reuse a stack left
  running overnight. The take's 1s poll cadence grows the database all
  night; a morning relaunch reseeds it clean (~2 min)
