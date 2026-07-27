"""Watchdog: scheduled autonomous patrols (P7).

Every ``watchdog.interval_min`` the API process runs a patrol:

1. Gather current state through the audited read-only tools (so every
   patrol shows up in the tool audit like any other consumer).
2. Deterministic rules render the verdict: status level, findings,
   recommendation — the same insight/outlook/alert services the UI uses.
3. If the local model is loaded, it writes the one-sentence report FROM
   those verified findings (language layer only, as everywhere else).
   No model → the deterministic summary stands.
4. The report is logged to the ``patrols`` table with a timestamp.

That makes the claim on camera literally true: the AI checks the whole
system on a schedule, writes a report, and every check is logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from starlette.concurrency import run_in_threadpool

from api.insight import compute_insight
from api.outlook import compute_outlook
from api.tools import ToolRunner

log = logging.getLogger("vanguard.watchdog")

PATROL_TOOLS = ("get_battery_state", "get_solar_state", "get_loads",
                "get_climate", "get_network")

SUMMARY_PROMPT = (
    "You are VanGuard's watchdog. Write a 1-2 sentence patrol report from "
    "these verified findings. Use only numbers that appear below; plain "
    "sentences, no markdown, no advice beyond the recommendation given.\n"
)


def _status_from_alerts(alerts: list[dict]) -> str:
    sevs = {a["severity"] for a in alerts}
    if "critical" in sevs:
        return "critical"
    if "warning" in sevs:
        return "warning"
    if sevs:                      # advisory / data-quality / info
        return "attention"
    return "nominal"


async def run_patrol(app) -> dict:
    from api.main import cfg_for_mode, evaluate_alerts   # late import: no cycle
    t0 = time.perf_counter()
    store = app.state.store
    mode = (await store.get_meta("operating_mode")) or "camp"
    cfg = cfg_for_mode(app.state.cfg, mode)
    runner = ToolRunner(store)

    checks = {}
    for name in PATROL_TOOLS:
        checks[name.removeprefix("get_")] = await runner.call(
            name, {}, device="WATCHDOG")

    readings = await store.latest()
    pv_hist = await store.history("dcc50s", "pv_power_w", 24 * 3600)
    outlook = compute_outlook(readings, pv_hist, cfg)
    insight = compute_insight(readings, outlook, cfg)
    now = int(time.time())
    newest = max((ts for per in readings.values() for ts, _ in per.values()),
                 default=None)
    stale = newest is None or (now - newest) > 30
    alerts = evaluate_alerts(readings, cfg.get("alerts", {}), stale,
                             outlook=outlook)
    status = _status_from_alerts(alerts)

    findings = {
        "status": status,
        "insight": insight["summary"],
        "recommendation": insight.get("recommendation"),
        "data_quality": insight.get("data_quality"),
        "alerts": [f"{a['severity']}: {a['message']}" for a in alerts],
        "soc_at_sunrise_pct": outlook.get("soc_at_sunrise_pct"),
        "readings_checked": sum(len(p) for p in readings.values()),
        "all_fresh": not stale,
    }

    summary = insight["summary"]
    if insight.get("recommendation"):
        summary += " " + insight["recommendation"]
    source = "rules"

    engine = getattr(app.state, "engine", None)
    tokenizer = getattr(app.state, "chat_tokenizer", None)
    if engine is not None and tokenizer is not None \
            and (cfg.get("watchdog") or {}).get("use_model", True):
        try:
            prompt = tokenizer.apply_chat_template(
                [{"role": "system", "content": SUMMARY_PROMPT},
                 {"role": "user", "content": json.dumps(findings)}],
                add_generation_prompt=True, tokenize=False)
            gen = await run_in_threadpool(engine.generate, prompt, 90, 0.0)
            text = gen.text.strip()
            if 20 < len(text) < 600:
                summary = text
                source = f"rules + local model ({engine.device})"
        except Exception as e:          # model trouble never breaks a patrol
            log.warning("patrol summary generation failed: %s", e)

    duration_ms = int((time.perf_counter() - t0) * 1000)
    await store.add_patrol(status, summary, json.dumps(findings), source,
                           duration_ms)
    await store.audit(tool="watchdog_patrol",
                      args_json=json.dumps({"tools": len(PATROL_TOOLS)}),
                      result_hash=status, device="WATCHDOG",
                      duration_ms=duration_ms)
    return {"ts": now, "status": status, "summary": summary,
            "source": source, "duration_ms": duration_ms}


async def watchdog_loop(app, interval_min: float) -> None:
    await asyncio.sleep(15)          # let the poller lay down fresh samples
    while True:
        try:
            report = await run_patrol(app)
            log.info("patrol: %s (%s, %dms)", report["status"],
                     report["source"], report["duration_ms"])
        except Exception as e:
            log.warning("patrol failed: %s", e)
        await asyncio.sleep(max(60.0, interval_min * 60.0))
