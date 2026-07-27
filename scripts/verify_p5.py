"""P5 verification harness — demo mode: charge source, alerts, climate
control path, trip keeper, offline voice.

The voice check synthesizes real speech with Windows SAPI TTS and runs it
through the OpenVINO Whisper endpoint — a genuine offline round-trip.

Run:  .venv\\Scripts\\python.exe scripts\\verify_p5.py [--skip-voice]
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from api.main import create_app, track_miles
from api.tools import ToolRunner
from poller.store import Store
from sim.gps import nearby_pois
from sim.scenarios import get_scenario
from sim.van_model import SimSource
from verify_p2 import seed

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "sim" / "captures"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def sim_checks() -> None:
    print("== road_trip sim: alternator, GPS, HVAC ==")
    src = SimSource(get_scenario("road_trip"))
    src.advance(15 * 60)
    ems = src.emit(1_770_000_000)
    by = {}
    for s in ems:
        by.setdefault(s.source, {})[s.metric] = s.value
    check("GPS fix emitted and moving",
          by.get("gps", {}).get("speed_mph", 0) > 15,
          f"{by['gps']['speed_mph']}mph at ({by['gps']['lat']:.4f}, {by['gps']['lon']:.4f})")
    check("alternator charging while driving",
          by.get("dcc50s", {}).get("alt_power_w", 0) > 250,
          f"alt={by['dcc50s']['alt_power_w']}W")
    check("trip odometer counts",
          5.0 < by["gps"]["trip_mi"] < 12.0, f"{by['gps']['trip_mi']}mi in 15min")

    # Drive the whole route: it must park in Tofino and stop the alternator.
    src.advance(2 * 3600)
    ems2 = src.emit(1_770_100_000)
    by2 = {}
    for s in ems2:
        by2.setdefault(s.source, {})[s.metric] = s.value
    check("route ends parked (Tofino), alternator off",
          abs(by2["gps"]["speed_mph"]) < 0.5 and by2["dcc50s"]["alt_power_w"] == 0.0
          and abs(by2["gps"]["lat"] - 49.153) < 0.01,
          f"({by2['gps']['lat']:.4f}, {by2['gps']['lon']:.4f})")

    print("== HVAC control + battery coupling ==")
    ok = src.apply_command({"target": "hvac", "mode": "cool", "setpoint_c": 18})
    src.advance(120)
    ems3 = src.emit(1_770_100_200)
    hv = {s.metric: s.value for s in ems3 if s.source == "hvac"}
    check("cool command accepted; A/C drawing ~900W",
          ok and hv.get("hvac_power_w", 0) > 800,
          f"hvac={hv.get('hvac_power_w')}W")
    net_before = src.model.battery.i_net_a
    check("A/C visibly dives net battery power", net_before < -40,
          f"net={net_before:.1f}A")
    cabin_start = hv["cabin_temp_c"]
    src.advance(1800)
    ems4 = src.emit(1_770_102_000)
    cabin_now = next(s.value for s in ems4 if s.source == "hvac" and s.metric == "cabin_temp_c")
    check("cabin cools toward setpoint", cabin_now < cabin_start - 1.0,
          f"{cabin_start:.1f} → {cabin_now:.1f}°C")
    src.apply_command({"target": "hvac", "mode": "off"})
    src.advance(60)
    check("off command stops the draw", src.model.hvac_w == 0.0)

    ok = src.apply_command({"target": "sensor", "source": "gps", "offline": True})
    src.advance(30)
    ems_off = src.emit(1_770_102_100)
    gps_gone = not any(s.source == "gps" for s in ems_off)
    src.apply_command({"target": "sensor", "source": "gps", "offline": False})
    ems_back = src.emit(1_770_102_130)
    check("sensor offline toggle: gps stops emitting, then returns",
          ok and gps_gone and any(s.source == "gps" for s in ems_back))
    check("unknown sensor refused",
          src.apply_command({"target": "sensor", "source": "nope",
                             "offline": True}) is False)

    print("== charge-source switches ==")
    dv = SimSource(get_scenario("driveway"))
    dv.advance(600)
    base = {s.metric: s.value for s in dv.emit(1_770_000_600)
            if s.source in ("dcc50s",)}
    check("driveway baseline: solar producing, no alt/shore",
          base["pv_power_w"] > 50 and base["alt_power_w"] == 0.0,
          f"pv={base['pv_power_w']}W")
    dv.apply_command({"target": "charge_source", "source": "alternator", "enabled": True})
    dv.apply_command({"target": "charge_source", "source": "shore", "enabled": True})
    dv.apply_command({"target": "charge_source", "source": "solar", "enabled": False})
    dv.advance(60)
    ems_sw = dv.emit(1_770_000_660)
    sw = {s.metric: s.value for s in ems_sw if s.source == "dcc50s"}
    ctl = {s.metric: s.value for s in ems_sw if s.source == "charge_ctl"}
    check("switches: solar off kills PV at midday",
          sw["pv_power_w"] == 0.0 and ctl["solar_on"] == 0.0)
    check("switches: alternator on while parked (engine idling)",
          sw["alt_power_w"] > 300 and ctl["alternator_on"] == 1.0,
          f"alt={sw['alt_power_w']}W")
    check("switches: shore on → charging with no visible source",
          ctl["shore_on"] == 1.0 and dv.model.shore_a_actual > 0)
    dv.apply_command({"target": "charge_source", "source": "solar", "enabled": True})
    dv.apply_command({"target": "charge_source", "source": "alternator", "enabled": False})
    dv.apply_command({"target": "charge_source", "source": "shore", "enabled": False})
    dv.advance(60)
    sw2 = {s.metric: s.value for s in dv.emit(1_770_000_720) if s.source == "dcc50s"}
    check("switches: everything reverts",
          sw2["pv_power_w"] > 50 and sw2["alt_power_w"] == 0.0
          and dv.model.shore_a_actual == 0.0)
    check("unknown charge source refused",
          dv.apply_command({"target": "charge_source", "source": "fusion",
                            "enabled": True}) is False)

    print("== inverter (simulated; real unit is CAN-only) ==")
    inv_idle = {s.metric: s.value for s in ems_back if s.source == "inverter"}
    check("inverter OFF by default (van is 12V-only until switched on)",
          inv_idle.get("state") == 0.0 and inv_idle.get("ac_out_w") == 0.0)

    inv_src = SimSource(get_scenario("driveway"))
    inv_src.advance(60)
    ok_cook = inv_src.apply_command({"target": "appliance", "name": "cooktop",
                                     "on": True})
    inv_src.advance(10)
    e1 = {s.metric: s.value for s in inv_src.emit(1_770_000_070)
          if s.source == "inverter"}
    check("cooktop while inverter off → inverter auto-starts, inverting",
          ok_cook and e1.get("state") == 2.0 and e1.get("ac_out_w", 0) > 1400,
          f"state={e1.get('state')}, ac={e1.get('ac_out_w')}W")
    inv_src.apply_command({"target": "inverter", "on": False})
    inv_src.advance(10)
    e2 = {s.metric: s.value for s in inv_src.emit(1_770_000_080)
          if s.source == "inverter"}
    check("inverter off kills the outlets (cooktop drops with it)",
          e2.get("state") == 0.0 and e2.get("ac_out_w") == 0.0)

    print("== fridge / freezer smart switches ==")
    sw_src = SimSource(get_scenario("driveway"))
    sw_src.advance(3600)
    sw1 = {s.metric: s.value for s in sw_src.emit(1_770_003_600)
           if s.source == "switches"}
    check("switch states + live compressor watts emitted",
          sw1.get("fridge_on") == 1.0 and sw1.get("freezer_on") == 1.0
          and "fridge_w" in sw1 and "freezer_w" in sw1)
    ok_f = sw_src.apply_command({"target": "load_switch", "name": "fridge",
                                 "on": False})
    sw_src.advance(30)
    sw2 = {s.metric: s.value for s in sw_src.emit(1_770_003_630)
           if s.source == "switches"}
    check("fridge switch off → 0W from the fridge",
          ok_f and sw2.get("fridge_on") == 0.0 and sw2.get("fridge_w") == 0.0)
    check("freezer unaffected by fridge switch", sw2.get("freezer_on") == 1.0)
    check("unknown load switch refused",
          sw_src.apply_command({"target": "load_switch", "name": "tv",
                                "on": False}) is False)

    sp = SimSource(get_scenario("shore_power"))
    sp.advance(60)
    inv_sp = {s.metric: s.value for s in sp.emit(1_770_000_060)
              if s.source == "inverter"}
    check("BYPASS on shore power (documented van behaviour)",
          inv_sp.get("state") == 3.0)

    from sim.loads import LoadEvent
    cook_scn = dataclasses.replace(
        get_scenario("dusk_low"),
        events=(LoadEvent("cooktop", start_h=0.0, duration_min=30.0,
                          watts=1500.0, ac=True),))
    ck = SimSource(cook_scn)
    ck.advance(300)
    inv_ck = {s.metric: s.value for s in ck.emit(1_770_000_300)
              if s.source == "inverter"}
    check("cooktop → inverting, ~1500W AC / ~1720W DC",
          inv_ck.get("state") == 2.0
          and 1450 <= inv_ck.get("ac_out_w", 0) <= 1550
          and 1650 <= inv_ck.get("dc_in_w", 0) <= 1800,
          f"ac={inv_ck.get('ac_out_w')}W dc={inv_ck.get('dc_in_w')}W "
          f"({inv_ck.get('load_pct')}% of 3000W)")

    print("== POI dataset ==")
    pois = nearby_pois(49.0770, -125.8120, radius_mi=15)
    check("Tofino POIs within 15mi of Green Point",
          len(pois) >= 5 and pois[0]["dist_mi"] <= pois[-1]["dist_mi"],
          f"{len(pois)} found, nearest: {pois[0]['name']}")
    check("far POIs excluded", all(p["dist_mi"] <= 15 for p in pois))

    kirkland = nearby_pois(47.6840, -122.1965, radius_mi=8, limit=20)
    check("Kirkland position auto-selects the Kirkland dataset",
          len(kirkland) >= 5
          and any(p["name"] == "Saint Edward State Park" for p in kirkland)
          and not any("Tofino" in p["name"] or "Tacofino" in p["name"] for p in kirkland),
          f"{len(kirkland)} found, nearest: {kirkland[0]['name'] if kirkland else '-'}")

    fixes_lat = [(i * 30, 49.00 + i * 0.001) for i in range(20)]
    fixes_lon = [(i * 30, -125.60) for i in range(20)]
    check("track_miles sums a track", 1.0 < track_miles(fixes_lat, fixes_lon) < 2.0,
          f"{track_miles(fixes_lat, fixes_lon)}mi")


async def command_roundtrip() -> None:
    print("== command queue roundtrip (API process → db → poller) ==")
    db = CAPTURE_DIR / "_verify_p5_cmd.db"
    for sfx in ("", "-wal", "-shm"):
        p = Path(str(db) + sfx)
        if p.exists():
            p.unlink()
    store = await Store(db).open()
    cid = await store.enqueue_command(json.dumps({"target": "hvac", "mode": "heat"}))
    pending = await store.pending_commands()
    check("enqueued command is pending", len(pending) == 1 and pending[0][0] == cid)
    src = SimSource(get_scenario("dusk_low"))
    ok = src.apply_command(json.loads(pending[0][1]))
    await store.mark_command(cid, ok)
    check("sim applies; queue drains",
          ok and (await store.pending_commands()) == []
          and src.model.hvac.mode == 1.0)
    await store.close()


def api_checks() -> None:
    print("== API: alerts, hvac gate, trip ==")
    db = CAPTURE_DIR / "_verify_p5_api.db"
    asyncio.run(seed(db, "dusk_low", 8.0))    # 8h drain → SOC ~27% → alert fires
    app = create_app({"source": "sim", "db_path": str(db)})
    with TestClient(app) as c:
        alerts = c.get("/api/alerts").json()["alerts"]
        check("low battery raises an alert",
              any(a["id"] == "soc" for a in alerts),
              "; ".join(a["message"] for a in alerts) or "none")
        r = c.post("/api/hvac", json={"mode": "cool", "setpoint_c": 19})
        check("hvac command queues on sim", r.status_code == 200 and "queued" in r.json())
        check("human command audited as HUMAN",
              any(e["tool"] == "ui_set_climate" and e["device"] == "HUMAN"
                  for e in c.get("/api/audit").json()["entries"]))
        trip = c.get("/api/trip").json()
        check("trip endpoint: fix + nearby POIs",
              trip["fix"] is not None and len(trip["nearby"]) >= 3
              and trip["fix"]["moving"] is False,
              f"{len(trip.get('nearby', []))} POIs")
        bad = c.post("/api/hvac", json={"mode": "melt"})
        check("bad hvac mode rejected", bad.status_code == 422)

    app_live = create_app({"source": "live", "db_path": str(db)})
    with TestClient(app_live) as c:
        r = c.post("/api/hvac", json={"mode": "cool"})
        check("hvac REFUSED when source is live (phase-2 gate)",
              r.status_code == 403)


def voice_checks() -> None:
    print("== offline voice: SAPI TTS → OpenVINO Whisper (loads model) ==")
    wav_path = Path(tempfile.gettempdir()) / "vanguard_stt_test.wav"
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, 'Sixteen', 'Mono'); "
        f"$s.SetOutputToWaveFile('{wav_path}', $fmt); "
        "$s.Speak('What is my battery level right now?'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True, timeout=60)
    db = CAPTURE_DIR / "_verify_p5_api.db"
    app = create_app({"source": "sim", "db_path": str(db)})
    with TestClient(app) as c:
        r = c.post("/api/transcribe", content=wav_path.read_bytes())
        check("transcribe endpoint 200", r.status_code == 200,
              f"{r.status_code}" if r.status_code != 200 else "")
        if r.status_code == 200:
            text = r.json()["text"].lower()
            check("Whisper heard the question", "battery" in text,
                  f"transcript: '{r.json()['text']}'")
            check("served on-device", r.json()["device"] in ("GPU", "CPU"),
                  r.json()["device"])
        r2 = c.post("/api/transcribe", content=b"x" * 100)
        check("garbage audio rejected", r2.status_code == 400)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-voice", action="store_true")
    a = ap.parse_args()
    sim_checks()
    asyncio.run(command_roundtrip())
    api_checks()
    if not a.skip_voice:
        voice_checks()
    fails = [x for x in CHECKS if not x[1]]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
