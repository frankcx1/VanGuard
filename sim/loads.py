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
    """Compressor fridge duty-cycling — the sawtooth.

    Modelled as an on/off timer with ambient-dependent duty and per-cycle
    jitter rather than a thermal model: the observable (power vs time) is the
    same, and this stays deterministic and cheap.
    """

    CYCLE_MIN = 24.0          # nominal full cycle period, minutes
    RUN_W = 52.0              # compressor draw while running

    def __init__(self, rng: random.Random, ambient_c: float):
        self._rng = rng
        # ~30% duty at 15°C ambient scaling to ~50% at 35°C.
        self.duty = min(0.50, max(0.30, 0.30 + (ambient_c - 15.0) * 0.01))
        self._in_run = False
        self._t_left_s = self._draw_phase_s(run=False) * rng.uniform(0.1, 0.9)

    def _draw_phase_s(self, run: bool) -> float:
        jitter = self._rng.uniform(0.85, 1.15)
        share = self.duty if run else (1.0 - self.duty)
        return self.CYCLE_MIN * 60.0 * share * jitter

    def step(self, dt_s: float) -> float:
        self._t_left_s -= dt_s
        if self._t_left_s <= 0:
            self._in_run = not self._in_run
            self._t_left_s = self._draw_phase_s(run=self._in_run)
        if not self._in_run:
            return 0.0
        # Small compressor wander so the "on" plateau isn't a ruler line.
        return self.RUN_W + self._rng.uniform(-2.0, 2.0)


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
    last_ac_w: float = 0.0

    def step(self, dt_s: float, sim_h: float, clock_h: float) -> float:
        w = self.base_w + self.rng.uniform(-0.5, 0.5)
        if self.fridge is not None:
            w += self.fridge.step(dt_s)
        if self.pump is not None:
            w += self.pump.step(dt_s, clock_h)
        self.last_ac_w = 0.0     # AC-side watts through the inverter this step
        for ev in self.events:
            dc = ev.dc_watts_at(sim_h)
            w += dc
            if ev.ac and dc > 0:
                self.last_ac_w += ev.watts
        return max(0.0, w)
