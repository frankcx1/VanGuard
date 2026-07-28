"""P8 verification — VanGuard Guardian autonomy.

Deterministic; the LLM is never in the Guardian loop, so no model needed.

Run:  .venv\\Scripts\\python.exe scripts\\verify_p8.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from api.guardian import Guardian
from api.main import create_app
from poller.store import Store
from verify_p2 import seed

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "sim" / "captures"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def rd(now: int, **sources) -> dict:
    return {src: {m: (now, v) for m, v in metrics.items()}
            for src, metrics in sources.items()}


def detector_checks() -> None:
    print("== detectors (pure rules) ==")
    g = Guardian(SimpleNamespace(state=None))
    now = int(time.time())

    sag = g.detect_voltage_sag(rd(now, shunt={"voltage_v": 11.85},
                                  inverter={"ac_out_w": 1500.0}))
    check("voltage sag interlock fires <12V under heavy AC",
          sag is not None and sag["severity"] == "critical"
          and sag["actions"] == ["stop_cooktop"])
    check("no sag trip at healthy voltage",
          g.detect_voltage_sag(rd(now, shunt={"voltage_v": 12.9},
                                  inverter={"ac_out_w": 1500.0})) is None)

    gap = g.detect_alternator_gap(rd(now, gps={"speed_mph": 45.0},
                                     dcc50s={"alt_power_w": 0.0}))
    check("alternator gap while moving → advisory with NO actions (restraint)",
          gap is not None and gap["actions"] == [] and gap["severity"] == "advisory")

    check("conflicting sensors → confidence low",
          g.data_confidence_low(rd(now, shunt={"current_a": 5.0,
                                               "power_w": -80.0}), now)
          is not None)
    check("fresh consistent sensors → confidence ok",
          g.data_confidence_low(rd(now, shunt={"current_a": 5.0,
                                               "power_w": 66.0}), now) is None)


def flow_checks() -> None:
    print("== protect-level episode: detect → verify → decide → act → confirm ==")
    db = CAPTURE_DIR / "_verify_p8.db"
    asyncio.run(seed(db, "overnight_guardian", 1.0))
    app = create_app({"source": "sim", "db_path": str(db),
                      "inference": {"model_dir": "ov_nonexistent"},
                      "watchdog": {"interval_min": 0},
                      "guardian": {"interval_s": 0}})
    with TestClient(app) as c:
        g0 = c.get("/api/guardian").json()
        check("guardian armed at protect on sim", g0["armed"] is True
              and g0["level"] == "protect", g0["level"])
        check("policy lists never-autonomous class",
              any("BMS" in n for n in g0["never"]))

        c.post("/api/guardian/run")                  # detection 1 (hysteresis)
        s1 = c.get("/api/guardian").json()
        check("first detection does not act (hysteresis)",
              s1["active"] is None)

        c.post("/api/guardian/run")                  # detection 2 → episode
        s2 = c.get("/api/guardian").json()
        stages = [e["stage"] for e in s2["events"]]
        check("episode ran: detected/verified/decided/acted all logged",
              all(x in stages for x in ("detected", "verified", "decided", "acted")),
              str(stages[:6]))
        check("reserve risk named with policy numbers",
              any("reserve" in e["title"].lower() for e in s2["events"]))
        check("plan shed Starlink + idle inverter",
              any("Starlink" in e["detail"] and "inverter" in e["detail"].lower()
                  for e in s2["events"] if e["stage"] == "decided"))

        # Actions must be real commands in the audited queue.
        async def pending():
            st = await Store(db).open()
            try:
                return await st.pending_commands()
            finally:
                await st.close()
        cmds = asyncio.run(pending())
        check("actions enqueued through the sim-gated command queue",
              len(cmds) >= 2 and any('"network"' in p for _, p in cmds)
              and any('"inverter"' in p for _, p in cmds), f"{len(cmds)} pending")
        audit = c.get("/api/audit").json()["entries"]
        check("guardian actions audited as GUARDIAN",
              sum(1 for e in audit if e["device"] == "GUARDIAN") >= 2)

        time.sleep(9)                                # verification window
        c.post("/api/guardian/run")
        s3 = c.get("/api/guardian").json()
        check("confirmation stage records before/after",
              any(e["stage"] == "confirmed" and "→" in e["detail"]
                  and "battery net power" in e["detail"]
                  for e in s3["events"]))
        # P10: the camera-ready event card, assembled from logged events only.
        card = s3.get("card")
        check("event card present during the episode", card is not None)
        if card:
            check("card carries the executed actions + savings",
                  len(card["actions"]) >= 2 and (card["savings_w"] or 0) > 0,
                  f"{card['actions']} ~{card['savings_w']}W")
            check("card risk lines include sunrise SOC vs reserve",
                  any("sunrise" in k for k, _ in card["risk"])
                  and any("reserve" in k for k, _ in card["risk"]))
            check("card result verified from the confirmed event",
                  card["result"] is not None
                  and card["result"]["net_after_w"] is not None)
            check("decision receipt: evidence, policy, deterministic AI, 0 external",
                  "readings" in card["receipt"]["evidence"]
                  and "deterministic" in card["receipt"]["ai"]
                  and card["receipt"]["external"] == "0 external calls",
                  card["receipt"]["policy"])
        c.post("/api/guardian/run")
        n_eps = len({e["episode"] for e in
                     c.get("/api/guardian").json()["events"]
                     if e["stage"] == "detected"})
        check("no episode spam while risk persists", n_eps == 1, f"{n_eps} episodes")

    print("== ask level: proposal + human approval ==")
    db2 = CAPTURE_DIR / "_verify_p8_ask.db"
    asyncio.run(seed(db2, "overnight_guardian", 1.0))
    app2 = create_app({"source": "sim", "db_path": str(db2),
                       "inference": {"model_dir": "ov_nonexistent"},
                       "watchdog": {"interval_min": 0},
                       "guardian": {"interval_s": 0,
                                    "default_level": "ask"}})
    with TestClient(app2) as c:
        c.post("/api/guardian/run")
        c.post("/api/guardian/run")
        s = c.get("/api/guardian").json()
        check("ask level → proposal, nothing executed",
              s["active"] is not None and s["active"]["stage"] == "proposed")
        async def pending2():
            st = await Store(db2).open()
            try:
                return await st.pending_commands()
            finally:
                await st.close()
        check("no commands before approval", len(asyncio.run(pending2())) == 0)
        r = c.post("/api/guardian/approve")
        check("approval executes the prepared plan",
              r.json()["approved"] is True
              and len(asyncio.run(pending2())) >= 1)

    print("== observe level: log only ==")
    db3 = CAPTURE_DIR / "_verify_p8_obs.db"
    asyncio.run(seed(db3, "overnight_guardian", 1.0))
    app3 = create_app({"source": "sim", "db_path": str(db3),
                       "inference": {"model_dir": "ov_nonexistent"},
                       "watchdog": {"interval_min": 0},
                       "guardian": {"interval_s": 0,
                                    "default_level": "observe"}})
    with TestClient(app3) as c:
        c.post("/api/guardian/run")
        c.post("/api/guardian/run")
        s = c.get("/api/guardian").json()
        check("observe: risk logged, would-have plan named, no action",
              any(e["stage"] == "decided" and "observe" in e["detail"]
                  for e in s["events"]))
        async def pending3():
            st = await Store(db3).open()
            try:
                return await st.pending_commands()
            finally:
                await st.close()
        check("observe: command queue untouched",
              len(asyncio.run(pending3())) == 0)


def main() -> int:
    detector_checks()
    flow_checks()
    fails = [x for x in CHECKS if not x[1]]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
