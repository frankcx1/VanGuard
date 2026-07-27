"""P6 verification — insight rules, outlook math, provenance, fallback,
operating modes, story-mode plumbing (appliance command), NPU-claim honesty.

All deterministic; no LLM required (the fallback path is the point).

Run:  .venv\\Scripts\\python.exe scripts\\verify_p6.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from api.chat import _provenance
from api.insight import compute_insight
from api.main import create_app, evaluate_alerts
from api.outlook import compute_outlook
from sim.scenarios import get_scenario
from sim.van_model import SimSource
from verify_p2 import seed

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "sim" / "captures"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def rd(now: int, **sources) -> dict:
    """Synthetic readings: rd(now, shunt={'soc_pct': 46, ...})"""
    return {src: {m: (now, v) for m, v in metrics.items()}
            for src, metrics in sources.items()}


def local_ts(hour: int) -> int:
    lt = time.localtime()
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                            hour, 0, 0, 0, 0, -1)))


def outlook_checks() -> None:
    print("== outlook math (deterministic, synthetic readings) ==")
    now = local_ts(22)   # 22:00 → 8.5h to the 6:30 sunrise
    readings = rd(now,
                  shunt={"soc_pct": 46.0, "voltage_v": 12.9, "current_a": -14.0,
                         "power_w": -180.0},
                  dcc50s={"pv_power_w": 0.0, "alt_power_w": 0.0})
    out = compute_outlook(readings, [], {}, now=now)
    # Review scenario 3: 46% @ 180W overnight. 3840Wh: stored 1766Wh,
    # 8.5h × 180W = 1530Wh → ~6% at sunrise → reserve breached.
    check("overnight concern: sunrise SOC ≈ 6%, reserve breached",
          out["available"] and abs(out["soc_at_sunrise_pct"] - 6.0) <= 2.0
          and out["reserve_ok_overnight"] is False,
          f"sunrise={out['soc_at_sunrise_pct']}%")
    check("runtime to reserve ≈ 5.5h at 180W",
          abs(out["runtime_to_reserve_h"] - 5.5) < 0.3,
          f"{out['runtime_to_reserve_h']}h")
    check("night forecast is high confidence (no solar uncertainty)",
          out["confidence"] == "high")
    check("assumptions carry real van capacity (3840Wh, not generic 5kWh)",
          out["assumptions"]["capacity_wh"] == 3840.0)

    stale = rd(now - 300, shunt={"soc_pct": 46.0, "power_w": -180.0,
                                 "current_a": -14.0})
    out2 = compute_outlook(stale, [], {}, now=now)
    check("stale battery data → low confidence + issue listed",
          out2["confidence"] == "low" and out2["issues"])

    out3 = compute_outlook(rd(now, gps={"lat": 1.0}), [], {}, now=now)
    check("no battery data → honestly unavailable", out3["available"] is False)

    # Engine running: the alternator keeps charging as long as there's
    # diesel — no "0% by sunrise" while net-positive on a persistent source.
    alt = rd(now,
             shunt={"soc_pct": 46.0, "voltage_v": 13.4, "current_a": 30.0,
                    "power_w": 402.0},
             dcc50s={"pv_power_w": 0.0, "alt_power_w": 500.0})
    out4 = compute_outlook(alt, [], {}, now=now)
    check("alternator charging → sunrise forecast rises, reserve OK",
          out4["reserve_ok_overnight"] is True
          and out4["soc_at_sunrise_pct"] > 46.0
          and out4["assumptions"]["persistent_charging"] is True,
          f"sunrise={out4['soc_at_sunrise_pct']}%")

    # Engine on but cooktop bigger than the alternator: net drain persists
    # and the forecast must still say so.
    alt2 = rd(now,
              shunt={"soc_pct": 46.0, "voltage_v": 12.9, "current_a": -90.0,
                     "power_w": -1160.0},
              dcc50s={"pv_power_w": 0.0, "alt_power_w": 540.0})
    out5 = compute_outlook(alt2, [], {}, now=now)
    check("net drain despite alternator → honest countdown remains",
          out5["reserve_ok_overnight"] is False
          and out5["runtime_to_reserve_h"] is not None,
          f"{out5['runtime_to_reserve_h']}h to reserve")


def insight_checks() -> None:
    print("== insight rules ==")
    now = local_ts(14)
    # Review scenario 1: full battery still charging, hot cabin, hvac off.
    readings = rd(now,
                  shunt={"soc_pct": 100.0, "current_a": 3.2, "power_w": 43.0},
                  dcc50s={"pv_power_w": 269.0, "alt_power_w": 0.0},
                  hvac={"cabin_temp_c": 29.9, "setpoint_c": 21.0, "mode": 0.0,
                        "hvac_power_w": 0.0},
                  gps={"speed_mph": 0.0})
    out = compute_outlook(readings, [(now, 269.0)], {}, now=now)
    ins = compute_insight(readings, out, {}, now=now)
    s = ins["summary"].lower()
    check("explains 100%-but-charging as absorption/rounding",
          "100%" in s and "absorption" in s)
    check("flags hot cabin with delta in °F", "°f above" in s)
    check("recommends ventilation/cooling",
          "cooling" in (ins["recommendation"] or "").lower()
          or "ventilation" in (ins["recommendation"] or "").lower())
    check("proposes a sim cooling action (confirmation required)",
          ins["proposed_action"] is not None
          and ins["proposed_action"]["command"]["mode"] == "cool")
    check("provenance is deterministic rules",
          ins["generated_by"] == "deterministic rules")

    # Review scenario 4: driving but no alternator input.
    fault = rd(now, shunt={"soc_pct": 60.0, "current_a": -4.0, "power_w": -52.0},
               dcc50s={"pv_power_w": 30.0, "alt_power_w": 0.0},
               gps={"speed_mph": 45.0})
    ins2 = compute_insight(fault, compute_outlook(fault, [], {}, now=now), {},
                           now=now)
    check("driving with no alternator → flagged, no component blamed",
          "alternator" in ins2["summary"].lower()
          and "worth checking" in ins2["summary"].lower())

    # Review scenario 5: conflicting sensors.
    conflict = rd(now, shunt={"soc_pct": 60.0, "current_a": 5.0, "power_w": -80.0})
    ins3 = compute_insight(conflict, {"available": False}, {}, now=now)
    check("conflicting current/power → data-quality note",
          any("disagree" in q for q in ins3["data_quality"]))


def alert_checks() -> None:
    print("== alert rules ==")
    now = local_ts(14)
    readings = rd(now,
                  shunt={"soc_pct": 100.0, "current_a": 3.0, "power_w": 40.0},
                  dcc50s={"alt_power_w": 0.0}, gps={"speed_mph": 45.0})
    alerts = evaluate_alerts(readings, {}, stale=False)
    ids = {a["id"]: a["severity"] for a in alerts}
    check("100%-while-charging → advisory", ids.get("soc-full-charging") == "advisory")
    check("moving without alternator → warning", ids.get("alt-missing") == "warning")

    conflict = rd(now, shunt={"soc_pct": 60.0, "current_a": 5.0, "power_w": -80.0})
    ids2 = {a["id"]: a["severity"] for a in evaluate_alerts(conflict, {}, False)}
    check("sensor conflict → data-quality severity",
          ids2.get("sensor-conflict") == "data-quality")

    bad_outlook = {"available": True, "reserve_ok_overnight": False,
                   "soc_at_sunrise_pct": 12.0}
    ids3 = {a["id"]: a for a in evaluate_alerts(
        rd(now, shunt={"soc_pct": 46.0, "current_a": -14.0, "power_w": -180.0}),
        {}, False, outlook=bad_outlook)}
    check("forecast reserve breach → warning alert",
          "reserve-forecast" in ids3)


def provenance_checks() -> None:
    print("== provenance labels ==")
    check("calculation + model",
          _provenance([{"tool": "estimate_runtime"}], "GPU")
          == "calculation + local model (GPU)")
    check("tools + model",
          _provenance([{"tool": "get_nearby_pois"}], "NPU")
          == "local tools + local model (NPU)")
    check("snapshot only",
          "audited snapshot" in _provenance([{"tool": "get_climate", "auto": True}], "GPU"))
    check("no model → deterministic label",
          "no model active" in _provenance([], None))


def api_checks() -> None:
    print("== API: fallback, runtime honesty, modes ==")
    db = CAPTURE_DIR / "_verify_p6.db"
    asyncio.run(seed(db, "dusk_low", 2.0))
    # Bogus model dir → the app must stay fully usable, deterministically.
    app = create_app({"source": "sim", "db_path": str(db),
                      "inference": {"model_dir": "ov_nonexistent"}})
    with TestClient(app) as c:
        rt = c.get("/api/runtime").json()
        check("runtime honesty: nothing loaded → no device claimed",
              rt["loaded"] is False and rt["device_confirmed"] is None
              and rt["model_exported"] is False)

        r = c.post("/v1/chat/completions", json={"messages": [
            {"role": "user", "content": "Can I run the cooktop for 25 minutes?"}]})
        check("no model → deterministic fallback answers", r.status_code == 200)
        data = r.json()
        vg = data["vanguard"]
        answer = data["choices"][0]["message"]["content"]
        check("fallback provenance labeled",
              "deterministic" in vg["provenance"],
              vg["provenance"])
        check("fallback cooktop verdict correct (No at low dusk_low SOC)",
              answer.startswith("No") and "below the 20% reserve" in answer,
              answer[:90])
        check("fallback used real audited tools",
              any(t["tool"] == "estimate_runtime" for t in vg["tool_calls"]))

        ins = c.get("/api/insight").json()
        check("insight endpoint serves rules + outlook + mode",
              "summary" in ins["insight"] and "mode" in ins)

        c.post("/api/mode", json={"mode": "storage"})
        ol = c.get("/api/outlook").json()
        check("storage mode raises reserve policy to 50%",
              ol["assumptions"]["reserve_pct"] == 50.0)
        c.post("/api/mode", json={"mode": "camp"})
        ol2 = c.get("/api/outlook").json()
        check("camp mode restores 20% reserve",
              ol2["assumptions"]["reserve_pct"] == 20.0)


def appliance_checks() -> None:
    print("== appliance command (story mode step 5) ==")
    src = SimSource(get_scenario("driveway"))
    src.advance(60)
    ok = src.apply_command({"target": "appliance", "name": "cooktop", "on": True})
    src.advance(30)
    ems = src.emit(1_770_000_090)
    inv = {s.metric: s.value for s in ems if s.source == "inverter"}
    check("cooktop on → inverting ~1500W AC",
          ok and inv.get("state") == 2.0 and inv.get("ac_out_w", 0) > 1400,
          f"ac={inv.get('ac_out_w')}W")
    src.apply_command({"target": "appliance", "name": "cooktop", "on": False})
    src.advance(30)
    ems2 = src.emit(1_770_000_120)
    inv2 = {s.metric: s.value for s in ems2 if s.source == "inverter"}
    check("cooktop off → back to idle", inv2.get("state") == 1.0)
    check("unknown appliance refused",
          src.apply_command({"target": "appliance", "name": "hairdryer",
                             "on": True}) is False)


def main() -> int:
    outlook_checks()
    insight_checks()
    alert_checks()
    provenance_checks()
    api_checks()
    appliance_checks()
    fails = [x for x in CHECKS if not x[1]]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
