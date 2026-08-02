"""Seed a telemetry DB with N hours of simulated history ending now.

Used by scripts/demo.ps1 so sparklines show a full day the moment the
dashboard opens (paired with sim.warmup_h so the live poller continues
where the seed left off).

Run:  .venv\\Scripts\\python.exe scripts\\seed_db.py <db_path> <scenario> <hours> [take]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_p2 import seed

if __name__ == "__main__":
    db, scenario, hours = sys.argv[1], sys.argv[2], float(sys.argv[3])
    take = sys.argv[4] if len(sys.argv) > 4 else None
    asyncio.run(seed(Path(db), scenario, hours, take=take))
    print(f"seeded {hours}h of {scenario} into {db}"
          + (f" (take {take})" if take else ""))
