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


def _f(c: float | None) -> float | None:
    """°C → °F, done here so the model never converts units itself."""
    return None if c is None else round(c * 9 / 5 + 32, 1)


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
        # The signs are pre-interpreted into words: a small model misreads
        # "+55A" as discharge often enough that the tool states it plainly.
        i = sh.get("current_a") or 0.0
        state = "charging" if i > 0.5 else "discharging" if i < -0.5 else "idle"
        cs = derived.charge_source(rd)
        return {
            "soc_pct": _r(sh.get("soc_pct"), 0),
            "state": state,
            "charging_from": cs["sources"] if cs["sources"] else "nothing",
            "voltage_v": _r(sh.get("voltage_v"), 2),
            "current_a": _r(sh.get("current_a"), 1),
            "power_w": _r(sh.get("power_w"), 0),
            "temp_f": _f(sh.get("temp_c")),
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
        inv = {m: v for m, (ts, v) in rd.get("inverter", {}).items()}
        state = {0.0: "off", 1.0: "idle", 2.0: "inverting",
                 3.0: "bypass (shore power)"}.get(inv.get("state"))
        return {"load_w": _r(load, 0),
                "inverter_state": state,
                "inverter_ac_out_w": _r(inv.get("ac_out_w"), 0),
                "note": "aggregate DC load; no per-circuit breakdown"}

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

    async def tool_get_climate(self) -> dict:
        rd = await self.store.latest()
        hv = {m: v for m, (ts, v) in rd.get("hvac", {}).items()}
        if not hv:
            return {"error": "no climate data"}
        mode = {0.0: "off", 1.0: "heat", 2.0: "cool"}.get(hv.get("mode"), "off")
        return {
            "cabin_temp_f": _f(hv.get("cabin_temp_c")),
            "mode": mode,
            "setpoint_f": _f(hv.get("setpoint_c")),
            "hvac_power_w": _r(hv.get("hvac_power_w"), 0),
            "note": "read-only; controls are human-only via the dashboard",
        }

    async def tool_get_trip_status(self) -> dict:
        rd = await self.store.latest()
        gps = {m: v for m, (ts, v) in rd.get("gps", {}).items()}
        if not gps:
            return {"error": "no GPS fix"}
        return {
            "lat": _r(gps.get("lat"), 4), "lon": _r(gps.get("lon"), 4),
            "speed_mph": _r(gps.get("speed_mph")),
            "moving": (gps.get("speed_mph") or 0) > 2.0,
            "trip_mi": _r(gps.get("trip_mi")),
        }

    async def tool_get_nearby_pois(self, radius_mi: float = 15.0,
                                   limit: int = 5) -> dict:
        from sim.gps import nearby_pois
        rd = await self.store.latest()
        gps = {m: v for m, (ts, v) in rd.get("gps", {}).items()}
        if "lat" not in gps:
            return {"error": "no GPS fix"}
        radius_mi = max(1.0, min(100.0, float(radius_mi)))
        pois = nearby_pois(gps["lat"], gps["lon"], radius_mi,
                           limit=max(1, min(8, int(limit))))
        return {"radius_mi": radius_mi, "pois": pois,
                "source": "offline curated dataset"}

    async def tool_get_network(self) -> dict:
        rd = await self.store.latest()
        net = {m: v for m, (ts, v) in rd.get("network", {}).items()}
        if not net:
            return {"error": "no connectivity data"}
        mode = {0.0: "offline", 1.0: "5G cellular", 2.0: "local wifi",
                3.0: "starlink"}.get(net.get("mode"), "offline")
        out = {
            "uplink": mode,
            "note": "uplink carries internet only - AI and telemetry stay on device",
        }
        if mode != "offline":
            out.update({
                "signal_pct": _r(net.get("signal_pct"), 0),
                "latency_ms": _r(net.get("latency_ms"), 0),
                "down_mbps": _r(net.get("down_mbps"), 0),
                "up_mbps": _r(net.get("up_mbps"), 0),
            })
        sl = {m: v for m, (ts, v) in rd.get("starlink", {}).items()}
        if sl:
            out["starlink_dish"] = {
                "state": {0.0: "booting", 1.0: "online",
                          2.0: "obstructed"}.get(sl.get("state")),
                "obstruction_pct": _r(sl.get("obstruction_pct")),
                "power_w": _r(sl.get("power_w"), 0),
            }
        return out

    async def tool_get_chassis(self) -> dict:
        rd = await self.store.latest()
        ch = {m: v for m, (ts, v) in rd.get("chassis", {}).items()}
        if not ch:
            return {"error": "no chassis adapter - front-of-van data not monitored"}
        return {
            "engine_running": ch.get("engine_running") == 1.0,
            "speed_mph": _r(ch.get("speed_mph")),
            "chassis_battery_v": _r(ch.get("chassis_v"), 2),
            "fuel_pct": _r(ch.get("fuel_pct"), 0),
            "def_pct": _r(ch.get("def_pct"), 0),
            "coolant_f": _f(ch.get("coolant_c")),
            "odometer_mi": _r(ch.get("odometer_mi"), 0),
            "dtc_count": _r(ch.get("dtc_count"), 0),
            "note": "read-only chassis telemetry",
        }

    async def tool_get_guardian_log(self, limit: int = 8) -> dict:
        """The autonomy decision trail — lets the model answer "why did you
        do that?" from the record instead of confabulating a reason."""
        events = await self.store.guardian_events(limit=max(1, min(20, int(limit))))
        return {"events": [
            {"time_ago_s": int(time.time()) - e["ts"], "stage": e["stage"],
             "title": e["title"], "detail": e["detail"]}
            for e in events]}

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
        "name": "get_climate",
        "description": "Cabin temp F, HVAC mode/setpoint F, HVAC watts. Read-only.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_trip_status",
        "description": "GPS: position, speed mph, moving flag, trip miles.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_nearby_pois",
        "description": "Things to do near the van from the offline POI dataset: name, type, distance mi, note.",
        "parameters": {"type": "object", "properties": {
            "radius_mi": {"type": "number", "minimum": 1, "maximum": 100},
            "limit": {"type": "integer", "minimum": 1, "maximum": 8}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "get_network",
        "description": "Connectivity: uplink (offline/5G/wifi/starlink), signal, latency, throughput, Starlink dish state/power.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_chassis",
        "description": "Read-only Mercedes chassis: engine state, speed, chassis battery V, fuel %, DEF %, coolant F, odometer, DTC count.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_guardian_log",
        "description": "Recent autonomous Guardian decisions: what was detected, what was done, the verified result. Use to answer why-did-you-do-that.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": []}}},
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
