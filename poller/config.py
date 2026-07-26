"""Config loading: config/devices.yaml, falling back to the committed example.

devices.yaml is gitignored on purpose — it will hold BLE MAC addresses.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "devices.yaml"
EXAMPLE_PATH = REPO_ROOT / "config" / "devices.example.yaml"


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else (CONFIG_PATH if CONFIG_PATH.exists() else EXAMPLE_PATH)
    with p.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or "source" not in cfg:
        raise ValueError(f"invalid config at {p}: needs at least 'source:'")
    return cfg


def build_source(cfg: dict):
    """Factory for the configured TelemetrySource."""
    kind = cfg["source"]
    if kind == "sim":
        from sim.scenarios import get_scenario
        from sim.van_model import SimSource
        sim_cfg = cfg.get("sim", {})
        return SimSource(
            get_scenario(sim_cfg.get("scenario", "sunny_midday")),
            speed=float(sim_cfg.get("speed", 1.0)),
        )
    if kind == "replay":
        from sim.replay import ReplaySource
        r = cfg.get("replay", {})
        return ReplaySource(
            REPO_ROOT / r["capture"],
            speed=float(r.get("speed", 1.0)),
            loop=bool(r.get("loop", True)),
        )
    if kind == "live":
        raise NotImplementedError(
            "LiveSource lands at M2, after the M1 hardware handshake gate"
        )
    raise ValueError(f"unknown source '{kind}' (live|sim|replay)")
