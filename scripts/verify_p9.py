"""P9 verification — whole-van fusion: chassis sim, cross-system findings,
arrival cleanup, departure readiness.

Run:  .venv\\Scripts\\python.exe scripts\\verify_p9.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from api.deterministic import departure_checklist, format_checklist
from api.guardian import Guardian
from api.main import create_app
from poller.store import Store
from sim.scenarios import get_scenario
from sim.van_model import SimSource
from verify_p2 import seed

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "sim" / "captures"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def rd(now: int, **sources) -> dict:
    return {src: {m: (now, v) for m, v in metrics.items()}
            for src, metrics in sources.items()}


def by_source(ems, source):
    return {s.metric: s.value for s in ems if s.source == source}


def chassis_sim_checks() -> None:
    print("== chassis sim (read-only domain) ==")
    src = SimSource(get_scenario("road_trip"))
    src.advance(10 * 60)
    ch = by_source(src.emit(1_770_000_600), "chassis")
    check("driving: engine on, chassis at charging voltage",
          ch.get("engine_running") == 1.0 and 13.8 <= ch.get("chassis_v", 0) <= 14.4,
          f"{ch.get('chassis_v')}V")
    fuel_early = ch.get("fuel_pct")
    src.advance(60 * 60)
    ch2 = by_source(src.emit(1_770_004_200), "chassis")
    check("fuel burns while the engine runs",
          ch2.get("fuel_pct", 99) < fuel_early, f"{fuel_early}% → {ch2.get('fuel_pct')}%")
    src.advance(2 * 3600)          # route long over; parked
    ch3 = by_source(src.emit(1_770_011_400), "chassis")
    check("parked: engine off, chassis at rest voltage, coolant cooling",
          ch3.get("engine_running") == 0.0 and ch3.get("chassis_v", 0) < 13.0
          and ch3.get("coolant_c", 99) < ch2.get("coolant_c", 0),
          f"{ch3.get('chassis_v')}V, coolant {ch3.get('coolant_c')}°C")
    check("odometer = base + trip",
          ch3.get("odometer_mi", 0) > get_scenario("road_trip").odometer_mi + 15)

    print("== OBD engine stream (coherent model) ==")
    check("driving: rpm/load/boost in plausible bands",
          1200 <= ch.get("rpm", 0) <= 2600 and 30 <= ch.get("engine_load_pct", 0) <= 80
          and ch.get("boost_psi", 0) > 1.5,
          f"{ch.get('rpm')}rpm, {ch.get('engine_load_pct')}%, {ch.get('boost_psi')}psi")
    mpg = (ch.get("speed_mph", 0) / ch.get("fuel_rate_gph", 1)
           if ch.get("fuel_rate_gph", 0) > 0.1 else 0)
    check("live MPG plausible for a loaded 3500XD (10-22)",
          10.0 <= mpg <= 22.0, f"{mpg:.1f} mpg")
    check("parked: engine stream reads zero",
          ch3.get("rpm") == 0.0 and ch3.get("boost_psi") == 0.0
          and ch3.get("fuel_rate_gph") == 0.0)
    check("range tracks the tank",
          ch3.get("range_mi", 0) < ch.get("range_mi", 9999)
          and 100 < ch3.get("range_mi", 0) < 400,
          f"{ch.get('range_mi')} → {ch3.get('range_mi')} mi")

    print("== charging_path_fault scenario (fusion premise) ==")
    f = SimSource(get_scenario("charging_path_fault"))
    f.advance(10 * 60)
    ems = f.emit(1_770_000_600)
    chf = by_source(ems, "chassis")
    dcc = by_source(ems, "dcc50s")
    check("engine healthy and running, chassis 14V, yet house alt = 0W",
          chf.get("engine_running") == 1.0 and chf.get("chassis_v", 0) > 13.8
          and dcc.get("alt_power_w") == 0.0,
          f"chassis {chf.get('chassis_v')}V, alt {dcc.get('alt_power_w')}W")
    check("no DTC — Mercedes sees nothing wrong (that's the story)",
          chf.get("dtc_count") == 0.0)


def detector_checks() -> None:
    print("== interactive drive (free-drive mode) ==")
    dv = SimSource(get_scenario("driveway"))
    dv.advance(60)
    ok = dv.apply_command({"target": "drive", "on": True, "speed_mph": 30})
    dv.advance(20)                          # inside the healthy first 30s
    ems_d = dv.emit(1_770_000_080)
    chd = by_source(ems_d, "chassis")
    lat0 = by_source(ems_d, "gps").get("lat")
    check("drive command: engine starts, van moves, alternator charges",
          ok and chd.get("engine_running") == 1.0 and chd.get("rpm", 0) > 1000
          and by_source(ems_d, "dcc50s").get("alt_power_w", 0) > 300,
          f"rpm={chd.get('rpm')}, alt={by_source(ems_d, 'dcc50s').get('alt_power_w')}W")
    dv.advance(700)
    ems_m = dv.emit(1_770_000_780)
    moved = abs(by_source(ems_m, "gps").get("lat", 0) - lat0)
    check("position actually travels", moved > 0.02, f"Δlat={moved:.4f}")

    # P11 replaced the old +30s scripted mid-drive fault with the take-gated
    # forgot-switch story (scripts/verify_take.py). A drive with NO take
    # armed stays healthy the whole way — charging throughout.
    chm = by_source(ems_m, "chassis")
    check("no-take drive stays healthy mid-drive (engine on, alt charging)",
          chm.get("engine_running") == 1.0
          and by_source(ems_m, "dcc50s").get("alt_power_w", 0) > 300
          and chm.get("chassis_v", 0) > 13.8,
          f"alt={by_source(ems_m, 'dcc50s').get('alt_power_w')}W, "
          f"chassis={chm.get('chassis_v')}V")

    home = get_scenario("driveway").position
    dv.apply_command({"target": "drive", "on": False})
    dv.advance(30)
    ems_p = dv.emit(1_770_000_810)
    chp = by_source(ems_p, "chassis")
    gpp = by_source(ems_p, "gps")
    check("park: engine off, stream zeroes",
          chp.get("engine_running") == 0.0 and chp.get("rpm") == 0.0)
    check("park resets the take: trip zeroed, back home",
          gpp.get("trip_mi") == 0.0
          and abs(gpp.get("lat", 0) - home[0]) < 0.001)
    dv.apply_command({"target": "drive", "on": True, "speed_mph": 30})
    dv.advance(15)
    ems_2 = dv.emit(1_770_000_830)
    check("next drive also healthy (forgot-switch is take-gated)",
          by_source(ems_2, "dcc50s").get("alt_power_w", 0) > 300,
          f"alt={by_source(ems_2, 'dcc50s').get('alt_power_w')}W")
    dv.apply_command({"target": "drive", "on": False})

    print("== fusion detectors ==")
    g = Guardian(SimpleNamespace(state=None))
    now = int(time.time())

    fault = rd(now,
               chassis={"engine_running": 1.0, "chassis_v": 14.1},
               dcc50s={"alt_power_w": 0.0},
               shunt={"soc_pct": 55.0})
    r = g.detect_alternator_gap(fault)
    check("charging-path anomaly uses chassis evidence",
          r is not None and "14.1V" in r["detail"] and r["actions"] == [],
          r["title"] if r else "none")
    check("no anomaly when battery is full (charge legitimately suppressed)",
          g.detect_alternator_gap(rd(now,
              chassis={"engine_running": 1.0, "chassis_v": 14.1},
              dcc50s={"alt_power_w": 0.0},
              shunt={"soc_pct": 97.0})) is None)
    check("no component is blamed",
          "no single component can be blamed" in r["detail"])
    fault_with_loads = rd(now,
                          chassis={"engine_running": 1.0, "chassis_v": 14.1},
                          dcc50s={"alt_power_w": 0.0},
                          shunt={"soc_pct": 55.0},
                          network={"mode": 3.0},
                          inverter={"state": 0.0, "ac_out_w": 0.0})
    r2 = g.detect_alternator_gap(fault_with_loads)
    check("fault with travel loads → conserves by shedding (real action)",
          r2 is not None and r2["severity"] == "warning"
          and r2["actions"] == ["suspend_starlink"]
          and "cannot be repaired autonomously" in r2["detail"])

    g2 = Guardian(SimpleNamespace(state=None))
    moving = rd(now, chassis={"engine_running": 1.0, "speed_mph": 30.0},
                network={"mode": 3.0},
                inverter={"state": 1.0, "ac_out_w": 0.0})
    parked = rd(now, chassis={"engine_running": 0.0, "speed_mph": 0.0},
                network={"mode": 3.0},
                inverter={"state": 1.0, "ac_out_w": 0.0})
    check("no arrival while still moving", g2.detect_arrival(moving) is None)
    arr = g2.detect_arrival(parked)
    check("arrival fires on the moving→parked transition",
          arr is not None and "set_mode_camp" in arr["actions"]
          and "suspend_starlink" in arr["actions"]
          and "inverter_standby_off" in arr["actions"])
    check("arrival fires exactly once", g2.detect_arrival(parked) is None)


def checklist_checks() -> None:
    print("== departure readiness (unknown ≠ PASS) ==")
    now = int(time.time())
    readings = rd(now,
                  shunt={"soc_pct": 72.0},
                  charge_ctl={"shore_on": 1.0},
                  inverter={"state": 1.0},
                  switches={"fridge_on": 1.0, "freezer_on": 0.0},
                  hvac={"mode": 0.0},
                  chassis={"fuel_pct": 18.0, "def_pct": 60.0, "dtc_count": 0.0})
    rows = {r["item"]: r for r in departure_checklist(readings)}
    check("shore still connected → attention",
          rows["Shore power"]["status"] == "attention")
    check("inverter still on → attention",
          rows["Inverter"]["status"] == "attention")
    check("freezer switched off → attention (food risk)",
          rows["Freezer"]["status"] == "attention")
    check("low fuel → attention", rows["Fuel"]["status"] == "attention")

    no_chassis = rd(now, shunt={"soc_pct": 72.0})
    rows2 = {r["item"]: r for r in departure_checklist(no_chassis)}
    check("missing chassis → fuel/DEF/DTC are NOT MONITORED, never PASS",
          all(rows2[i]["status"] == "not monitored"
              for i in ("Fuel", "DEF", "Diagnostic codes")))
    txt = format_checklist(departure_checklist(readings))
    check("formatted verdict counts attention items",
          "need attention" in txt)


def arrival_flow_checks() -> None:
    print("== arrival episode end-to-end (drive → park across guardian runs) ==")
    db = CAPTURE_DIR / "_verify_p9_arr.db"
    for sfx in ("", "-wal", "-shm"):
        p = Path(str(db) + sfx)
        if p.exists():
            p.unlink()
    src = SimSource(get_scenario("arrival_cleanup"))
    src.advance(int(0.5 * 3600))          # still driving (parks ~36 min)
    now = int(time.time())

    async def write(ts):
        st = await Store(db).open()
        try:
            await st.write(src.emit(ts))
        finally:
            await st.close()
    asyncio.run(write(now))

    app = create_app({"source": "sim", "db_path": str(db),
                      "inference": {"model_dir": "ov_nonexistent"},
                      "watchdog": {"interval_min": 0},
                      "guardian": {"interval_s": 0}})
    with TestClient(app) as c:
        c.post("/api/guardian/run")            # observes driving
        src.advance(15 * 60)                   # …now parked, ignition off
        asyncio.run(write(now + 30))
        c.post("/api/guardian/run")            # the transition cycle
        s = c.get("/api/guardian").json()
        arr = [e for e in s["events"] if "Arrived" in e["title"]]
        check("arrival episode fires on the live transition",
              any(e["stage"] == "detected" for e in arr))
        check("arrival plan: mode→Camp + shed travel loads",
              any("Camp" in e["detail"] and "Starlink" in e["detail"]
                  for e in arr if e["stage"] == "decided"),
              next((e["detail"][:80] for e in arr if e["stage"] == "decided"), "none"))
        check("operating mode switched to camp",
              c.get("/api/status").json()["mode"] == "camp")


def api_checks() -> None:
    print("== API: departure routed deterministically; chassis tool ==")
    db = CAPTURE_DIR / "_verify_p9.db"
    asyncio.run(seed(db, "arrival_cleanup", 0.2))
    app = create_app({"source": "sim", "db_path": str(db),
                      "inference": {"model_dir": "ov_nonexistent"},
                      "watchdog": {"interval_min": 0},
                      "guardian": {"interval_s": 0}})
    with TestClient(app) as c:
        r = c.post("/v1/chat/completions", json={"messages": [
            {"role": "user", "content": "Are we ready to depart?"}]})
        d = r.json()
        rr = c.post("/api/guardian/reset")
        check("guardian take-reset re-arms Protect",
              rr.status_code == 200 and rr.json()["level"] == "protect"
              and c.get("/api/guardian").json()["level"] == "protect")

        check("departure question → deterministic checklist",
              r.status_code == 200
              and "Departure readiness" in d["choices"][0]["message"]["content"]
              and "deterministic checklist" in d["vanguard"]["provenance"])
        check("driving state flagged in checklist rows",
              "NOT MONITORED" in d["choices"][0]["message"]["content"]
              or "ATTENTION" in d["choices"][0]["message"]["content"])


def main() -> int:
    chassis_sim_checks()
    detector_checks()
    checklist_checks()
    arrival_flow_checks()
    api_checks()
    fails = [x for x in CHECKS if not x[1]]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
