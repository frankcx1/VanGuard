"""Seeded, deterministic scenario presets (PLAN.md §7).

The part that actually matters for filming: you cannot wait for the battery
to reach 40% at dusk to shoot a take. Every preset is seeded, so re-shooting
the same shot produces the same numbers.

Select with ``config/devices.yaml: sim.scenario: <name>`` or
``SimSource(get_scenario("dusk_low"))``.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from sim.loads import Fridge, LoadBank, LoadEvent, WaterPump
from sim.van_model import VanModel


@dataclass(frozen=True)
class Scenario:
    name: str
    seed: int
    start_soc: float          # %
    start_hour: float         # clock hour at scenario start (0-24)
    ambient_c: float
    weather: str              # 'clear' | 'cloudy' | 'none'
    pv_peak_w: float          # observed peak, not nameplate
    base_load_w: float        # parasitics: ONE Core monitor, detectors, idle inverter
    fridge: bool = True
    pump: bool = True
    shore_charger_a: float = 0.0   # inverter/charger output on shore power
    dropout_rate: float = 0.0      # per-device chance a poll round goes missing
    events: tuple[LoadEvent, ...] = field(default_factory=tuple)


PRESETS: dict[str, Scenario] = {
    # Dashboard hero shot: healthy battery, strong sun, light loads.
    "sunny_midday": Scenario(
        name="sunny_midday", seed=101,
        start_soc=85.0, start_hour=12.0, ambient_c=27.0,
        weather="clear", pv_peak_w=290.0, base_load_w=20.0,
    ),
    # THE cooktop question: 42% at dusk, no sun coming back today.
    "dusk_low": Scenario(
        name="dusk_low", seed=202,
        start_soc=42.0, start_hour=19.5, ambient_c=22.0,
        weather="none", pv_peak_w=0.0, base_load_w=35.0,
        events=(
            LoadEvent("lights", start_h=0.25, duration_min=180.0, watts=12.0),
            LoadEvent("maxxfan", start_h=0.5, duration_min=120.0, watts=22.0),
        ),
    ),
    # Time-to-empty tile: SOC visibly falling all night.
    "overnight_drain": Scenario(
        name="overnight_drain", seed=303,
        start_soc=58.0, start_hour=22.0, ambient_c=18.0,
        weather="none", pv_peak_w=0.0, base_load_w=28.0,
    ),
    # Proves the honest "unavailable" state: charging from a source the
    # telemetry cannot see, so load derivation must refuse, not lie.
    # Golden rule: solar OFF on shore power (documented overcharge issue).
    "shore_power": Scenario(
        name="shore_power", seed=404,
        start_soc=64.0, start_hour=10.0, ambient_c=24.0,
        weather="none", pv_peak_w=0.0, base_load_w=30.0,
        shore_charger_a=45.0,
    ),
    # The answer should be *no*: low battery, gusty marginal sun.
    "cloudy_marginal": Scenario(
        name="cloudy_marginal", seed=505,
        start_soc=30.0, start_hour=10.0, ambient_c=17.0,
        weather="cloudy", pv_peak_w=290.0, base_load_w=25.0,
    ),
}


def get_scenario(name: str) -> Scenario:
    try:
        return PRESETS[name]
    except KeyError:
        raise KeyError(
            f"unknown scenario '{name}'; choose from {sorted(PRESETS)}"
        ) from None


def build_model(scn: Scenario) -> tuple[VanModel, random.Random]:
    """Construct the deterministic model + RNG pair for a scenario.

    One RNG drives everything (loads, weather, sensor noise) so a preset's
    entire behaviour is a pure function of (seed, poll schedule).
    """
    rng = random.Random(scn.seed)
    loads = LoadBank(
        rng=rng,
        base_w=scn.base_load_w,
        fridge=Fridge(rng, scn.ambient_c) if scn.fridge else None,
        pump=WaterPump(rng) if scn.pump else None,
        events=list(scn.events),
    )
    return VanModel(scn, rng, loads), rng
