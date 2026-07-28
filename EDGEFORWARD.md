# EdgeForwardAI — what the VanGuard build proved

*Draft for LinkedIn / blog. Numbers are measured on this machine
(BENCHMARKS.md); the build history, failures included, is BUILD_LOG.md.*

---

Eighteen months ago, putting a language model on a laptop NPU was a
research project. You experimented. You fought drivers, watched ops fall
back silently to CPU, and quantized models by trial and error.

This month I built VanGuard — an offline AI that monitors a camper van's
power system, forecasts its battery through the night, takes autonomous
protective action, and explains every decision by voice — and the striking
part is what I *didn't* have to do. I didn't experiment. There is now a
**defined, functioning path** from open weights to NPU silicon, and it
exists because a stack of players each did their part and the parts
actually fit:

- **Intel** shipped the silicon (a Core Ultra Series 3 NPU, 50 TOPS, in a
  Surface Pro) *and* the runtime that makes it reachable — OpenVINO
  GenAI, where the entire NPU/GPU decision is a one-word device string.
- **Microsoft** shipped the machine, and an OS where on-device dictation
  (Copilot+ Fluid Dictation) is a system service any app can lean on —
  voice input with zero cloud, zero code.
- **The open-weight model builders** — the Qwen team's 4B instruct model,
  OpenAI's Whisper — published weights good enough to do real work at a
  size that fits edge silicon.
- **Hugging Face** glued it together: `optimum-cli export openvino` turns
  a model repo into an INT4 artifact for the NPU in one command.

The whole system — telemetry simulator, storage, dashboard, forecasting,
deterministic autonomy, NPU chat with audited tools, offline voice — went
from empty repo to filmed demo in **four days**, AI-assisted, evenings and
a weekend. Not because it was trivial, but because every layer had a
documented route that worked. The problems I did hit were
*configuration-level, not feasibility-level*: a chat-template default that
double-wrapped prompts, an exporter invocation that exits clean while
doing nothing, static-shape context discipline on the NPU. Each cost an
hour, not a week, and none required inventing anything.

## The numbers that make it "forward," not "fallback"

- **27 tokens/sec on the NPU at 18.4 W** package power (37 tok/s on GPU
  — same INT4 artifact, one config word apart).
- **≈ 0.02 Wh per question.** On the van's 3.8 kWh battery that is
  roughly **190,000 questions per charge**. One cooktop dinner costs the
  same energy as ~35,000 questions. Intelligence is now a rounding error
  on the power budget.
- **Zero external calls.** Not throttled, not cached — architecturally
  absent. The model is a 2.1 GB folder of files; the runtime is a Python
  import. Nothing phones home, nothing expires, nothing needs a
  subscription to keep working in ten years.

## Why the edge is the forward position

The reflex is to treat local AI as a degraded fallback for when the cloud
is unreachable. VanGuard argues the opposite. In this system the local
model is not the backup — it is the *architecture*:

- **The data never needed to leave.** Battery telemetry, location, what's
  running in your home-on-wheels — there is no version of this product
  improved by shipping that to a data center.
- **Latency and availability become properties of the device**, not of a
  WAN path through a dish on the roof. The demo makes the point on
  camera: Starlink connected, and the AI still doesn't use it. Turn the
  uplink off and the rail reads **NO UPLINK · LOCAL AI ACTIVE** — and
  nothing else changes.
- **Autonomy demands locality.** A Guardian that sheds load when your
  battery won't make sunrise cannot depend on connectivity to function —
  by definition it earns trust only if it works when everything else
  fails.

That's **EdgeForwardAI**: put the intelligence where the data lives and
where the decisions land, and treat the cloud as optional reach, not as
the brain. Eighteen months ago that was a position you argued. Today it's
a stack you `pip install`.

The van was the perfect proof case — a small, honest world where power is
finite, connectivity is a luxury, and the AI has to be a resident, not a
service. But nothing in the architecture is van-shaped. Clinics, farms,
factories, boats, homes: anywhere the data is born on-site and the
decision matters on-site, the edge isn't where AI degrades to.

It's where it's headed.

---

*Build: Surface Pro for Business 13" (Intel Core Ultra Series 3, 50-TOPS
NPU, 64 GB) · Qwen3-4B-Instruct-2507 INT4 via OpenVINO GenAI ·
whisper-small.en · Windows Fluid Dictation · FastAPI + SQLite · zero
cloud at runtime. Demo telemetry simulated and labeled as such; the AI,
NPU inference, calculations, and decisions are real.*
