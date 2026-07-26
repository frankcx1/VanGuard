"""Simulated cabin climate + HVAC (P5 demo mode).

Models a cabin whose temperature drifts toward ambient (plus daytime solar
gain), with two appliances pulling it toward a setpoint:

- Heater: Webasto-style diesel air heater — heat comes from diesel, the DC
  draw is just fan+pump (~25W). [UNVERIFIED — typical Airtop figure]
- A/C: Cruise N Comfort-style 12V unit — the DC draw is the story:
  ~900W while compressing. [UNVERIFIED — mid-range 12V AC figure]
  Turning it on visibly dives the battery's net power, which is exactly
  what the demo should show.

Demo-mode honesty: this simulates the *behaviour* of the van's real
appliances; the real A/C (Tuya cloud) and heater (BLE SmartTemp) are not
controllable in v1 — see PLAN.md §13. Control of the sim goes through the
commands table, human-initiated only, and only when source=sim.
"""
from __future__ import annotations

MODE_OFF, MODE_HEAT, MODE_COOL = 0.0, 1.0, 2.0

HEATER_ELEC_W = 25.0
HEATER_DEG_PER_H = 8.0        # cabin heating rate at full burn
AC_ELEC_W = 900.0
AC_DEG_PER_H = 6.0            # cabin cooling rate while compressing
CABIN_TAU_H = 1.6             # passive drift time constant toward ambient
SOLAR_GAIN_C = 4.0            # midday greenhouse offset at full sun
HYSTERESIS_C = 0.7


class Hvac:
    def __init__(self, cabin_c: float, mode: float = MODE_OFF,
                 setpoint_c: float = 21.0):
        self.cabin_c = cabin_c
        self.mode = mode
        self.setpoint_c = setpoint_c
        self._running = False      # compressor/burner duty state

    def command(self, mode: float | None = None,
                setpoint_c: float | None = None) -> None:
        if mode is not None and mode in (MODE_OFF, MODE_HEAT, MODE_COOL):
            self.mode = mode
        if setpoint_c is not None:
            self.setpoint_c = max(10.0, min(32.0, float(setpoint_c)))

    def step(self, dt_s: float, ambient_c: float, sun_frac: float) -> float:
        """Advance cabin temp; return the HVAC electrical draw in DC watts."""
        dt_h = dt_s / 3600.0
        target_passive = ambient_c + SOLAR_GAIN_C * max(0.0, sun_frac)
        # Passive drift toward (ambient + solar gain).
        self.cabin_c += (target_passive - self.cabin_c) * min(1.0, dt_h / CABIN_TAU_H)

        if self.mode == MODE_HEAT:
            if self.cabin_c < self.setpoint_c - HYSTERESIS_C:
                self._running = True
            elif self.cabin_c > self.setpoint_c + HYSTERESIS_C:
                self._running = False
            if self._running:
                self.cabin_c += HEATER_DEG_PER_H * dt_h
                return HEATER_ELEC_W
        elif self.mode == MODE_COOL:
            if self.cabin_c > self.setpoint_c + HYSTERESIS_C:
                self._running = True
            elif self.cabin_c < self.setpoint_c - HYSTERESIS_C:
                self._running = False
            if self._running:
                self.cabin_c -= AC_DEG_PER_H * dt_h
                return AC_ELEC_W
        else:
            self._running = False
        return 0.0
