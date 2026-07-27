"""PowerCalculationService — deterministic forecasts (P6, review adoption).

All arithmetic lives here, server-side, never in the UI and never in the
model. Estimates are conservative, list their assumptions, and carry a
confidence that degrades honestly with data quality.

Defaults match the van's actual hardware (300Ah × 12.8V = 3,840Wh usable
nameplate — not the review's generic 5kWh), overridable in config.
"""
from __future__ import annotations

import math
import time

from poller import derived
from sim.van_model import SUNRISE_H, SUNSET_H

DEFAULTS = {
    "capacity_wh": 3840.0,       # 300Ah @ 12.8V [verified — OGA invoice]
    "reserve_pct": 20.0,
    "inverter_efficiency": 0.88,
}


def _get(readings: dict, source: str, metric: str):
    try:
        return readings[source][metric][1]
    except (KeyError, TypeError):
        return None


def _age_s(readings: dict, source: str, now: int) -> float | None:
    per = readings.get(source, {})
    if not per:
        return None
    return max(0.0, now - max(ts for ts, _ in per.values()))


def solar_remaining_wh(now_hour: float, current_pv_w: float,
                       peak_today_w: float) -> float:
    """Clear-sky-shaped estimate of solar left today.

    Integrates the same bell the sim uses (sin^1.5 between sunrise/sunset),
    scaled to today's observed peak — deterministic and honest about being
    shape-based, not weather-aware.
    """
    if peak_today_w <= 0 or now_hour >= SUNSET_H:
        return 0.0
    start = max(now_hour, SUNRISE_H)
    total = 0.0
    step_h = 0.25
    h = start
    while h < SUNSET_H:
        x = math.sin(math.pi * (h - SUNRISE_H) / (SUNSET_H - SUNRISE_H))
        total += peak_today_w * (x ** 1.5) * step_h
        h += step_h
    return total


def compute_outlook(readings: dict, pv_history: list[tuple[int, float]],
                    cfg: dict, horizon_h: float | None = None,
                    now: int | None = None) -> dict:
    now = int(now if now is not None else time.time())
    p = {**DEFAULTS, **(cfg.get("power") or {})}
    capacity_wh = float(p["capacity_wh"])
    reserve_pct = float(p["reserve_pct"])

    dv = derived.all_derived(readings)
    soc = _get(readings, "shunt", "soc_pct")
    net_w = dv.get("net_power_w")
    load_w = dv.get("load_w")
    pv_w = _get(readings, "dcc50s", "pv_power_w") or 0.0

    issues = []
    shunt_age = _age_s(readings, "shunt", now)
    if shunt_age is None or shunt_age > 60:
        issues.append("battery readings stale")
    if soc is None or net_w is None:
        return {"available": False,
                "reason": "insufficient data for forecast",
                "issues": issues}

    # Local clock hour — the sim and the demo share the machine's timezone.
    lt = time.localtime(now)
    now_hour = lt.tm_hour + lt.tm_min / 60.0

    peak_today = max((v for _, v in pv_history), default=0.0)
    remaining_solar_wh = solar_remaining_wh(now_hour, pv_w, peak_today)

    reserve_wh = capacity_wh * reserve_pct / 100.0
    stored_wh = capacity_wh * soc / 100.0
    above_reserve_wh = max(0.0, stored_wh - reserve_wh)

    # Source persistence matters: solar dies at sunset, but the alternator
    # keeps charging as long as the engine runs and shore as long as the
    # cord is in. Forecasting "0% by sunrise" while the engine covers the
    # whole system would be wrong.
    alt_w = _get(readings, "dcc50s", "alt_power_w") or 0.0
    persistent_source = alt_w > 25 or derived.shore_power_suspected(readings)

    # Runtime to reserve at the current net rate (persistent sources count;
    # while charging there is no countdown).
    runtime_to_reserve_h = None
    if net_w < -5:
        runtime_to_reserve_h = above_reserve_wh / -net_w

    hours_to_sunrise = ((SUNRISE_H - now_hour) % 24.0) or 24.0

    if persistent_source:
        # Engine/shore charging continues: project the current NET rate.
        soc_at_sunrise = stored_wh + net_w * hours_to_sunrise
        overnight_use_wh = max(0.0, -net_w) * hours_to_sunrise
        discretionary_wh = above_reserve_wh
    else:
        # Off-grid: loads continue all night, solar only until sunset.
        drain_w = load_w if load_w is not None else max(0.0, -net_w)
        overnight_use_wh = drain_w * hours_to_sunrise
        soc_at_sunrise = stored_wh - overnight_use_wh + remaining_solar_wh
        discretionary_wh = max(0.0, above_reserve_wh - overnight_use_wh
                               + remaining_solar_wh)
    soc_at_sunrise_pct = max(0.0, min(100.0, soc_at_sunrise / capacity_wh * 100.0))

    horizon = float(horizon_h) if horizon_h else hours_to_sunrise
    soc_at_horizon = (stored_wh + (net_w * horizon)) / capacity_wh * 100.0
    soc_at_horizon_pct = max(0.0, min(100.0, soc_at_horizon))

    if issues:
        confidence = "low"
    elif persistent_source:
        confidence = "medium"     # assumes the engine/cord stays on
    elif remaining_solar_wh > 0:
        confidence = "medium"     # shape-based solar estimate, no weather
    else:
        confidence = "high"       # pure coulomb math, no solar uncertainty

    return {
        "available": True,
        "soc_pct": round(soc, 0),
        "net_power_w": round(net_w, 0),
        "solar_surplus_w": round((pv_w or 0.0) - (load_w or 0.0), 0)
        if load_w is not None else None,
        "runtime_to_reserve_h": round(runtime_to_reserve_h, 1)
        if runtime_to_reserve_h is not None else None,
        "hours_to_sunrise": round(hours_to_sunrise, 1),
        "soc_at_sunrise_pct": round(soc_at_sunrise_pct, 0),
        "reserve_ok_overnight": bool(soc_at_sunrise_pct > reserve_pct),
        "soc_at_horizon_pct": round(soc_at_horizon_pct, 0),
        "horizon_h": round(horizon, 1),
        "discretionary_wh": round(discretionary_wh, 0),
        "remaining_solar_wh": round(remaining_solar_wh, 0),
        "confidence": confidence,
        "issues": issues,
        "assumptions": {
            "capacity_wh": capacity_wh,
            "reserve_pct": reserve_pct,
            "load_basis_w": round(overnight_use_wh / hours_to_sunrise, 0),
            "persistent_charging": persistent_source,
            "note": ("assumes alternator/shore charging stays on"
                     if persistent_source else
                     "assumes loads continue; solar ends at sunset"),
            "solar_model": "clear-sky bell scaled to today's observed peak",
            "sunrise_h": SUNRISE_H, "sunset_h": SUNSET_H,
        },
    }
