"""P11 verification — the filmed take's event clock (VanGuard_Scripts_ShotList.docx).

Runs the forgot_switch take end-to-end — real SimSource, real Store, real
Guardian — on a fake 1s clock (no sleeps), replicating the poller loop and
the take's devices.yaml. Asserts the shot-list offsets from the Drive press:

    20% crossing   +20s (forgot_switch)  / +12s (forgot_switch_fast)
    Stage 1 acted  ~+28s  (Shed Starlink dish, ~24W)
    Stage 2 acted  ~+40s  (Shed rear A/C, the battery-saver exception)
    why-chip       after the final stage only (escalating flag)

plus: single warning alert at the crossing, screen demeanor
alarm → easing → calm, PROTECTED fridge/freezer on the card, Park reset
restoring the full take state, and take-to-take reproducibility within 1s
(second take pressed at a different moment, after a Park, on the same
running source — the actual filming flow).

Run:  .venv\\Scripts\\python.exe scripts\\verify_take.py
Exits non-zero on any FAIL.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time as real_time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api.guardian as guardian_mod
import api.outlook as outlook_mod
import poller.store as store_mod
from api.guardian import Guardian
from api.main import cfg_for_mode, evaluate_alerts
from api.outlook import compute_outlook
from poller.config import build_source
from poller.store import Store
from sim.scenarios import TAKES

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "sim" / "captures"
CHECKS: list[tuple[str, bool, str]] = []

# The shot-list clock, seconds after the Drive press (±1s crossing, ±2s
# stages: guardian pacing is wall-clock so eval-phase adds up to a second).
TARGETS = {
    "forgot_switch": {"crossing": (19.0, 21.0), "stage1": (26.0, 31.0),
                      "stage2": (38.0, 44.0)},
    "forgot_switch_fast": {"crossing": (11.0, 13.0), "stage1": (18.0, 23.0),
                           "stage2": (30.0, 36.0)},
}


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


class FakeClock:
    """Stands in for the `time` module inside guardian/store/outlook:
    time() is ours, everything else delegates to the real module."""

    def __init__(self, t0: float):
        self.t = float(t0)

    def time(self) -> float:
        return self.t

    def __getattr__(self, name):
        return getattr(real_time, name)


def take_cfg(take: str, db: Path) -> dict:
    """Mirror of what demo.ps1 writes for a take (keep the two in sync)."""
    return {
        "source": "sim",
        "db_path": str(db),
        "poll_interval_s": 1,
        "sim": {"scenario": "driveway", "speed": 1.0, "warmup_h": 0,
                "take": take},
        "guardian": {"interval_s": 1, "default_level": "protect",
                     # no arrival during takes: it would re-shed the dish
                     # that the Park reset just restored (live race, found
                     # on the real stack 2026-08-01)
                     "detectors": ["sag", "battery_saver"]},
        "alerts": {"soc_warn_pct": 20.0, "tte_warn_h": 0.5,
                   "alt_missing_severity": "advisory",
                   "reserve_warning": False},
    }


class Harness:
    """The poller loop + guardian loop, hand-cranked one fake second a tick."""

    def __init__(self, take: str, db: Path):
        self.clock = FakeClock(int(real_time.time()))
        guardian_mod.time = self.clock
        store_mod.time = self.clock
        outlook_mod.time = self.clock
        self.cfg = take_cfg(take, db)
        self.src = build_source(self.cfg)
        self.store = None
        self.guardian = None

    async def open(self):
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.cfg["db_path"]) + suffix)
            if p.exists():
                p.unlink()
        self.store = await Store(self.cfg["db_path"]).open()
        app = SimpleNamespace(state=SimpleNamespace(
            store=self.store, cfg=self.cfg))
        self.guardian = Guardian(app)
        app.state.guardian = self.guardian
        return self

    async def tick(self) -> dict:
        self.clock.t += 1.0
        for cmd_id, payload in await self.store.pending_commands():
            ok = self.src.apply_command(json.loads(payload))
            await self.store.mark_command(cmd_id, ok)
        self.src.advance(1.0)
        await self.store.write(self.src.emit(int(self.clock.t)))
        return await self.guardian.evaluate()

    async def readings(self) -> dict:
        return await self.store.latest()

    async def alerts(self) -> list[dict]:
        rd = await self.readings()
        mcfg = cfg_for_mode(self.cfg, "camp")
        pv_hist = await self.store.history("dcc50s", "pv_power_w", 24 * 3600)
        outlook = compute_outlook(rd, pv_hist, mcfg)
        return evaluate_alerts(rd, mcfg.get("alerts", {}), False,
                               outlook=outlook)

    async def soc(self) -> float | None:
        rd = await self.readings()
        try:
            return rd["shunt"]["soc_pct"][1]
        except KeyError:
            return None

    async def press_drive(self, on: bool) -> None:
        await self.store.enqueue_command(
            json.dumps({"target": "drive", "on": on}))

    async def close(self):
        await self.store.close()


async def run_take(h: Harness, label: str, targets: dict,
                   start_soc: float) -> dict | None:
    """One Drive press → full episode → measurements. Returns offsets."""
    press = h.clock.t
    await h.press_drive(True)
    crossing = stage1 = stage2 = chip = calm = None
    screens = []
    last = None
    for _ in range(150):
        st = await h.tick()
        off = h.clock.t - press
        soc = await h.soc()
        if crossing is None and soc is not None and soc <= 20.0:
            crossing = off
            al = await h.alerts()
            warns = [a for a in al if a["severity"] in ("warning", "critical")]
            check(f"{label}: single warning alert at the crossing",
                  len(warns) == 1 and warns[0]["id"] == "soc",
                  "; ".join(f"{a['severity']}:{a['id']}" for a in al))
        screens.append((off, st.get("screen")))
        for e in st.get("events") or []:
            if e["stage"] != "acted" or e["ts"] < press:
                continue    # this take's events only, not the last take's
            if "Starlink" in e["detail"] and stage1 is None:
                stage1 = e["ts"] - press
            if "rear A/C" in e["detail"] and stage2 is None:
                stage2 = e["ts"] - press
        card = st.get("card")
        if (chip is None and card and stage1 is not None
                and card["stage"] in ("acted", "confirmed")
                and not card["escalating"]):
            chip = off
        if calm is None and st.get("screen") == "calm":
            calm = off
            last = st
            break
        last = st
    lo, hi = targets["crossing"]
    check(f"{label}: 20% crossing on the clock",
          crossing is not None and lo <= crossing <= hi, f"+{crossing}s")
    lo, hi = targets["stage1"]
    check(f"{label}: Stage 1 (Starlink) acted on the clock",
          stage1 is not None and lo <= stage1 <= hi, f"+{stage1}s")
    lo, hi = targets["stage2"]
    check(f"{label}: Stage 2 (rear A/C) acted on the clock",
          stage2 is not None and lo <= stage2 <= hi, f"+{stage2}s")
    check(f"{label}: why-chip held until the final stage",
          chip is not None and stage2 is not None
          and stage2 <= chip <= stage2 + 4,
          f"chip +{chip}s vs stage2 +{stage2}s")

    # Screen demeanor: alarm strictly before Stage 1, easing between the
    # stages, calm after recovery confirms; nothing before the crossing.
    pre = {s for o, s in screens if crossing and o < crossing}
    between = {s for o, s in screens
               if stage1 and stage2 and stage1 + 1 < o < stage2}
    check(f"{label}: screen quiet before the crossing", pre == {None},
          str(pre))
    check(f"{label}: alarm pulse between crossing and Stage 1",
          any(s == "alarm" for o, s in screens
              if crossing and stage1 and crossing <= o < stage1),
          )
    check(f"{label}: easing between the stages",
          between == {"easing"}, str(between))
    check(f"{label}: calm after recovery", calm is not None,
          f"+{calm}s")

    card = (last or {}).get("card") or {}
    check(f"{label}: card shows STAGE 2 + PROTECTED fridge/freezer",
          card.get("stage_no") == 2
          and card.get("protected") == ["fridge", "freezer"],
          f"stage_no={card.get('stage_no')} protected={card.get('protected')}")
    check(f"{label}: decision receipt still says 0 external calls",
          (card.get("receipt") or {}).get("external") == "0 external calls")

    if None in (crossing, stage1, stage2):
        return None
    return {"crossing": crossing, "stage1": stage1, "stage2": stage2}


async def park_and_check(h: Harness, label: str, start_soc: float) -> None:
    """Park = full take reset: SOC at its mark, A/C off, dish warm, quiet."""
    await h.press_drive(False)
    await h.guardian.reset_take()        # the UI's Park button does both
    st = await h.tick()
    rd = await h.readings()
    soc = await h.soc()
    hvac = rd.get("hvac", {}).get("mode", (0, None))[1]
    net = rd.get("network", {}).get("mode", (0, None))[1]
    check(f"{label}: Park resets SOC to its mark",
          soc is not None and abs(soc - start_soc) <= 0.06,
          f"{soc} vs {start_soc}")
    check(f"{label}: Park resets A/C off + dish back online",
          hvac == 0.0 and net == 3.0, f"hvac={hvac} net={net}")
    check(f"{label}: Park clears the episode and the pulse",
          st.get("active") is None and st.get("screen") is None)


async def main() -> int:
    # --- the standard take: park-idle, take 1, Park, odd-offset take 2 ------
    take = "forgot_switch"
    start_soc = TAKES[take].start_soc
    h = await Harness(take, CAPTURE_DIR / "_verify_take.db").open()

    print("== forgot_switch: parked pre-roll ==")
    st = None
    for _ in range(30):
        st = await h.tick()
    soc = await h.soc()
    check("pre-drive: SOC pinned at its mark",
          soc is not None and abs(soc - start_soc) <= 0.06,
          f"{soc} vs mark {start_soc}")
    check("pre-drive: no episode, no pulse",
          st.get("active") is None and st.get("screen") is None)
    warns = [a for a in await h.alerts()
             if a["severity"] in ("warning", "critical")]
    check("pre-drive: no warning alerts", not warns,
          "; ".join(a["id"] for a in warns))
    dish = (await h.readings()).get("starlink", {}).get("power_w", (0, 0))[1]
    check("pre-drive: dish online and steady (~24W, not booting)",
          dish is not None and 15.0 <= dish <= 32.0, f"{dish}W")

    print("== forgot_switch: take 1 ==")
    t1 = await run_take(h, "take1", TARGETS[take], start_soc)
    await park_and_check(h, "take1", start_soc)

    # The filming flow: some narration passes, Frank presses Drive again at
    # an arbitrary moment. 17 idle ticks = a deliberately odd phase.
    print("== forgot_switch: take 2 (same source, odd press phase) ==")
    for _ in range(17):
        await h.tick()
    t2 = await run_take(h, "take2", TARGETS[take], start_soc)
    if t1 and t2:
        drift = max(abs(t1[k] - t2[k]) for k in t1)
        check("take-to-take reproducibility within 1s", drift <= 1.0,
              f"max drift {drift}s across crossing/stage1/stage2")
    await park_and_check(h, "take2", start_soc)
    await h.close()

    # --- the fast variant, one pass ------------------------------------------
    print("== forgot_switch_fast ==")
    take = "forgot_switch_fast"
    h = await Harness(take, CAPTURE_DIR / "_verify_take_fast.db").open()
    for _ in range(20):
        await h.tick()
    await run_take(h, "fast", TARGETS[take], TAKES[take].start_soc)
    await h.close()

    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
