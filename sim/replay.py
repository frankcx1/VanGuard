"""ReplaySource — plays back a recorded .jsonl capture at 1× or N×.

Capture format, one JSON object per line:
    {"ts": 1721900000, "source": "shunt", "metric": "voltage_v", "value": 13.12}

Once M1/M3 land this runs the demo on genuine van data, time-shifted —
maximum realism, zero fabrication. Until then it replays sim captures for
deterministic takes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from poller.source import Sample, TelemetrySource


class ReplaySource(TelemetrySource):
    name = "replay"

    def __init__(self, capture_path: str | Path, speed: float = 1.0,
                 loop: bool = True, ts_fn=time.time):
        self.path = Path(capture_path)
        self.speed = speed
        self.loop = loop
        self._ts_fn = ts_fn
        self._records = self._load()
        if not self._records:
            raise ValueError(f"capture is empty: {self.path}")
        self._t0_capture = self._records[0][0]
        self._span = max(1, self._records[-1][0] - self._t0_capture)
        self._t0_wall = None
        self._cursor = 0

    def _load(self) -> list[tuple[int, str, str, float]]:
        records = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                records.append((int(d["ts"]), d["source"], d["metric"], float(d["value"])))
        records.sort(key=lambda r: r[0])
        return records

    async def poll(self) -> list[Sample]:
        now = self._ts_fn()
        if self._t0_wall is None:
            self._t0_wall = now
        elapsed = (now - self._t0_wall) * self.speed
        if self.loop and elapsed >= self._span:
            # Wrap: restart the tape, keep wall time monotonic.
            loops = int(elapsed // self._span)
            elapsed -= loops * self._span
            self._cursor = 0
        target = self._t0_capture + elapsed
        out = []
        while (self._cursor < len(self._records)
               and self._records[self._cursor][0] <= target):
            ts_cap, source, metric, value = self._records[self._cursor]
            # Re-stamp into the present so dashboards treat it as fresh.
            out.append(Sample(int(now - (target - ts_cap)), source, metric, value))
            self._cursor += 1
        return out
