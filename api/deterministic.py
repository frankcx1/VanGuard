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
