"""P2 verification harness — API routes + integrity stamps against a seeded db.

Run:  .venv\\Scripts\\python.exe scripts\\verify_p2.py
Exits non-zero on any FAIL.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from api.main import create_app
from poller.store import Store
from sim.scenarios import get_scenario
from sim.van_model import SimSource

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "sim" / "captures"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


async def seed(db_path: Path, scenario: str, hours: float, cadence_s: int = 30) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    src = SimSource(get_scenario(scenario))
    store = await Store(db_path).open()
    now = int(time.time())
    steps = int(hours * 3600 / cadence_s)
    start = now - steps * cadence_s
    batch = []
    for k in range(steps):
        src.advance(cadence_s)
        batch.extend(src.emit(start + (k + 1) * cadence_s))
    await store.write(batch)
    await store.downsample(now=now)
    await store.close()


def main() -> int:
    print("== seeded sunny_midday 24h ==")
    db = CAPTURE_DIR / "_verify_p2.db"
    asyncio.run(seed(db, "sunny_midday", 24.0))
    app = create_app({"source": "sim", "db_path": str(db)})

    with TestClient(app) as c:
        s = c.get("/api/status").json()
        check("status: fresh data not stale", s["stale"] is False,
              f"staleness={s['staleness_s']}s")

        latest = c.get("/api/telemetry/latest").json()
        rd = latest["readings"]
        check("latest: shunt + dcc50s present", "shunt" in rd and "dcc50s" in rd)
        check("latest: SOC present", "soc_pct" in rd.get("shunt", {}))
        check("latest: derived bundle present",
              set(latest["derived"]) >= {"net_power_w", "load_w", "time_to_empty_h"})

        for path in ("/api/status", "/api/telemetry/latest",
                     "/api/telemetry/history?source=shunt&metric=soc_pct"):
            payload = c.get(path).json()
            if payload.get("simulated") is not True:
                check(f"integrity stamp on {path}", False, str(payload.get("simulated")))
                break
        else:
            check("integrity guardrail: simulated=true stamped on every payload", True)

        h = c.get("/api/telemetry/history", params={
            "source": "shunt", "metric": "soc_pct", "window_s": 24 * 3600}).json()
        check("history: 24h raw series, decimated",
              h["resolution"] == "raw" and 250 <= len(h["points"]) <= 300,
              f"{len(h['points'])} pts")

        h1m = c.get("/api/telemetry/history", params={
            "source": "shunt", "metric": "soc_pct", "window_s": 72 * 3600}).json()
        check("history: >48h window served from 1m downsamples",
              h1m["resolution"] == "1m" and len(h1m["points"]) > 100,
              f"{len(h1m['points'])} pts")

        check("history: bad source rejected",
              c.get("/api/telemetry/history",
                    params={"source": "nope", "metric": "x"}).status_code == 422)

        idx = c.get("/")
        check("dashboard served at /",
              idx.status_code == 200 and "SIM" in idx.text and "VanGuard" in idx.text)
        check("static assets served",
              c.get("/static/app.js").status_code == 200
              and c.get("/static/style.css").status_code == 200)

    print("== seeded shore_power 1h ==")
    db2 = CAPTURE_DIR / "_verify_p2_shore.db"
    asyncio.run(seed(db2, "shore_power", 1.0))
    app2 = create_app({"source": "sim", "db_path": str(db2)})
    with TestClient(app2) as c:
        dv = c.get("/api/telemetry/latest").json()["derived"]
        check("shore power: suspected from observables",
              dv["shore_power_suspected"] is True)
        check("shore power: load_w honestly null over the API",
              dv["load_w"] is None)
        check("shore power: charging is visible at the shunt",
              (dv["net_power_w"] or 0) > 100, f"net={dv['net_power_w']}W")

    fails = [x for x in CHECKS if not x[1]]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
