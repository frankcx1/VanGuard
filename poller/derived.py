"""Derived metrics (PLAN.md §3) — pure functions over the latest readings.

Honesty rules encoded here:
- ``load_w`` is only derivable off-grid. On shore power the inverter/charger
  is a charge source the telemetry cannot see (it's CAN-only), so the
  derivation breaks — we return None and the UI says "unavailable on shore
  power" rather than showing a wrong number.
- Rates near zero produce None, not comically large time estimates.
"""
from __future__ import annotations

from sim.van_model import CAPACITY_AH

# Charging harder than this with no visible source ⇒ something we can't see
# (shore charger / alternator) is feeding the battery.
SHORE_SUSPECT_CHARGE_A = 2.0
VISIBLE_SOURCE_FLOOR_W = 25.0


def _get(readings: dict, source: str, metric: str) -> float | None:
    try:
        return readings[source][metric][1]
    except (KeyError, TypeError):
        return None


def net_power_w(readings: dict) -> float | None:
    """Signed battery power straight from the shunt; positive = charging."""
    return _get(readings, "shunt", "power_w")


def shore_power_suspected(readings: dict) -> bool:
    """Detected from observables only — never from sim internals."""
    i = _get(readings, "shunt", "current_a")
    pv = _get(readings, "dcc50s", "pv_power_w") or 0.0
    alt = _get(readings, "dcc50s", "alt_power_w") or 0.0
    if i is None:
        return False
    return i > SHORE_SUSPECT_CHARGE_A and (pv + alt) < VISIBLE_SOURCE_FLOOR_W


def load_w(readings: dict) -> float | None:
    """(visible charge sources in) − (net battery power). Off-grid only."""
    if shore_power_suspected(readings):
        return None
    net = net_power_w(readings)
    pv = _get(readings, "dcc50s", "pv_power_w")
    alt = _get(readings, "dcc50s", "alt_power_w") or 0.0
    if net is None or pv is None:
        return None
    return max(0.0, (pv + alt) - net)


def time_to_empty_h(readings: dict, capacity_ah: float = CAPACITY_AH) -> float | None:
    soc = _get(readings, "shunt", "soc_pct")
    i = _get(readings, "shunt", "current_a")
    if soc is None or i is None or i >= -0.1:      # not meaningfully discharging
        return None
    return (soc / 100.0) * capacity_ah / -i


def time_to_full_h(readings: dict, capacity_ah: float = CAPACITY_AH) -> float | None:
    soc = _get(readings, "shunt", "soc_pct")
    i = _get(readings, "shunt", "current_a")
    if soc is None or i is None or i <= 0.1:       # not meaningfully charging
        return None
    return ((100.0 - soc) / 100.0) * capacity_ah / i


def solar_yield_wh_today(readings: dict) -> float | None:
    return _get(readings, "dcc50s", "daily_yield_wh")


def charge_source(readings: dict) -> dict:
    """Which system is charging the battery, from observables.

    Solar and alternator are measured at the DCC50S; shore power is
    inferred (the inverter/charger is CAN-only and invisible), so it is
    always labeled inferred, never presented as a measurement.
    """
    pv = _get(readings, "dcc50s", "pv_power_w") or 0.0
    alt = _get(readings, "dcc50s", "alt_power_w") or 0.0
    i = _get(readings, "shunt", "current_a")
    sources = []
    if pv >= VISIBLE_SOURCE_FLOOR_W:
        sources.append("solar")
    if alt >= VISIBLE_SOURCE_FLOOR_W:
        sources.append("alternator")
    if shore_power_suspected(readings):
        sources.append("shore (inferred)")
    charging = i is not None and i > 0.5
    return {
        "charging": charging,
        "sources": sources if charging or sources else [],
        "solar_w": round(pv), "alternator_w": round(alt),
    }


def all_derived(readings: dict) -> dict[str, float | bool | None]:
    """The bundle the API will expose; None means honestly unavailable."""
    return {
        "net_power_w": net_power_w(readings),
        "load_w": load_w(readings),
        "shore_power_suspected": shore_power_suspected(readings),
        "time_to_empty_h": time_to_empty_h(readings),
        "time_to_full_h": time_to_full_h(readings),
        "solar_yield_wh_today": solar_yield_wh_today(readings),
        "charge_source": charge_source(readings),
    }
