"""TelemetrySource — the swappable hinge of the whole project (PLAN.md §7).

Everything downstream of this interface (storage, API, dashboard, tools) is
identical whether the numbers come from a real shunt, a simulator, or a
replayed capture. Selected by ``config/devices.yaml: source: live|sim|replay``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    ts: int          # unix seconds
    source: str      # 'shunt' | 'dcc50s'
    metric: str
    value: float


class TelemetrySource(ABC):
    """One poll round returns whatever samples arrived.

    An empty list is a legitimate result — a BLE dropout or a stale device —
    and every caller must tolerate it. The sim can emit dropouts too, so that
    code paths exercised against ``sim`` don't break on ``live`` (PLAN.md §9,
    "sim and live diverge" risk).
    """

    #: 'live' | 'sim' | 'replay' — echoed into every API payload.
    name: str = "abstract"

    @property
    def simulated(self) -> bool:
        """True unless the data comes from the van.

        Integrity guardrail (CLAUDE.md): when this is True the dashboard shows
        a persistent SIM badge and the API stamps ``"simulated": true`` on
        every payload. Non-negotiable.
        """
        return self.name != "live"

    @abstractmethod
    async def poll(self) -> list[Sample]:
        """Return one round of readings across all devices."""

    async def close(self) -> None:
        return None
