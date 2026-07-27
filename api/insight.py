"""DeterministicInsightService (P6, review adoption).

Continuously converts telemetry into a concise natural-language
interpretation using local rules — no model involved, so the Insight panel
is reliable even if inference is unavailable. The LLM may *rephrase* an
insight on request; it never originates one.

Each rule returns (finding sentence, optional recommendation, optional
proposed action). Findings are ordered by importance; the panel shows the
composed summary plus the top recommendation.
"""
from __future__ import annotations

import time

from poller import derived


def _get(readings: dict, source: str, metric: str):
    try:
        return readings[source][metric][1]
    except (KeyError, TypeError):
        return None


def _f(c):  # °C → °F for display sentences
    return None if c is None else c * 9 / 5 + 32


def compute_insight(readings: dict, outlook: dict, cfg: dict,
                    now: int | None = None) -> dict:
    now = int(now if now is not None else time.time())
    dv = derived.all_derived(readings)
    findings: list[str] = []
    quality: list[str] = []
    recommendation = None
    action = None      # {"label", "command"} — proposal only, never auto

    soc = _get(readings, "shunt", "soc_pct")
    i = _get(readings, "shunt", "current_a")
    net = dv.get("net_power_w")
    load = dv.get("load_w")
    pv = _get(readings, "dcc50s", "pv_power_w") or 0.0
    alt = _get(readings, "dcc50s", "alt_power_w") or 0.0
    speed = _get(readings, "gps", "speed_mph")
    cabin_c = _get(readings, "hvac", "cabin_temp_c")
    setpoint_c = _get(readings, "hvac", "setpoint_c")
    hvac_mode = _get(readings, "hvac", "mode")
    inv_state = _get(readings, "inverter", "state")

    # -- staleness / data quality first: it gates trust in everything else --
    stale_sources = []
    for source, per in (readings or {}).items():
        if per and now - max(ts for ts, _ in per.values()) > 60:
            stale_sources.append(source)
    if stale_sources:
        quality.append(
            f"{', '.join(sorted(stale_sources))} readings are stale - "
            "treat related values and forecasts as unreliable until they recover")

    if i is not None and net is not None and i * net < -1.0:
        quality.append(
            "battery current and power disagree on direction - "
            "possible sensor inconsistency")

    # -- power story ------------------------------------------------------------
    if dv.get("shore_power_suspected"):
        findings.append(
            "Charging from shore power (inferred - the charger is invisible "
            "to telemetry), so the house load can't be derived right now")
    elif net is not None and net > 5:
        srcs = []
        if pv > 25:
            srcs.append(f"solar ({pv:.0f}W)")
        if alt > 25:
            srcs.append(f"the alternator ({alt:.0f}W)")
        src_txt = " and ".join(srcs) if srcs else "an unidentified source"
        src_cap = src_txt[0].upper() + src_txt[1:]
        if load is not None:
            findings.append(
                f"{src_cap} is covering the {load:.0f}W house "
                f"load and sending about {net:.0f}W to the battery")
        else:
            findings.append(f"{src_cap} is charging the battery "
                            f"at about {net:.0f}W")
        if soc is not None and soc >= 99.5 and (i or 0) > 0.5:
            findings.append(
                "the battery reports 100% while still accepting charge - "
                "normal during absorption/float, or state-of-charge rounding")
    elif net is not None and net < -5:
        findings.append(
            f"Discharging at about {-net:.0f}W"
            + (f" with {pv:.0f}W of solar partially offsetting the "
               f"{load:.0f}W load" if pv > 25 and load else ""))
        rtr = outlook.get("runtime_to_reserve_h")
        if rtr is not None:
            findings.append(f"about {rtr:.1f}h to the "
                            f"{outlook['assumptions']['reserve_pct']:.0f}% reserve "
                            "at this rate")

    # -- overnight verdict -------------------------------------------------------
    if outlook.get("available") and not outlook.get("reserve_ok_overnight", True):
        findings.append(
            f"at the current load the battery is forecast to reach "
            f"{outlook['soc_at_sunrise_pct']:.0f}% by sunrise - below reserve")
        recommendation = "Reduce overnight loads or add charge before tonight."

    # -- driving consistency -----------------------------------------------------
    if (speed or 0) > 5 and alt < 25:
        findings.append(
            "the vehicle appears to be moving but no alternator charge is "
            "arriving - worth checking the DC-DC charger connection")

    # -- climate -----------------------------------------------------------------
    if cabin_c is not None and setpoint_c is not None:
        delta_f = _f(cabin_c) - _f(setpoint_c)
        if delta_f > 8 and hvac_mode == 0:
            findings.append(
                f"cabin is {delta_f:.0f}°F above the {_f(setpoint_c):.0f}°F "
                "target with climate control off")
            if recommendation is None:
                recommendation = ("Consider ventilation or cooling if the "
                                  "van is occupied.")
            action = {"label": "Simulate enabling cooling",
                      "command": {"target": "hvac", "mode": "cool"}}
        elif delta_f < -8 and hvac_mode == 0:
            findings.append(
                f"cabin is {-delta_f:.0f}°F below the {_f(setpoint_c):.0f}°F "
                "target with climate control off")
            if recommendation is None:
                recommendation = "Consider heating if the van is occupied."
            action = {"label": "Simulate enabling heating",
                      "command": {"target": "hvac", "mode": "heat"}}

    # -- inverter ----------------------------------------------------------------
    if inv_state == 2.0:
        ac = _get(readings, "inverter", "ac_out_w") or 0.0
        findings.append(f"the inverter is carrying {ac:.0f}W of AC load")

    if not findings and not quality:
        findings.append("All systems stable; nothing needs attention")

    summary = ". ".join(s[0].upper() + s[1:] for s in findings) + "."
    return {
        "summary": summary,
        "recommendation": recommendation,
        "data_quality": quality,
        "proposed_action": action,
        "generated_by": "deterministic rules",   # provenance — never a model
        "ts": now,
    }
