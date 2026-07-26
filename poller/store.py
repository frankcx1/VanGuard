"""SQLite storage: raw samples, 1-minute downsamples, tool audit (PLAN.md §7).

Retention policy from the data model:
- ``samples``     raw, 48h
- ``samples_1m``  1-minute avg/min/max/n, 30d
- ``tool_audit``  every AI tool invocation, kept forever (it's the governance
  story — created here so the schema is complete from day one, used at P4)

WAL mode so the poller (writer) and API (reader) never block each other.
"""
from __future__ import annotations

import time
from pathlib import Path

import aiosqlite

from poller.source import Sample

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
  ts INTEGER NOT NULL,
  source TEXT NOT NULL,
  metric TEXT NOT NULL,
  value REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_metric_ts ON samples (source, metric, ts);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples (ts);

CREATE TABLE IF NOT EXISTS samples_1m (
  ts INTEGER NOT NULL,
  source TEXT NOT NULL,
  metric TEXT NOT NULL,
  avg REAL, min REAL, max REAL, n INTEGER,
  PRIMARY KEY (ts, source, metric)
);

CREATE TABLE IF NOT EXISTS tool_audit (
  ts INTEGER NOT NULL,
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  result_hash TEXT NOT NULL,
  device TEXT,
  duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commands (  -- human control commands (P5 demo);
  id INTEGER PRIMARY KEY,              -- the poller applies them to the source
  ts INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  applied INTEGER NOT NULL DEFAULT 0,  -- 0 pending, 1 applied, -1 refused
  applied_ts INTEGER
);
"""

RAW_RETENTION_S = 48 * 3600
DOWNSAMPLE_RETENTION_S = 30 * 24 * 3600


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> "Store":
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        return self

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def write(self, samples: list[Sample]) -> None:
        if not samples:
            return
        await self._db.executemany(
            "INSERT INTO samples (ts, source, metric, value) VALUES (?, ?, ?, ?)",
            [(s.ts, s.source, s.metric, s.value) for s in samples],
        )
        await self._db.commit()

    # -- maintenance -----------------------------------------------------------

    async def downsample(self, now: int | None = None) -> int:
        """Aggregate completed minutes into samples_1m, tracked by high-water
        mark so it's incremental and idempotent."""
        now = int(now if now is not None else time.time())
        cutoff = now // 60 * 60          # only minutes fully in the past
        cur = await self._db.execute("SELECT value FROM meta WHERE key='downsampled_to'")
        row = await cur.fetchone()
        start = int(row[0]) if row else 0
        result = await self._db.execute(
            """
            INSERT OR REPLACE INTO samples_1m (ts, source, metric, avg, min, max, n)
            SELECT (ts/60)*60, source, metric, AVG(value), MIN(value), MAX(value), COUNT(*)
            FROM samples
            WHERE ts >= ? AND ts < ?
            GROUP BY (ts/60)*60, source, metric
            """,
            (start, cutoff),
        )
        await self._db.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('downsampled_to', ?)",
            (str(cutoff),),
        )
        await self._db.commit()
        return result.rowcount

    async def prune(self, now: int | None = None) -> None:
        now = int(now if now is not None else time.time())
        await self._db.execute("DELETE FROM samples WHERE ts < ?", (now - RAW_RETENTION_S,))
        await self._db.execute("DELETE FROM samples_1m WHERE ts < ?", (now - DOWNSAMPLE_RETENTION_S,))
        await self._db.commit()

    # -- reads (the API layer builds on these at P2) -----------------------------

    async def latest(self) -> dict[str, dict[str, tuple[int, float]]]:
        """{source: {metric: (ts, value)}} using each metric's newest sample."""
        cur = await self._db.execute(
            """
            SELECT s.source, s.metric, s.ts, s.value
            FROM samples s
            JOIN (SELECT source, metric, MAX(ts) AS mts FROM samples
                  GROUP BY source, metric) m
              ON s.source = m.source AND s.metric = m.metric AND s.ts = m.mts
            """
        )
        out: dict[str, dict[str, tuple[int, float]]] = {}
        for source, metric, ts, value in await cur.fetchall():
            out.setdefault(source, {})[metric] = (int(ts), float(value))
        return out

    async def history(self, source: str, metric: str, window_s: int,
                      now: int | None = None) -> list[tuple[int, float]]:
        """Raw points if the window fits raw retention, else 1m averages."""
        now = int(now if now is not None else time.time())
        since = now - window_s
        if window_s <= RAW_RETENTION_S:
            cur = await self._db.execute(
                "SELECT ts, value FROM samples WHERE source=? AND metric=? AND ts>=? ORDER BY ts",
                (source, metric, since),
            )
        else:
            cur = await self._db.execute(
                "SELECT ts, avg FROM samples_1m WHERE source=? AND metric=? AND ts>=? ORDER BY ts",
                (source, metric, since),
            )
        return [(int(t), float(v)) for t, v in await cur.fetchall()]

    # -- control commands (P5 demo; poller applies, sim-only) --------------------

    async def enqueue_command(self, payload_json: str) -> int:
        cur = await self._db.execute(
            "INSERT INTO commands (ts, payload_json) VALUES (?, ?)",
            (int(time.time()), payload_json))
        await self._db.commit()
        return cur.lastrowid

    async def pending_commands(self) -> list[tuple[int, str]]:
        cur = await self._db.execute(
            "SELECT id, payload_json FROM commands WHERE applied = 0 ORDER BY id")
        return [(int(i), p) for i, p in await cur.fetchall()]

    async def mark_command(self, cmd_id: int, applied: bool) -> None:
        await self._db.execute(
            "UPDATE commands SET applied = ?, applied_ts = ? WHERE id = ?",
            (1 if applied else -1, int(time.time()), cmd_id))
        await self._db.commit()

    async def audit_recent(self, limit: int = 50) -> list[dict]:
        cur = await self._db.execute(
            "SELECT ts, tool, args_json, result_hash, device, duration_ms "
            "FROM tool_audit ORDER BY ts DESC, rowid DESC LIMIT ?", (limit,))
        return [
            {"ts": int(ts), "tool": tool, "args": args_json,
             "result_hash": rh, "device": device, "duration_ms": dur}
            for ts, tool, args_json, rh, device, dur in await cur.fetchall()
        ]

    async def audit(self, tool: str, args_json: str, result_hash: str,
                    device: str | None, duration_ms: int) -> None:
        await self._db.execute(
            "INSERT INTO tool_audit (ts, tool, args_json, result_hash, device, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (int(time.time()), tool, args_json, result_hash, device, duration_ms),
        )
        await self._db.commit()
