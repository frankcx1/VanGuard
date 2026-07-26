"""Three-way NPU / GPU / CPU benchmark (PLAN.md §8, P3).

Measures per device: model load/compile time, TTFT, tokens/sec, and — when
the Pro is running on battery — mean discharge watts and watt-hours per
query, read from the machine's own battery gauge
(``root\\wmi BatteryStatus.DischargeRate``). On AC power watts are reported
as n/a; re-run unplugged for the video's number.

Nothing here is simulated: real model, real silicon, real numbers.

Run:  .venv\\Scripts\\python.exe inference\\bench.py --model-dir ov_qwen3_4b_instruct_2507_int4_npu
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from inference.serve import InferenceEngine  # noqa: E402

# Van-shaped prompts, compact per the context discipline. Deterministic set
# so runs are comparable across devices and days.
PROMPTS = [
    ("cooktop", "You monitor a camper van's 12V system. State: SOC 42%, "
     "battery 300Ah LiFePO4, net draw 35W, solar 0W (dusk). The induction "
     "cooktop pulls 1700W DC for 25 minutes. Can I cook dinner without "
     "dropping below 20% SOC? Show the arithmetic, then answer yes or no."),
    ("status", "Telemetry: V=13.08, I=-2.9A, SOC=61%, PV=0W, fridge duty "
     "38%. Summarise the power situation for a display in under 40 words."),
    ("advice", "A camper van battery reads SOC 30% at 10:00 with cloudy "
     "skies, PV peaking 118W, base load 25W. Estimate SOC by sunset at "
     "20:30 and say whether to conserve. Be brief and show key numbers."),
]


class PowerSampler:
    """Samples battery discharge rate (mW) once a second in a thread."""

    PS = ("Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus | "
          "Select-Object -First 1 | ForEach-Object { \"$($_.Discharging) $($_.DischargeRate)\" }")

    def __init__(self):
        self._samples_mw: list[float] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _read(self) -> float | None:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", self.PS],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            discharging, rate = out.split()
            if discharging.lower() == "true":
                return float(rate)
        except Exception:
            pass
        return None

    def _run(self):
        while not self._stop.is_set():
            mw = self._read()
            if mw and mw > 0:
                self._samples_mw.append(mw)
            self._stop.wait(1.0)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)

    @property
    def mean_w(self) -> float | None:
        if not self._samples_mw:
            return None       # on AC, or gauge unavailable
        return statistics.mean(self._samples_mw) / 1000.0


def bench_device(model_dir: str, device: str, iters: int,
                 max_new_tokens: int) -> dict:
    print(f"\n=== {device} ===", flush=True)
    try:
        eng = InferenceEngine(model_dir, device_order=(device,))
    except RuntimeError as e:
        print(f"  load FAILED: {e}")
        return {"device": device, "ok": False, "error": str(e).strip()}
    print(f"  loaded in {eng.load_s:.1f}s")

    eng.generate(PROMPTS[0][1], max_new_tokens=16)     # warmup / first compile
    ttfts, tps_list, results = [], [], []
    with PowerSampler() as power:
        t0 = time.perf_counter()
        for it in range(iters):
            for name, prompt in PROMPTS:
                r = eng.generate(prompt, max_new_tokens=max_new_tokens)
                ttfts.append(r.ttft_ms)
                tps_list.append(r.tokens_per_s)
                results.append(r)
                print(f"  [{device}] {name}: ttft={r.ttft_ms:.0f}ms "
                      f"tps={r.tokens_per_s:.1f} tokens={r.n_new_tokens}", flush=True)
        wall_s = time.perf_counter() - t0
    mean_w = power.mean_w
    queries = iters * len(PROMPTS)
    wh_per_query = (mean_w * wall_s / 3600.0 / queries) if mean_w else None
    return {
        "device": device, "ok": True,
        "load_s": round(eng.load_s, 1),
        "ttft_ms_mean": round(statistics.mean(ttfts), 0),
        "tokens_per_s_mean": round(statistics.mean(tps_list), 1),
        "power_w_mean": round(mean_w, 1) if mean_w else None,
        "wh_per_query": round(wh_per_query, 3) if wh_per_query else None,
        "queries": queries,
        "wall_s": round(wall_s, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--devices", default="NPU,GPU,CPU")
    ap.add_argument("--iters", type=int, default=2)
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    model_dir = str(REPO_ROOT / a.model_dir) \
        if not Path(a.model_dir).is_absolute() else a.model_dir
    rows = [bench_device(model_dir, d.strip(), a.iters, a.max_new_tokens)
            for d in a.devices.split(",")]

    print("\n" + json.dumps(rows, indent=2))
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0 if any(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
