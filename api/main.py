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

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from poller import derived
from poller.config import load_config
from poller.store import RAW_RETENTION_S, Store

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Header chip goes stale after this many seconds without a fresh sample.
STALE_AFTER_S = 30


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
