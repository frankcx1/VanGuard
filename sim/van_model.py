"""SimSource: a physically-modelled synthetic van (PLAN.md §7).

Non-negotiable modelling rules from the plan:

- **The battery is a coulomb counter.** SOC integrates net current over time;
  it is set once at construction and never written directly again.
- **Voltage comes from a real LiFePO4 OCV curve** — famously flat through the
  mid-band — plus an IR term for sag under load, with the charge controller's
  bulk → absorption → float behaviour layered on top. No linear V-vs-SOC ramp.
- **Solar is a bell curve** scaled by weather, peaking at the 200–300W this
  van has actually been observed to produce (forum screenshot in
  ``../Sprinter/Renogy and Power/``), not the 400W nameplate.
- All randomness flows through one seeded RNG so scenario takes reproduce.

Electrical figures and provenance:
- Battery: Renogy 12V 300Ah Core Series, 200A BMS  [verified — OGA invoice]
- OCV curve points: canonical 12V LiFePO4 shape    [verified-external —
  matches PLAN §7's anchor points 13.4/13.1/12.9]
- Internal resistance ~3 mΩ pack-level             [UNVERIFIED — plausible for
  a 300Ah pack; calibrate against real sag after M2]
- DCC50S bulk 14.4V / float 13.6V                  [verified — PLAN §7]
- Emission quantisation steps                      [UNVERIFIED — plausible
  DC-Home-like resolution; match to real captures after M2]
"""
from __future__ import annotations

import math
import random
import time

from poller.source import Sample, TelemetrySource
from sim.loads import LoadBank

# --- Battery -----------------------------------------------------------------

OCV_CURVE = [  # (SOC %, resting volts). The flat mid-band is the point.
    (0.0, 10.0), (2.0, 11.5), (5.0, 12.1), (10.0, 12.55), (20.0, 12.90),
    (30.0, 13.00), (40.0, 13.05), (50.0, 13.10), (60.0, 13.15),
    (70.0, 13.20), (80.0, 13.25), (90.0, 13.32), (99.0, 13.38), (100.0, 13.40),
]

BULK_ABSORB_V = 14.4
FLOAT_V = 13.6
PACK_R_OHM = 0.003
CAPACITY_AH = 300.0
BMS_LIMIT_A = 200.0
CHARGE_EFFICIENCY = 0.95        # PV watts in → battery watts, controller losses


def ocv(soc: float) -> float:
    """Piecewise-linear interpolation over OCV_CURVE."""
    pts = OCV_CURVE
    if soc <= pts[0][0]:
        return pts[0][1]
    for (s0, v0), (s1, v1) in zip(pts, pts[1:]):
        if soc <= s1:
            return v0 + (v1 - v0) * (soc - s0) / (s1 - s0)
    return pts[-1][1]


class Battery:
    """Coulomb-counting LiFePO4 pack. SOC is never assigned after __init__."""

    def __init__(self, soc_pct: float):
        self._soc = max(0.0, min(100.0, soc_pct))
        self.charge_ah_total = 0.0
        self.discharge_ah_total = 0.0
        self.i_net_a = 0.0          # signed; positive = charging

    @property
    def soc(self) -> float:
        return self._soc

    def headroom_a(self, dt_s: float) -> float:
        """Max charge current this step without overshooting 100% SOC."""
        return (100.0 - self._soc) / 100.0 * CAPACITY_AH * 3600.0 / dt_s

    def step(self, i_net_a: float, dt_s: float) -> None:
        i_net_a = max(-BMS_LIMIT_A, min(BMS_LIMIT_A, i_net_a))
        self.i_net_a = i_net_a
        d_ah = i_net_a * dt_s / 3600.0
        self._soc = max(0.0, min(100.0, self._soc + d_ah / CAPACITY_AH * 100.0))
        if d_ah >= 0:
            self.charge_ah_total += d_ah
        else:
            self.discharge_ah_total += -d_ah

    def terminal_v(self, charge_stage: str) -> float:
        if charge_stage == "absorption":
            return BULK_ABSORB_V
        if charge_stage == "float":
            return FLOAT_V
        v = ocv(self._soc) + self.i_net_a * PACK_R_OHM
        return max(9.5, min(14.6, v))


# --- Solar ---------------------------------------------------------------------

SUNRISE_H = 6.5   # July-ish; scenarios are filmed takes, not an almanac
SUNSET_H = 20.5


class SolarArray:
    """2×200W nominal, but the bell peaks where this van actually peaks."""

    def __init__(self, rng: random.Random, peak_w: float, weather: str):
        self._rng = rng
        self.peak_w = peak_w
        self.weather = weather          # 'clear' | 'cloudy' | 'none'
        self._cloud = 0.35              # random-walk transmission for 'cloudy'

    def power_w(self, clock_h: float, dt_s: float) -> float:
        if self.weather == "none":
            return 0.0
        h = clock_h % 24.0
        if not (SUNRISE_H < h < SUNSET_H):
            return 0.0
        x = math.sin(math.pi * (h - SUNRISE_H) / (SUNSET_H - SUNRISE_H))
        w = self.peak_w * (x ** 1.5)
        if self.weather == "cloudy":
            # Bounded random walk: intermittent, gusty transmission.
            self._cloud += self._rng.uniform(-0.06, 0.06) * (dt_s / 60.0) ** 0.5
            self._cloud = max(0.10, min(0.60, self._cloud))
            w *= self._cloud
        return max(0.0, w)


# --- The van -------------------------------------------------------------------

class VanModel:
    """Steps the whole electrical system forward and exposes device readings."""

    def __init__(self, scenario, rng: random.Random, loads: LoadBank,
                 hvac=None, gps=None):
        self.scn = scenario
        self.rng = rng
        self.loads = loads
        self.hvac = hvac
        self.gps = gps
        self.hvac_w = 0.0
        self.alt_w = 0.0
        self.battery = Battery(scenario.start_soc)
        self.solar = SolarArray(rng, scenario.pv_peak_w, scenario.weather)
        self.sim_s = 0.0                       # seconds since scenario start
        self.charge_stage = "bulk"             # 'bulk' | 'absorption' | 'float'
        self._absorb_i = None                  # tapering absorption current
        self.daily_yield_wh = 0.0
        self._yield_day = 0
        # Last-step observables, read by the emitter.
        self.pv_w = 0.0
        self.load_w = 0.0
        self.batt_v = ocv(scenario.start_soc)

    @property
    def clock_h(self) -> float:
        return self.scn.start_hour + self.sim_s / 3600.0

    def step(self, dt_s: float) -> None:
        self.sim_s += dt_s
        clock_h = self.clock_h
        sim_h = self.sim_s / 3600.0

        # Daily yield counter resets at (sim) midnight, like the DCC50S does.
        day = int(clock_h // 24.0)
        if day != self._yield_day:
            self._yield_day = day
            self.daily_yield_wh = 0.0

        self.pv_w = self.solar.power_w(clock_h, dt_s)
        self.load_w = self.loads.step(dt_s, sim_h, clock_h)

        if self.gps is not None:
            self.gps.step(dt_s)
        if self.hvac is not None:
            sun_frac = self.pv_w / self.scn.pv_peak_w if self.scn.pv_peak_w > 0 else 0.0
            self.hvac_w = self.hvac.step(dt_s, self.ambient_c(), sun_frac)
            self.load_w += self.hvac_w

        v = self.batt_v if self.batt_v > 9.5 else 12.8
        i_load = self.load_w / v

        # Charge sources: MPPT from PV, alternator through the DCC50S while
        # the engine runs, plus the inverter/charger on shore power
        # (invisible to the DCC50S — that blindness is modelled, not a
        # bug: it's what breaks load derivation on shore, PLAN §3).
        i_pv = self.pv_w * CHARGE_EFFICIENCY / v
        engine_on = self.scn.alternator_a > 0 and (
            self.gps is None or self.scn.route is None or self.gps.moving)
        i_alt = self.scn.alternator_a if engine_on else 0.0
        i_alt = max(0.0, min(50.0 - i_pv, i_alt))   # DCC50S is a 50A device
        self.alt_w = i_alt * v
        i_shore = self.scn.shore_charger_a
        i_charge_avail = i_pv + i_alt + i_shore

        i_charge = self._charge_stage_limit(i_charge_avail, dt_s)
        i_net = i_charge - i_load
        self.battery.step(i_net, dt_s)
        self.batt_v = self.battery.terminal_v(self.charge_stage)

        if i_pv > 0 and i_charge > 0:
            pv_share = min(1.0, i_pv / max(i_charge_avail, 1e-9))
            self.daily_yield_wh += self.pv_w * pv_share * dt_s / 3600.0

    def apply_command(self, cmd: dict) -> bool:
        """Human-initiated control (P5 demo). Only the sim accepts these."""
        if cmd.get("target") == "hvac" and self.hvac is not None:
            mode_map = {"off": 0.0, "heat": 1.0, "cool": 2.0}
            mode = mode_map.get(cmd.get("mode")) if "mode" in cmd else None
            self.hvac.command(mode=mode, setpoint_c=cmd.get("setpoint_c"))
            return True
        return False

    def _charge_stage_limit(self, i_avail: float, dt_s: float) -> float:
        """DCC50S bulk → absorption → float state machine."""
        batt = self.battery
        if i_avail < 0.2:
            # No meaningful source: fall out of regulation back to bulk.
            self.charge_stage = "bulk"
            self._absorb_i = None
            return i_avail
        if self.charge_stage == "bulk":
            v_would_be = ocv(batt.soc) + i_avail * PACK_R_OHM
            if v_would_be >= BULK_ABSORB_V or batt.soc >= 97.0:
                self.charge_stage = "absorption"
                self._absorb_i = i_avail
        if self.charge_stage == "absorption":
            # Held at 14.4V the acceptance current tapers; ~25 min constant.
            self._absorb_i *= math.exp(-dt_s / (25.0 * 60.0))
            i = min(i_avail, self._absorb_i)
            if i <= 0.02 * CAPACITY_AH * (1.0):  # < 6A → float
                self.charge_stage = "float"
            return min(i, batt.headroom_a(dt_s))
        if self.charge_stage == "float":
            # Float holds the battery topped: replace load draw, no more.
            return min(i_avail, batt.headroom_a(dt_s))
        return min(i_avail, batt.headroom_a(dt_s))

    # -- ambient/thermals ------------------------------------------------------

    def ambient_c(self) -> float:
        swing = 5.0 * math.sin(math.pi * ((self.clock_h % 24.0) - 9.0) / 12.0)
        return self.scn.ambient_c + max(-5.0, swing)


# --- Emission: model state → quantised, noisy device samples --------------------

def _q(value: float, step: float) -> float:
    return round(round(value / step) * step, 6)


class SimSource(TelemetrySource):
    """TelemetrySource that advances a VanModel in (scaled) wall time.

    ``speed`` > 1 runs the van faster than real time (useful on camera and in
    tests). Values depend only on accumulated sim time, so a fixed poll
    cadence reproduces a take exactly.
    """

    name = "sim"
    MODEL_DT_S = 5.0     # internal integration step; polls advance N of these

    def __init__(self, scenario, speed: float = 1.0, warmup_h: float = 0.0,
                 ts_fn=time.time):
        from sim.scenarios import build_model   # local import avoids a cycle
        self.scn = scenario
        self.speed = speed
        self._ts_fn = ts_fn
        self.model, self._rng = build_model(scenario)
        self._last_wall = None
        self._offline: set[str] = set()   # sensors knocked out via command
        if warmup_h > 0:
            # Join a day in progress — the take starts mid-story, not at the
            # scenario's initial conditions.
            self.advance(warmup_h * 3600.0)

    def advance(self, sim_seconds: float) -> None:
        """Step the model forward by sim_seconds in MODEL_DT_S increments."""
        remaining = sim_seconds
        while remaining > 1e-9:
            dt = min(self.MODEL_DT_S, remaining)
            self.model.step(dt)
            remaining -= dt

    async def poll(self) -> list[Sample]:
        now = self._ts_fn()
        if self._last_wall is None:
            self._last_wall = now
        elapsed = max(0.0, now - self._last_wall) * self.speed
        self._last_wall = now
        self.advance(elapsed)
        return self.emit(int(now))

    def emit(self, ts: int) -> list[Sample]:
        m, rng, out = self.model, self._rng, []

        def add(source: str, metric: str, value: float, sigma: float, step: float):
            out.append(Sample(ts, source, metric, _q(value + rng.gauss(0.0, sigma), step)))

        drop = self.scn.dropout_rate
        v = m.batt_v
        i = m.battery.i_net_a
        if "shunt" not in self._offline and rng.random() >= drop:   # shunt round
            add("shunt", "voltage_v", v, 0.004, 0.01)
            add("shunt", "current_a", i, 0.05, 0.01)
            add("shunt", "power_w", v * i, 0.8, 1.0)
            add("shunt", "soc_pct", m.battery.soc, 0.0, 1.0)
            add("shunt", "temp_c", m.ambient_c() + 2.0 + abs(i) / 200.0 * 6.0, 0.2, 1.0)
            add("shunt", "charge_ah_total", m.battery.charge_ah_total, 0.0, 0.1)
            add("shunt", "discharge_ah_total", m.battery.discharge_ah_total, 0.0, 0.1)
        if "dcc50s" not in self._offline and rng.random() >= drop:   # dcc50s round
            pv_w = m.pv_w
            pv_v = 24.0 + pv_w / 400.0 * 12.0 if pv_w > 0 else 0.0  # 2S panel Vmp-ish
            add("dcc50s", "pv_voltage_v", pv_v, 0.05, 0.1)
            add("dcc50s", "pv_current_a", pv_w / pv_v if pv_v > 1 else 0.0, 0.03, 0.01)
            add("dcc50s", "pv_power_w", pv_w, 0.8, 1.0)
            add("dcc50s", "alt_power_w", m.alt_w, 1.0 if m.alt_w > 0 else 0.0, 1.0)
            add("dcc50s", "charge_current_a", max(0.0, i + m.load_w / max(v, 1.0)), 0.05, 0.01)
            add("dcc50s", "controller_temp_c", m.ambient_c() + pv_w / 300.0 * 14.0, 0.3, 1.0)
            add("dcc50s", "daily_yield_wh", m.daily_yield_wh, 0.0, 1.0)
        if m.hvac is not None and "hvac" not in self._offline:   # cabin sensor round
            add("hvac", "cabin_temp_c", m.hvac.cabin_c, 0.05, 0.1)
            add("hvac", "mode", m.hvac.mode, 0.0, 1.0)
            add("hvac", "setpoint_c", m.hvac.setpoint_c, 0.0, 0.5)
            add("hvac", "hvac_power_w", m.hvac_w, 0.0, 1.0)
        if m.gps is not None and "gps" not in self._offline:     # GPS round
            add("gps", "lat", m.gps.lat, 0.00002, 0.00001)   # ~2m fix jitter
            add("gps", "lon", m.gps.lon, 0.00002, 0.00001)
            add("gps", "speed_mph", m.gps.speed_mph, 0.2, 0.1)
            add("gps", "heading_deg", m.gps.heading, 0.0, 1.0)
            add("gps", "trip_mi", m.gps.trip_mi, 0.0, 0.1)
        return out

    def apply_command(self, cmd: dict) -> bool:
        if cmd.get("target") == "sensor":
            # Take a simulated sensor offline (or back): its samples stop,
            # the last reading ages, and staleness handling does the rest —
            # real behaviour, not painted-on state.
            source = cmd.get("source")
            if source not in ("shunt", "dcc50s", "hvac", "gps"):
                return False
            if cmd.get("offline"):
                self._offline.add(source)
            else:
                self._offline.discard(source)
            return True
        return self.model.apply_command(cmd)
