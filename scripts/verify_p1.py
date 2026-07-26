"""P1 verification harness.

Success criterion (PLAN.md §8, P1): a 24h run produces a plausible-looking
graph — flat LiFePO4 voltage curve, sawtooth fridge load, solar bell peaking
~290W — plus the structural checks below. Exits non-zero on any FAIL.

Run:  .venv\\Scripts\\python.exe scripts\\verify_p1.py
"""
from __future__ import annotations

import asyncio
import dataclasses
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poller import derived
from poller.store import Store
from sim.loads import Fridge
from sim.replay import ReplaySource
from sim.scenarios import PRESETS, get_scenario
from sim.van_model import SimSource

FIXED_EPOCH = 1_770_000_000       # synthetic wall clock; determinism needs no real time
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def run_scenario(name: str, hours: float, cadence_s: int = 30):
    """Drive SimSource on a synthetic clock; returns (emissions, model states)."""
    src = SimSource(get_scenario(name))
    emissions, states = [], []
    steps = int(hours * 3600 / cadence_s)
    for k in range(steps):
        src.advance(cadence_s)
        ts = FIXED_EPOCH + (k + 1) * cadence_s
        emissions.append(src.emit(ts))
        m = src.model
        states.append({
            "ts": ts, "soc": m.battery.soc, "v": m.batt_v, "i": m.battery.i_net_a,
            "pv_w": m.pv_w, "load_w": m.load_w, "stage": m.charge_stage,
            "charge_ah": m.battery.charge_ah_total, "discharge_ah": m.battery.discharge_ah_total,
        })
    return emissions, states


def readings_from(emission) -> dict:
    out: dict = {}
    for s in emission:
        out.setdefault(s.source, {})[s.metric] = (s.ts, s.value)
    return out


def main() -> int:
    print("== determinism ==")
    a, _ = run_scenario("dusk_low", 2.0)
    b, _ = run_scenario("dusk_low", 2.0)
    check("same seed → identical emissions", a == b)

    print("== sunny_midday, 24h ==")
    ems, st = run_scenario("sunny_midday", 24.0)

    resting = [s for s in st if abs(s["i"]) < 5.0 and 20.0 < s["soc"] < 95.0
               and s["stage"] == "bulk"]
    vmin = min(s["v"] for s in resting)
    vmax = max(s["v"] for s in resting)
    check("LiFePO4 flat band: resting V within 12.85-13.45",
          12.85 <= vmin and vmax <= 13.45, f"[{vmin:.2f}, {vmax:.2f}]")

    pv_peak = max(s["pv_w"] for s in st)
    night = [s["pv_w"] for s in st if not (6.5 < (FIXED_EPOCH and (12.0 + (s['ts']-FIXED_EPOCH)/3600.0) % 24.0) < 20.5)]
    check("solar bell peaks 250-330W (observed van Pmax, not nameplate)",
          250.0 <= pv_peak <= 330.0, f"peak={pv_peak:.0f}W")
    check("solar is zero at night", all(w == 0.0 for w in night))

    d_soc = st[-1]["soc"] - get_scenario("sunny_midday").start_soc
    d_ah = st[-1]["charge_ah"] - st[-1]["discharge_ah"]
    check("coulomb consistency: ΔSOC tracks ∫I·dt / capacity",
          abs(d_soc - d_ah / 300.0 * 100.0) < 0.5,
          f"ΔSOC={d_soc:.2f}%, from counters={d_ah/300.0*100.0:.2f}%")

    vq = [s.value for e in ems for s in e if s.source == "shunt" and s.metric == "voltage_v"]
    check("emitted voltage quantised to 0.01V",
          all(abs(v * 100 - round(v * 100)) < 1e-6 for v in vq))

    print("== fridge duty cycle ==")
    import random
    fr = Fridge(random.Random(7), ambient_c=25.0)
    on = total = 0
    for _ in range(int(24 * 3600 / 10)):
        if fr.step(10.0) > 10.0:
            on += 1
        total += 1
    duty = on / total
    check("fridge duty in 25-55% (sawtooth, not flat line)",
          0.25 <= duty <= 0.55, f"duty={duty:.0%}")

    print("== dusk_low, 4h ==")
    _, dl = run_scenario("dusk_low", 4.0)
    socs = [s["soc"] for s in dl]
    check("SOC only falls (no sun, net drain)",
          all(s2 <= s1 + 1e-9 for s1, s2 in zip(socs, socs[1:])),
          f"{socs[0]:.1f}% → {socs[-1]:.1f}%")

    print("== shore_power honesty ==")
    ems_sp, sp = run_scenario("shore_power", 1.0)
    r = readings_from(ems_sp[-1])
    check("charging with no visible source → shore suspected",
          derived.shore_power_suspected(r) is True)
    check("load_w honestly unavailable on shore power", derived.load_w(r) is None)
    r_dl = readings_from(a[-1])
    check("load_w derivable off-grid",
          (derived.load_w(r_dl) or 0.0) > 10.0,
          f"load={derived.load_w(r_dl)}")
    tte = derived.time_to_empty_h(r_dl)
    check("time_to_empty plausible on dusk_low (12h-400h)",
          tte is not None and 12.0 <= tte <= 400.0, f"{tte and round(tte,1)}h")

    print("== cloudy_marginal ==")
    _, cm = run_scenario("cloudy_marginal", 6.0)
    cm_peak = max(s["pv_w"] for s in cm)
    check("cloudy PV intermittent and well below sunny peak",
          0.0 < cm_peak < 200.0, f"peak={cm_peak:.0f}W")

    print("== dropout capability ==")
    scn = dataclasses.replace(get_scenario("dusk_low"), dropout_rate=0.5)
    src = SimSource(scn)
    src.advance(60)
    rounds = []
    for k in range(200):
        src.advance(30)
        rounds.append(src.emit(FIXED_EPOCH + k))
    full = max(len(e) for e in rounds)
    partial = sum(1 for e in rounds if len(e) < full)
    check("sim can emit missing/stale rounds", partial > 20, f"{partial}/200 rounds degraded")

    print("== storage roundtrip ==")
    asyncio.run(storage_checks(ems))

    print("== replay source ==")
    asyncio.run(replay_checks(ems))

    print("== graph ==")
    png = graph(st)
    print(f"  wrote {png}")

    fails = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    return 1 if fails else 0


async def storage_checks(ems) -> None:
    db = Path(__file__).resolve().parent.parent / "sim" / "captures" / "_verify_p1.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            p.unlink()
    store = await Store(db).open()
    flat = [s for e in ems for s in e]
    await store.write(flat)
    latest = await store.latest()
    check("latest() returns both devices",
          "shunt" in latest and "dcc50s" in latest)
    now = max(s.ts for s in flat) + 60
    rows = await store.downsample(now=now)
    check("downsample produced 1m rows", rows > 1000, f"{rows} rows")
    hist = await store.history("shunt", "soc_pct", 24 * 3600 + 120, now=now)
    check("history() returns the 24h raw series", len(hist) > 2000, f"{len(hist)} pts")
    await store.prune(now=now + 49 * 3600)
    hist2 = await store.history("shunt", "soc_pct", 24 * 3600, now=now)
    check("raw pruned after 48h retention", len(hist2) == 0)
    hist1m = await store.history("shunt", "soc_pct", 80 * 3600, now=now + 49 * 3600)
    check("1m downsamples survive raw pruning", len(hist1m) > 1000, f"{len(hist1m)} pts")
    await store.close()


async def replay_checks(ems) -> None:
    cap = Path(__file__).resolve().parent.parent / "sim" / "captures" / "example.jsonl"
    cap.parent.mkdir(parents=True, exist_ok=True)
    import json
    flat = [s for e in ems[:120] for s in e]      # first hour of sunny_midday
    with cap.open("w", encoding="utf-8") as f:
        for s in flat:
            f.write(json.dumps({"ts": s.ts, "source": s.source,
                                "metric": s.metric, "value": s.value}) + "\n")
    clock = {"t": FIXED_EPOCH + 100_000.0}
    src = ReplaySource(cap, speed=60.0, ts_fn=lambda: clock["t"])
    got = []
    for _ in range(10):
        got.extend(await src.poll())
        clock["t"] += 5.0
    check("replay yields re-stamped samples at 60×", len(got) > 100, f"{len(got)} samples")


def graph(st) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hours = [(s["ts"] - FIXED_EPOCH) / 3600.0 + 12.0 for s in st]   # clock hours
    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    fig.suptitle("VanGuard P1 verification — sunny_midday, 24h sim (SIMULATED DATA)")
    axes[0].plot(hours, [s["soc"] for s in st], lw=1.2)
    axes[0].set_ylabel("SOC %")
    axes[1].plot(hours, [s["v"] for s in st], lw=0.8)
    axes[1].set_ylabel("Battery V")
    axes[1].set_ylim(12.4, 14.8)
    axes[2].plot(hours, [s["pv_w"] for s in st], lw=0.8, color="tab:orange")
    axes[2].set_ylabel("PV W")
    axes[3].plot(hours, [s["load_w"] for s in st], lw=0.6, color="tab:green")
    axes[3].set_ylabel("DC load W")
    axes[3].set_xlabel("clock hour (sim)")
    for ax in axes:
        ax.grid(True, alpha=0.3)
    out = Path(__file__).resolve().parent.parent / "sim" / "verify_p1_sunny24h.png"
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    return out


if __name__ == "__main__":
    sys.exit(main())
