"""vanguard-api — FastAPI telemetry routes + the dashboard (PLAN.md §7).

Run:  python -m uvicorn api.main:app --port 8000

Separate process from the poller on purpose: a crashed model service must
never cost telemetry history. This process only *reads* the SQLite database
the poller writes (WAL lets the two coexist without blocking).

Integrity guardrail (CLAUDE.md, non-negotiable): every payload carries
``"simulated"`` — true unless the configured source is ``live`` — and the
dashboard renders a persistent SIM badge from it. A screenshot must never be
able to misrepresent simulated data as live van data.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from poller import derived
from poller.config import load_config
from poller.store import RAW_RETENTION_S, Store
from sim.gps import haversine_mi, nearby_pois

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Header chip goes stale after this many seconds without a fresh sample.
STALE_AFTER_S = 30


class HvacCommand(BaseModel):
    mode: Literal["off", "heat", "cool"] | None = None
    setpoint_c: float | None = Field(default=None, ge=10, le=32)


DEFAULT_ALERT_RULES = {
    "soc_warn_pct": 30.0,
    "soc_crit_pct": 15.0,
    "tte_warn_h": 4.0,
    "volt_warn": 12.2,
    "volt_crit": 11.8,
}


def evaluate_alerts(readings: dict, overrides: dict, stale: bool) -> list[dict]:
    rules = {**DEFAULT_ALERT_RULES, **overrides}
    dv = derived.all_derived(readings)
    soc = readings.get("shunt", {}).get("soc_pct", (0, None))[1]
    volts = readings.get("shunt", {}).get("voltage_v", (0, None))[1]
    out = []

    def alert(aid, severity, message):
        out.append({"id": aid, "severity": severity, "message": message})

    if stale:
        alert("stale", "warning", "telemetry is stale - check the poller")
    if soc is not None:
        if soc <= rules["soc_crit_pct"]:
            alert("soc", "critical", f"battery critical: {soc:.0f}%")
        elif soc <= rules["soc_warn_pct"]:
            alert("soc", "warning", f"battery low: {soc:.0f}%")
    tte = dv.get("time_to_empty_h")
    if tte is not None and tte <= rules["tte_warn_h"]:
        alert("tte", "warning", f"~{tte:.1f}h to empty at current draw")
    if volts is not None:
        if volts <= rules["volt_crit"]:
            alert("volts", "critical", f"voltage sagging: {volts:.2f}V")
        elif volts <= rules["volt_warn"]:
            alert("volts", "warning", f"voltage low: {volts:.2f}V")
    return out


def track_miles(lat_hist: list, lon_hist: list) -> float:
    """Distance along today's GPS track.

    Stride caps the point count; the teleport filter only drops genuinely
    impossible jumps (>5mi between fixes) — poll-cadence stretches under
    load produce multi-minute gaps that are still real driving.
    """
    lons = dict(lon_hist)
    fixes = [(ts, lat, lons[ts]) for ts, lat in lat_hist if ts in lons]
    stride = max(1, len(fixes) // 600)
    fixes = fixes[::stride]
    total = 0.0
    for (_, la1, lo1), (_, la2, lo2) in zip(fixes, fixes[1:]):
        d = haversine_mi(la1, lo1, la2, lo2)
        if d < 5.0:
            total += d
    return round(total, 1)


def create_app(cfg: dict | None = None) -> FastAPI:
    cfg = cfg if cfg is not None else load_config()
    simulated = cfg["source"] != "live"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = await Store(cfg.get("db_path", "vanguard.db")).open()
        try:
            yield
        finally:
            await app.state.store.close()

    app = FastAPI(title="VanGuard", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.simulated = simulated
    app.state.engine = None
    app.state.stt = None
    app.state.stt_lock = asyncio.Lock()

    from api.chat import router as chat_router
    app.include_router(chat_router)

    def stamp(payload: dict) -> dict:
        payload["simulated"] = simulated
        payload["source_kind"] = cfg["source"]
        payload["server_ts"] = int(time.time())
        return payload

    @app.get("/api/status")
    async def status():
        latest = await app.state.store.latest()
        newest = max(
            (ts for per in latest.values() for ts, _ in per.values()),
            default=None,
        )
        now = int(time.time())
        return stamp({
            "latest_sample_ts": newest,
            "staleness_s": None if newest is None else max(0, now - newest),
            "stale": newest is None or (now - newest) > STALE_AFTER_S,
        })

    @app.get("/api/telemetry/latest")
    async def latest():
        readings = await app.state.store.latest()
        return stamp({
            "readings": {
                src: {m: {"ts": ts, "value": v} for m, (ts, v) in per.items()}
                for src, per in readings.items()
            },
            "derived": derived.all_derived(readings),
        })

    @app.get("/api/telemetry/history")
    async def history(
        source: str = Query(pattern="^(shunt|dcc50s)$"),
        metric: str = Query(min_length=1, max_length=64),
        window_s: int = Query(default=24 * 3600, ge=60, le=30 * 24 * 3600),
        max_points: int = Query(default=300, ge=10, le=5000),
    ):
        points = await app.state.store.history(source, metric, window_s)
        return stamp({
            "source": source,
            "metric": metric,
            "window_s": window_s,
            "resolution": "raw" if window_s <= RAW_RETENTION_S else "1m",
            "points": _decimate(points, max_points),
        })

    @app.get("/api/audit")
    async def audit(limit: int = Query(default=50, ge=1, le=500)):
        return stamp({"entries": await app.state.store.audit_recent(limit)})

    # -- P5 demo mode ----------------------------------------------------------

    @app.get("/api/alerts")
    async def alerts():
        readings = await app.state.store.latest()
        return stamp({"alerts": evaluate_alerts(
            readings, cfg.get("alerts", {}),
            (await status())["stale"])})

    @app.post("/api/hvac")
    async def hvac(body: HvacCommand):
        # Actuation is demo-only: human-initiated, sim-gated. A live source
        # refuses at the poller too (phase-1 read-only, defense in depth).
        if cfg["source"] != "sim":
            raise HTTPException(
                403, "climate control is phase 2 - only the simulator "
                     "accepts commands in v1")
        payload = {"target": "hvac", **body.model_dump(exclude_none=True)}
        cmd_id = await app.state.store.enqueue_command(json.dumps(payload))
        await app.state.store.audit(
            tool="ui_set_climate", args_json=json.dumps(payload),
            result_hash="-", device="HUMAN", duration_ms=0)
        return stamp({"queued": cmd_id,
                      "note": "applied by the poller within one poll interval"})

    @app.get("/api/trip")
    async def trip(radius_mi: float = Query(default=15.0, ge=1, le=100)):
        readings = await app.state.store.latest()
        gps = {m: v for m, (ts, v) in readings.get("gps", {}).items()}
        if not gps:
            return stamp({"fix": None})
        lat_hist = await app.state.store.history("gps", "lat", 24 * 3600)
        lon_hist = await app.state.store.history("gps", "lon", 24 * 3600)
        return stamp({
            "fix": {"lat": gps.get("lat"), "lon": gps.get("lon"),
                    "speed_mph": gps.get("speed_mph"),
                    "heading_deg": gps.get("heading_deg"),
                    "moving": (gps.get("speed_mph") or 0) > 2.0},
            "miles_today": track_miles(lat_hist, lon_hist),
            "nearby": nearby_pois(gps["lat"], gps["lon"], radius_mi),
        })

    @app.post("/api/transcribe")
    async def transcribe(request: Request):
        wav = await request.body()
        if len(wav) < 1000:
            raise HTTPException(400, "no audio")
        if len(wav) > 10_000_000:
            raise HTTPException(413, "clip too long")
        async with app.state.stt_lock:
            if app.state.stt is None:
                from inference.stt import SttEngine
                stt_dir = Path(__file__).resolve().parent.parent / cfg.get(
                    "stt", {}).get("model_dir", "ov_whisper_base_en")
                if not (stt_dir / "openvino_encoder_model.xml").exists():
                    raise HTTPException(503, f"whisper not exported: {stt_dir}")
                app.state.stt = await run_in_threadpool(SttEngine, str(stt_dir))
        try:
            text = await run_in_threadpool(app.state.stt.transcribe_wav, wav)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return stamp({"text": text, "device": app.state.stt.device})

    @app.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def _decimate(points: list[tuple[int, float]], max_points: int) -> list[list[float]]:
    """Bucket-mean decimation so 24h of 5s samples doesn't ship 17k points."""
    if len(points) <= max_points:
        return [[t, v] for t, v in points]
    out = []
    n = len(points)
    for k in range(max_points):
        lo, hi = k * n // max_points, (k + 1) * n // max_points
        if hi <= lo:
            continue
        bucket = points[lo:hi]
        out.append([
            bucket[len(bucket) // 2][0],
            sum(v for _, v in bucket) / len(bucket),
        ])
    return out


app = create_app()
