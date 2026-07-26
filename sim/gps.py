"""Simulated GPS + offline POI lookups (P5 demo mode).

Real hardware later: a ~$15 u-blox USB GPS speaking NMEA joins Track M (see
PLAN.md §13); this module keeps the same shape so the swap is a source
change, not a redesign.

POIs are a small curated offline dataset (`sim/data/pois.json`) — "things
to do nearby" must work with zero connectivity, so it comes from local
data, honestly labeled, not a cloud places API.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
EARTH_MI = 3958.8


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_MI * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def load_route(name: str) -> list[tuple[float, float]]:
    with (DATA_DIR / f"route_{name}.json").open(encoding="utf-8") as f:
        return [tuple(p) for p in json.load(f)["waypoints"]]


def load_pois() -> list[dict]:
    with (DATA_DIR / "pois.json").open(encoding="utf-8") as f:
        return json.load(f)


def nearby_pois(lat: float, lon: float, radius_mi: float = 10.0,
                limit: int = 6) -> list[dict]:
    out = []
    for p in load_pois():
        d = haversine_mi(lat, lon, p["lat"], p["lon"])
        if d <= radius_mi:
            out.append({"name": p["name"], "type": p["type"],
                        "dist_mi": round(d, 1), "note": p["note"]})
    out.sort(key=lambda p: p["dist_mi"])
    return out[:limit]


class GpsTrack:
    """Fixed campsite position, or motion along a route polyline.

    Moving mode advances at ~speed_mph with gentle variation from its own
    RNG (separate stream so adding GPS never perturbs the electrical sim's
    seeded behaviour). At the end of the route it parks.
    """

    def __init__(self, seed: int, position: tuple[float, float] | None = None,
                 route: str | None = None, speed_mph: float = 0.0):
        self._rng = random.Random(seed ^ 0x9E3779B9)
        self.speed_mph = 0.0
        self.heading = 0.0
        if route:
            self._pts = load_route(route)
            self._leg = 0
            self._leg_done_mi = 0.0
            self._cruise = speed_mph
            self.lat, self.lon = self._pts[0]
        else:
            self._pts = None
            self.lat, self.lon = position or (49.0770, -125.8120)  # Green Point CG, Tofino
        self.trip_mi = 0.0

    @property
    def moving(self) -> bool:
        return self._pts is not None and self._leg < len(self._pts) - 1

    def step(self, dt_s: float) -> None:
        if not self.moving:
            self.speed_mph = 0.0
            return
        self.speed_mph = max(15.0, self._cruise + self._rng.uniform(-6.0, 6.0))
        advance = self.speed_mph * dt_s / 3600.0
        self.trip_mi += advance
        while advance > 0 and self._leg < len(self._pts) - 1:
            a, b = self._pts[self._leg], self._pts[self._leg + 1]
            leg_mi = haversine_mi(*a, *b)
            remaining = leg_mi - self._leg_done_mi
            if advance < remaining:
                self._leg_done_mi += advance
                f = self._leg_done_mi / leg_mi
                self.lat = a[0] + (b[0] - a[0]) * f
                self.lon = a[1] + (b[1] - a[1]) * f
                self.heading = bearing_deg(*a, *b)
                return
            advance -= remaining
            self._leg += 1
            self._leg_done_mi = 0.0
            self.lat, self.lon = self._pts[self._leg]
        self.speed_mph = 0.0   # route finished; parked
