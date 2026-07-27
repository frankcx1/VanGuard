"""Deterministic question responder (P6, review adoption).

Used when no local model is available: the app must remain fully usable,
clearly labeled "LOCAL MODEL UNAVAILABLE - USING DETERMINISTIC DEMO ENGINE".
Same audited tools, same honest numbers — just template prose instead of a
model. Also the provable answer path for tests, since it needs no LLM.
"""
from __future__ import annotations

import re

from api.tools import ToolRunner

WATTS_RE = re.compile(r"(\d{3,4})\s*w", re.IGNORECASE)
MINUTES_RE = re.compile(r"(\d{1,3})\s*(?:min|minutes)", re.IGNORECASE)
COOKTOP_DEFAULT_W = 1700.0     # DC-side draw of the 1500W AC cooktop

DEPARTURE_KEYWORDS = ("ready to depart", "ready to leave", "ready to go",
                      "departure", "depart", "before we leave",
                      "before we drive", "leave camp")


def is_departure_question(q: str) -> bool:
    return any(k in q.lower() for k in DEPARTURE_KEYWORDS)


def departure_checklist(readings: dict) -> list[dict]:
    """Deterministic pre-departure check (P9). Unknown ≠ PASS: anything we
    can't see is reported as not monitored, never assumed fine."""
    import time as _time
    now = int(_time.time())

    def val(source, metric):
        m = readings.get(source, {}).get(metric)
        if not m or now - m[0] > 60:
            return None
        return m[1]

    rows = []

    def row(item, status, note):
        rows.append({"item": item, "status": status, "note": note})

    soc = val("shunt", "soc_pct")
    if soc is None:
        row("House battery", "not monitored", "no fresh reading")
    else:
        row("House battery", "ok" if soc >= 50 else "attention",
            f"{soc:.0f}% SOC")
    shore = val("charge_ctl", "shore_on")
    row("Shore power", "not monitored" if shore is None else
        ("attention" if shore == 1.0 else "ok"),
        "unplug before driving" if shore == 1.0 else "disconnected")
    inv = val("inverter", "state")
    row("Inverter", "not monitored" if inv is None else
        ("ok" if inv in (0.0, None) else "attention"),
        "off" if inv == 0.0 else "still on - switch off for the drive")
    for name, label in (("fridge_on", "Fridge"), ("freezer_on", "Freezer")):
        v = val("switches", name)
        row(label, "not monitored" if v is None else
            ("ok" if v == 1.0 else "attention"),
            "running" if v == 1.0 else "switched OFF - food risk on a long drive")
    hv = val("hvac", "mode")
    row("Climate", "not monitored" if hv is None else
        ("ok" if hv == 0.0 else "attention"),
        "off" if hv == 0.0 else "still running")
    fuel = val("chassis", "fuel_pct")
    row("Fuel", "not monitored" if fuel is None else
        ("ok" if fuel >= 25 else "attention"),
        f"{fuel:.0f}%" if fuel is not None else "chassis data unavailable")
    d = val("chassis", "def_pct")
    row("DEF", "not monitored" if d is None else
        ("ok" if d >= 15 else "attention"),
        f"{d:.0f}%" if d is not None else "chassis data unavailable")
    dtc = val("chassis", "dtc_count")
    row("Diagnostic codes", "not monitored" if dtc is None else
        ("ok" if dtc == 0 else "attention"),
        "none" if dtc == 0 else
        (f"{dtc:.0f} active DTC(s)" if dtc is not None else "unavailable"))
    stale = sum(1 for per in readings.values()
                for ts, _ in per.values() if now - ts > 60)
    row("Sensor freshness", "ok" if stale == 0 else "attention",
        "all fresh" if stale == 0 else f"{stale} stale readings")
    return rows


def format_checklist(rows: list[dict]) -> str:
    mark = {"ok": "OK", "attention": "ATTENTION", "not monitored": "NOT MONITORED"}
    lines = ["Departure readiness (deterministic check):"]
    for r in rows:
        lines.append(f"- {r['item']}: {mark[r['status']]} - {r['note']}")
    n_att = sum(1 for r in rows if r["status"] == "attention")
    lines.append("Verdict: " + ("ready to depart." if n_att == 0 else
                                f"{n_att} item(s) need attention before leaving."))
    return "\n".join(lines)


async def respond(question: str, runner: ToolRunner,
                  insight: dict, outlook: dict) -> tuple[str, list[dict]]:
    q = question.lower()
    trace: list[dict] = []

    async def call(name: str, args: dict) -> dict:
        result = await runner.call(name, args, device="DETERMINISTIC")
        trace.append({"tool": name, "args": args, "result": result})
        return result

    # Runtime / appliance questions → estimate_runtime verdict.
    if any(k in q for k in ("cooktop", "run the", "how long", "minutes",
                            "overnight", "a/c", "air condition")):
        watts = float(WATTS_RE.search(q).group(1)) if WATTS_RE.search(q) \
            else (900.0 if ("a/c" in q or "air condition" in q)
                  else COOKTOP_DEFAULT_W)
        mins = float(MINUTES_RE.search(q).group(1)) if MINUTES_RE.search(q) \
            else (outlook.get("hours_to_sunrise", 8.0) * 60.0
                  if "overnight" in q else None)
        args = {"load_watts": watts}
        if mins:
            args["duration_min"] = mins
        rt = await call("estimate_runtime", args)
        if "error" in rt:
            return f"Can't estimate: {rt['error']}.", trace
        if mins and "stays_above_20pct" in rt:
            verdict = "Yes" if rt["stays_above_20pct"] else "No"
            return (
                f"{verdict}. At {watts:.0f}W for {mins:.0f} minutes the "
                f"battery goes from {rt['soc_pct']:.0f}% to "
                f"{rt['soc_after_pct']:.1f}% - "
                f"{'above' if rt['stays_above_20pct'] else 'below'} the 20% "
                f"reserve. Time to reserve at that load: "
                f"{rt['minutes_to_20pct']:.0f} minutes.", trace)
        return (f"At {watts:.0f}W, about {rt['minutes_to_20pct']:.0f} minutes "
                f"to the 20% reserve from {rt['soc_pct']:.0f}% "
                f"({rt['hours_to_empty']:.1f}h to empty).", trace)

    # Location / things to do.
    if any(k in q for k in ("nearby", "around here", "things to do", "hike",
                            "where are we", "trail", "beach")):
        pois = await call("get_nearby_pois", {"radius_mi": 15, "limit": 4})
        if pois.get("pois"):
            lines = "; ".join(f"{p['name']} ({p['type']}, {p['dist_mi']}mi)"
                              for p in pois["pois"])
            return f"Nearby (offline dataset): {lines}.", trace
        return "No GPS fix or no known places nearby.", trace

    # Climate.
    if any(k in q for k in ("warm", "cold", "temperature", "inside", "climate")):
        cl = await call("get_climate", {})
        if "error" not in cl:
            return (f"Cabin is {cl['cabin_temp_f']:.1f}°F, climate control "
                    f"{cl['mode']} with a {cl['setpoint_f']:.0f}°F setpoint.",
                    trace)

    # Default: current interpretation + outlook.
    parts = [insight["summary"]]
    if outlook.get("available"):
        parts.append(
            f"Forecast: {outlook['soc_at_sunrise_pct']:.0f}% by sunrise "
            f"({outlook['confidence']} confidence).")
    if insight.get("recommendation"):
        parts.append(insight["recommendation"])
    return " ".join(parts), trace
