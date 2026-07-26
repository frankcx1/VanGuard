"""Phase-1 tool implementations (PLAN.md §7) — read only, always audited.

The AI can see everything and touch nothing: every tool here is a read
against the telemetry store. No write registers exist anywhere in this
module, and every invocation is logged to ``tool_audit`` — the log is the
governance story, not an afterthought.

Context discipline (PLAN.md §6): the NPU serves a 2–4k static context, so
tools return numbers and units, never prose. ``get_history`` returns
summary stats, not series.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from poller import derived
from poller.store import Store
from sim.van_model import CAPACITY_AH

NOMINAL_V = 12.8
USABLE_FLOOR_SOC = 20.0          # advisory floor for runtime estimates

# metric name the model uses → (device, stored metric)
HISTORY_METRICS = {
    "soc": ("shunt", "soc_pct"),
    "voltage": ("shunt", "voltage_v"),
    "net_power": ("shunt", "power_w"),
    "pv_power": ("dcc50s", "pv_power_w"),
}


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(x, nd)


class ToolRunner:
    """Executes named tools against the store; audits every call."""

    def __init__(self, store: Store):
        self.store = store

    async def call(self, name: str, args: dict, device: str | None) -> dict:
        t0 = time.perf_counter()
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            result = {"error": f"unknown tool '{name}'"}
        else:
            try:
                result = await fn(**args)
            except TypeError as e:
                result = {"error": f"bad arguments: {e}"}
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {e}"}
        duration_ms = int((time.perf_counter() - t0) * 1000)
        result_json = json.dumps(result, separators=(",", ":"))
        await self.store.audit(
            tool=name,
            args_json=json.dumps(args, separators=(",", ":")),
            result_hash=hashlib.sha256(result_json.encode()).hexdigest()[:16],
            device=device,
            duration_ms=duration_ms,
        )
        return result

    # -- the six tools ---------------------------------------------------------

    async def tool_get_battery_state(self) -> dict:
        rd = await self.store.latest()
        sh = {m: v for m, (ts, v) in rd.get("shunt", {}).items()}
        if not sh:
            return {"error": "no shunt data"}
        return {
            "soc_pct": _r(sh.get("soc_pct"), 0),
            "voltage_v": _r(sh.get("voltage_v"), 2),
            "current_a": _r(sh.get("current_a"), 1),
            "power_w": _r(sh.get("power_w"), 0),
            "temp_c": _r(sh.get("temp_c"), 0),
            "capacity_ah": CAPACITY_AH,
            "time_to_empty_h": _r(derived.time_to_empty_h(rd)),
            "time_to_full_h": _r(derived.time_to_full_h(rd)),
        }

    async def tool_get_solar_state(self) -> dict:
        rd = await self.store.latest()
        dc = {m: v for m, (ts, v) in rd.get("dcc50s", {}).items()}
        if not dc:
            return {"error": "no charge-controller data"}
        return {
            "pv_w": _r(dc.get("pv_power_w"), 0),
            "yield_today_wh": _r(dc.get("daily_yield_wh"), 0),
            "alternator_w": _r(dc.get("alt_power_w"), 0),
        }

    async def tool_get_loads(self) -> dict:
        rd = await self.store.latest()
        load = derived.load_w(rd)
        if load is None:
            return {
                "load_w": None,
                "reason": ("shore power suspected - charger is invisible to "
                           "telemetry, load underivable")
                if derived.shore_power_suspected(rd) else "no data",
            }
        return {"load_w": _r(load, 0), "note": "aggregate DC load; no per-circuit breakdown"}

    async def tool_get_history(self, metric: str, window_h: float = 24) -> dict:
        if metric not in HISTORY_METRICS:
            return {"error": f"metric must be one of {sorted(HISTORY_METRICS)}"}
        window_h = max(0.25, min(48.0, float(window_h)))
        source, stored = HISTORY_METRICS[metric]
        pts = await self.store.history(source, stored, int(window_h * 3600))
        if not pts:
            return {"metric": metric, "window_h": window_h, "n": 0}
        vals = [v for _, v in pts]
        return {
            "metric": metric, "window_h": window_h, "n": len(vals),
            "min": _r(min(vals)), "mean": _r(sum(vals) / len(vals)),
            "max": _r(max(vals)), "last": _r(vals[-1]),
        }

    async def tool_get_tanks(self) -> dict:
        # PLAN §7: stub — no tank level sensors on the invoice. Honest > fake.
        return {"available": False,
                "note": "no tank level sensors installed (PLAN.md open question 3)"}

    async def tool_estimate_runtime(self, load_watts: float,
                                    duration_min: float | None = None) -> dict:
        load_watts = float(load_watts)
        if load_watts <= 0:
            return {"error": "load_watts must be > 0"}
        rd = await self.store.latest()
        soc = rd.get("shunt", {}).get("soc_pct", (0, None))[1]
        if soc is None:
            return {"error": "no SOC reading"}
        wh_total = CAPACITY_AH * NOMINAL_V
        h_to_floor = max(0.0, (soc - USABLE_FLOOR_SOC) / 100.0 * wh_total / load_watts)
        h_to_empty = soc / 100.0 * wh_total / load_watts
        out = {
            "load_watts": load_watts,
            "soc_pct": _r(soc, 0),
            "minutes_to_20pct": _r(h_to_floor * 60, 0),
            "hours_to_empty": _r(h_to_empty),
            "assumes": f"{CAPACITY_AH:.0f}Ah @ {NOMINAL_V}V, this load only",
        }
        if duration_min is not None:
            # The tool renders the verdict so the model never does the
            # comparison itself — a 4B fumbles "25 vs 24" often enough to
            # matter, and this arithmetic must be right on camera.
            duration_min = float(duration_min)
            used_pct = load_watts * (duration_min / 60.0) / wh_total * 100.0
            soc_after = soc - used_pct
            out.update({
                "requested_min": duration_min,
                "soc_after_pct": _r(soc_after, 1),
                "stays_above_20pct": bool(soc_after >= USABLE_FLOOR_SOC),
            })
        return out


# OpenAI-style tool schemas, kept deliberately terse (context budget:
# system + schemas ≤ 800 tokens).
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "get_battery_state",
        "description": "Current battery: SOC %, volts, amps (+=charging), watts, temp, time-to-empty/full h.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_solar_state",
        "description": "Current solar: PV watts, yield today Wh, alternator watts.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_loads",
        "description": "Aggregate DC load watts (null + reason on shore power).",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_history",
        "description": "Stats (min/mean/max/last) for a metric over a window.",
        "parameters": {"type": "object", "properties": {
            "metric": {"type": "string", "enum": sorted(HISTORY_METRICS)},
            "window_h": {"type": "number", "minimum": 0.25, "maximum": 48}},
            "required": ["metric"]}}},
    {"type": "function", "function": {
        "name": "get_tanks",
        "description": "Tank levels (no sensors installed; returns unavailable).",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "estimate_runtime",
        "description": ("Runtime for a DC load from current SOC. Pass "
                        "duration_min for can-I-run-it-for-N-minutes "
                        "questions: returns soc_after_pct and the verdict "
                        "stays_above_20pct - quote that verdict, do not "
                        "recompute it."),
        "parameters": {"type": "object", "properties": {
            "load_watts": {"type": "number", "exclusiveMinimum": 0},
            "duration_min": {"type": "number", "exclusiveMinimum": 0}},
            "required": ["load_watts"]}}},
]
