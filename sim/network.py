"""Simulated connectivity: 5G, local Wi-Fi, and a roof-mounted Starlink Mini.

Modelled on what the real hardware reports:
- Starlink's local gRPC API (192.168.100.1:9200) exposes state, pop ping
  latency, up/down throughput, obstruction fraction and dish alerts
  [verified-external — starlink-grpc-tools ecosystem].
- Starlink Mini: native 12-48V DC, ~17-25W steady state (post-2026
  firmware), ~60W boot peak [verified-external] — so the dish is a real
  battery load in the van model, unlike 5G (the Surface's own modem) or
  joining someone else's Wi-Fi.

The uplink carries internet only; AI and telemetry stay on the device
regardless of mode — the panel says so.
"""
from __future__ import annotations

import random

MODE_OFF, MODE_CELL, MODE_WIFI, MODE_STARLINK = 0.0, 1.0, 2.0, 3.0
MODES = {"off": MODE_OFF, "cell": MODE_CELL, "wifi": MODE_WIFI,
         "starlink": MODE_STARLINK}

STARLINK_BOOT_S = 45.0
STARLINK_BOOT_W = 58.0


class NetworkSim:
    def __init__(self, seed: int):
        self._rng = random.Random(seed ^ 0x5EEDF00D)
        self.mode = MODE_OFF
        self._boot_left_s = 0.0
        self._obstruction = 0.06     # roof dish near trees: slow random walk
        self._cell_rsrp = -92.0      # dBm, wanders with "location"
        self._wifi_rssi = -58.0
        # Last-step observables for the emitter.
        self.signal_pct = 0.0
        self.latency_ms = 0.0
        self.down_mbps = 0.0
        self.up_mbps = 0.0
        self.starlink_state = 0.0    # 0 booting, 1 online, 2 obstructed
        self.starlink_power_w = 0.0
        self.obstruction_pct = 0.0

    def set_mode(self, mode_name: str) -> bool:
        if mode_name not in MODES:
            return False
        new = MODES[mode_name]
        if new == MODE_STARLINK and self.mode != MODE_STARLINK:
            self._boot_left_s = STARLINK_BOOT_S
        self.mode = new
        return True

    def step(self, dt_s: float) -> None:
        r = self._rng
        self._obstruction = min(0.25, max(0.0,
            self._obstruction + r.uniform(-0.004, 0.004)))
        self._cell_rsrp = min(-75.0, max(-112.0,
            self._cell_rsrp + r.uniform(-0.6, 0.6)))
        self._wifi_rssi = min(-45.0, max(-72.0,
            self._wifi_rssi + r.uniform(-0.5, 0.5)))

        self.starlink_power_w = 0.0
        self.obstruction_pct = self._obstruction * 100.0

        if self.mode == MODE_OFF:
            self.signal_pct = 0.0
            self.latency_ms = 0.0
            self.down_mbps = 0.0
            self.up_mbps = 0.0
            return

        if self.mode == MODE_CELL:
            # Map RSRP -112..-75 → 0..100%.
            q = (self._cell_rsrp + 112.0) / 37.0
            self.signal_pct = q * 100.0
            self.latency_ms = 65.0 - 25.0 * q + r.uniform(-4, 4)
            self.down_mbps = max(5.0, 300.0 * q ** 2 + r.uniform(-15, 15))
            self.up_mbps = max(1.0, 40.0 * q ** 2 + r.uniform(-3, 3))
            return

        if self.mode == MODE_WIFI:
            q = (self._wifi_rssi + 72.0) / 27.0
            self.signal_pct = q * 100.0
            # Coffee-shop / RV-park backhaul: fine signal, modest pipe.
            self.latency_ms = 24.0 - 12.0 * q + r.uniform(-2, 6)
            self.down_mbps = max(2.0, 60.0 * q + r.uniform(-8, 8))
            self.up_mbps = max(1.0, 18.0 * q + r.uniform(-3, 3))
            return

        # Starlink Mini.
        if self._boot_left_s > 0:
            self._boot_left_s -= dt_s
            self.starlink_state = 0.0
            self.starlink_power_w = STARLINK_BOOT_W + r.uniform(-3, 3)
            self.signal_pct = 0.0
            self.latency_ms = 0.0
            self.down_mbps = 0.0
            self.up_mbps = 0.0
            return
        obstructed_now = r.random() < self._obstruction * 0.6
        self.starlink_state = 2.0 if obstructed_now else 1.0
        clear = 1.0 - self._obstruction
        self.signal_pct = clear * 100.0
        self.starlink_power_w = 17.0 + 9.0 * (self.down_mbps / 250.0) + r.uniform(-1.5, 1.5)
        self.latency_ms = (30.0 + 25.0 * self._obstruction
                           + (40.0 if obstructed_now else 0.0) + r.uniform(-4, 4))
        self.down_mbps = max(5.0, 230.0 * clear ** 2 + r.uniform(-20, 20)
                             - (120.0 if obstructed_now else 0.0))
        self.up_mbps = max(2.0, 24.0 * clear + r.uniform(-3, 3))
