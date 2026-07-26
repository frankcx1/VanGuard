"""vanguard-poller — polls the configured TelemetrySource into SQLite.

Run:  python -m poller [--config config/devices.yaml]

Kept as its own process (separate from the API) so a crashed model service
never costs telemetry history (PLAN.md §7).
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from poller.config import build_source, load_config
from poller.store import Store

log = logging.getLogger("vanguard.poller")

MAINTENANCE_EVERY_S = 300


async def run(cfg: dict) -> None:
    source = build_source(cfg)
    store = await Store(cfg.get("db_path", "vanguard.db")).open()
    interval = float(cfg.get("poll_interval_s", 5))
    log.info("source=%s simulated=%s interval=%.0fs db=%s",
             source.name, source.simulated, interval, store.db_path)
    since_maintenance = 0.0
    try:
        while True:
            samples = await source.poll()
            await store.write(samples)
            if samples:
                log.debug("wrote %d samples", len(samples))
            else:
                log.warning("empty poll round (dropout or stale device)")
            since_maintenance += interval
            if since_maintenance >= MAINTENANCE_EVERY_S:
                since_maintenance = 0.0
                rows = await store.downsample()
                await store.prune()
                log.info("maintenance: downsampled %d rows, pruned", rows)
            await asyncio.sleep(interval)
    finally:
        await source.close()
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="vanguard-poller")
    parser.add_argument("--config", default=None, help="path to devices.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(run(load_config(args.config)))
    except KeyboardInterrupt:
        log.info("stopped")


if __name__ == "__main__":
    main()
