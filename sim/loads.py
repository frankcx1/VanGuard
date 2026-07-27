"""DC load models for the simulated van (PLAN.md §7, "making the simulator
look real").

Real telemetry is steppy, noisy, and quantized; the single biggest tell of a
fake load graph is a flat line. The fridge duty cycle here is what produces
the characteristic sawtooth.

All randomness must come through the RNG handed in by the scenario, never the
global ``random`` module — scenarios are seeded and takes must reproduce.

Figures and their provenance:
- Alpicool C40 compressor ~45-60W, duty ~30-50% by ambient  [UNVERIFIED —
  brief/PLAN working figure; measure against DC Home after M2]
- Inverter conversion efficiency ~88%                       [UNVERIFIED —
  typical for RIV1230RCL class; refine from manual or measurement]
- Cooktop 1500W AC ≈ 1700W DC after inverter losses         [verified — PLAN §7]
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

INVERTER_EFFICIENCY = 0.88


def ac_to_dc_watts(ac_w: float) -> float:
    """DC-side draw for an AC appliance behind the inverter."""
    return ac_w / INVERTER_EFFICIENCY if ac_w > 0 else 0.0


@dataclass(frozen=True)
class LoadEvent:
    """A scheduled discrete load: cooktop, fan, lights, ...

    ``start_h`` is hours since scenario start (not clock hour), so presets
    read naturally: an event 2h into the take starts at start_h=2.0.
    """
    name: str
    start_h: float
    duration_min: float
    watts: float
    ac: bool = False  # True → behind the inverter, pays conversion losses

    def dc_watts_at(self, sim_h: float) -> float:
        active = self.start_h <= sim_h < self.start_h + self.duration_min / 60.0
        if not active:
            return 0.0
        return ac_to_dc_watts(self.watts) if self.ac else self.watts


class Fridge:
    """Compressor fridge/freezer duty-cycling — the sawtooth.

    Modelled as an on/off timer with ambient-dependent duty and per-cycle
    jitter rather than a thermal model: the observable (power vs time) is the
    same, and this stays deterministic and cheap. The freezer is the same
    machine with its own parameters.
    """

    def __init__(self, rng: random.Random, ambient_c: float,
                 run_w: float = 52.0, cycle_min: float = 24.0,
                 duty_base: float = 0.30):
        self._rng = rng
        self.run_w = run_w
        self.cycle_min = cycle_min
        # duty scales with ambient: +1%/°C above 15°C, capped.
        self.duty = min(0.55, max(duty_base, duty_base + (ambient_c - 15.0) * 0.01))
        self._in_run = False
        self._t_left_s = self._draw_phase_s(run=False) * rng.uniform(0.1, 0.9)

    def _draw_phase_s(self, run: bool) -> float:
        jitter = self._rng.uniform(0.85, 1.15)
        share = self.duty if run else (1.0 - self.duty)
        return self.cycle_min * 60.0 * share * jitter

    def step(self, dt_s: float) -> float:
        self._t_left_s -= dt_s
        if self._t_left_s <= 0:
            self._in_run = not self._in_run
            self._t_left_s = self._draw_phase_s(run=self._in_run)
        if not self._in_run:
            return 0.0
        # Small compressor wander so the "on" plateau isn't a ruler line.
        return self.run_w + self._rng.uniform(-2.0, 2.0)


class WaterPump:
    """Short random bursts (taps, sink) while people are awake."""

    BURST_W = 42.0

    def __init__(self, rng: random.Random, bursts_per_active_hour: float = 0.6):
        self._rng = rng
        self._rate = bursts_per_active_hour
        self._burst_left_s = 0.0

    def step(self, dt_s: float, clock_h: float) -> float:
        if self._burst_left_s > 0:
            self._burst_left_s -= dt_s
            return self.BURST_W + self._rng.uniform(-1.5, 1.5)
        awake = 7.0 <= (clock_h % 24.0) <= 23.0
        if awake and self._rng.random() < self._rate * (dt_s / 3600.0):
            self._burst_left_s = self._rng.uniform(15.0, 60.0)
        return 0.0


@dataclass
class LoadBank:
    """Everything drawing from the battery, summed each step."""

    rng: random.Random
    base_w: float                       # parasitics: monitor, detectors, idle electronics
    fridge: Fridge | None
    pump: WaterPump | None
    events: list[LoadEvent] = field(default_factory=list)
    freezer: Fridge | None = None
    last_ac_w: float = 0.0
    last_fridge_w: float = 0.0
    last_freezer_w: float = 0.0
    # Human-toggled appliances (P6 demo): name → (watts, is_ac).
    appliances: dict = field(default_factory=dict)
    # Dedicated 12V smart switches (fridge/freezer have their own; assumed
    # BT-controllable — PLAN §12.5 hardware path).
    switches: dict = field(default_factory=lambda: {"fridge": True, "freezer": True})

    def step(self, dt_s: float, sim_h: float, clock_h: float,
             ac_available: bool = True) -> float:
        w = self.base_w + self.rng.uniform(-0.5, 0.5)
        self.last_fridge_w = 0.0
        self.last_freezer_w = 0.0
        if self.fridge is not None:
            fw = self.fridge.step(dt_s)     # step regardless — the compressor
            if self.switches.get("fridge", True):   # timer runs; the switch cuts power
                self.last_fridge_w = fw
                w += fw
        if self.freezer is not None:
            zw = self.freezer.step(dt_s)
            if self.switches.get("freezer", True):
                self.last_freezer_w = zw
                w += zw
        if self.pump is not None:
            w += self.pump.step(dt_s, clock_h)
        self.last_ac_w = 0.0     # AC-side watts through the inverter this step
        for ev in self.events:
            # Scenario-scripted AC events assume the take manages the
            # inverter; only interactive appliances are gated on it.
            dc = ev.dc_watts_at(sim_h)
            w += dc
            if ev.ac and dc > 0:
                self.last_ac_w += ev.watts
        for watts, is_ac in self.appliances.values():
            if is_ac and not ac_available:
                continue                    # dead outlets: inverter is off
            w += ac_to_dc_watts(watts) if is_ac else watts
            if is_ac:
                self.last_ac_w += watts
        return max(0.0, w)
