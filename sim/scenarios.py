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

from sim.climate import Hvac
from sim.gps import GpsTrack
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
    # P5 demo mode:
    alternator_a: float = 0.0      # DC-DC input while the engine runs
    position: tuple[float, float] | None = None   # fixed campsite (lat, lon)
    route: str | None = None       # route name → drives along sim/data/route_*.json
    drive_mph: float = 0.0
    hvac_mode: float = 0.0         # 0 off, 1 heat, 2 cool (initial)
    hvac_setpoint_c: float = 21.0
    inverter_on: bool = False      # initial inverter switch state
    network_mode: str = "off"      # off | cell | wifi | starlink (initial)
    # P9 chassis sim (read-only domain; real adapter is OBD-II, see
    # CHASSIS_RESEARCH.md):
    fuel_pct: float = 68.0
    def_pct: float = 74.0
    odometer_mi: float = 41_250.0
    dtc_count: float = 0.0
    charging_fault: bool = False   # engine runs but no energy reaches the
                                   # house system — the fusion-finding demo


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
    # P5 demo: parked at home in Kirkland, WA (approximate city-center
    # coords, deliberately not a real address — public repo). Sunny summer
    # day, solar doing its thing, Eastside recreation in the POI set.
    "driveway": Scenario(
        name="driveway", seed=707,
        start_soc=88.0, start_hour=10.0, ambient_c=22.0,
        weather="clear", pv_peak_w=290.0, base_load_w=22.0,
        position=(47.6840, -122.1965),
    ),
    # P8 Guardian demo: the overnight-reserve story. 31% at 23:00, no sun
    # coming, Starlink dish and idle inverter quietly burning ~40W of
    # nonessential load — the forecast breaches Camp reserve, Guardian
    # sheds both, and the sunrise number recovers on camera.
    "overnight_guardian": Scenario(
        name="overnight_guardian", seed=808,
        start_soc=31.0, start_hour=23.0, ambient_c=16.0,
        weather="none", pv_peak_w=0.0, base_load_w=30.0,
        inverter_on=True, network_mode="starlink",
    ),
    # P9 fusion demo: chassis says the engine is healthy and running, yet no
    # alternator energy reaches the house system. Neither subsystem alone
    # can explain it — the cross-system finding can.
    "charging_path_fault": Scenario(
        name="charging_path_fault", seed=909,
        start_soc=55.0, start_hour=14.0, ambient_c=21.0,
        weather="cloudy", pv_peak_w=290.0, base_load_w=35.0,
        alternator_a=40.0, route="tofino", drive_mph=32.0,
        charging_fault=True,
    ),
    # P9 fusion demo: arrive at camp — driving → parked, ignition off, but
    # Starlink and the idle inverter are still burning travel-mode watts
    # into a marginal evening reserve.
    "arrival_cleanup": Scenario(
        name="arrival_cleanup", seed=910,
        start_soc=44.0, start_hour=19.0, ambient_c=18.0,
        weather="none", pv_peak_w=0.0, base_load_w=30.0,
        alternator_a=40.0, route="tofino", drive_mph=32.0,
        inverter_on=True, network_mode="starlink",
    ),
    # P5 demo: driving the Pacific Rim Hwy into Tofino — alternator charging
    # while moving, GPS tracking the route, trip keeper advising on what's
    # nearby. Parks in Tofino when the route ends (~45 min at 32 mph).
    "road_trip": Scenario(
        name="road_trip", seed=606,
        start_soc=72.0, start_hour=10.5, ambient_c=17.0,
        weather="clear", pv_peak_w=290.0, base_load_w=25.0,
        alternator_a=40.0, route="tofino", drive_mph=32.0,
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
        freezer=Fridge(rng, scn.ambient_c, run_w=40.0, cycle_min=30.0,
                       duty_base=0.33) if scn.fridge else None,
        pump=WaterPump(rng) if scn.pump else None,
        events=list(scn.events),
    )
    hvac = Hvac(cabin_c=scn.ambient_c + 2.0, mode=scn.hvac_mode,
                setpoint_c=scn.hvac_setpoint_c)
    gps = GpsTrack(scn.seed, position=scn.position, route=scn.route,
                   speed_mph=scn.drive_mph)
    model = VanModel(scn, rng, loads, hvac=hvac, gps=gps)
    if scn.inverter_on:
        model.inverter_on = True
    if scn.network_mode != "off":
        model.network.set_mode(scn.network_mode)
    return model, rng
