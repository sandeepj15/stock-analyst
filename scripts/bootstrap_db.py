"""Database bootstrap script for SignalForge.

Runs during container startup before the API begins accepting requests:
1. Runs Alembic migrations (`alembic upgrade head`) to ensure the DB schema,
   tables, views, and indexes are completely up-to-date.
2. Checks if the `instruments` table has any rows.
3. If empty (brand new server installation), automatically seeds the core
   universe so the platform is immediately functional upon startup.
4. If already populated, exits immediately in ~0.05 seconds.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from sqlalchemy import text
from packages.common.db import session_scope

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bootstrap")


async def bootstrap() -> None:
    logger.info("Applying database migrations (alembic upgrade head)...")
    res = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
    if res.returncode != 0:
        logger.error("Alembic upgrade failed:\n%s\n%s", res.stderr, res.stdout)
        sys.exit(res.returncode)
    logger.info("Database migrations applied successfully.")

    # Check if instruments table has any rows
    async with session_scope() as session:
        result = await session.execute(text("SELECT count(*) FROM instruments"))
        count = result.scalar() or 0

    if count == 0:
        logger.info("Fresh database detected (0 instruments). Seeding initial universe...")
        seed_res = subprocess.run(
            [sys.executable, "scripts/seed_dev_data.py", "--skip-universe", "--days", "30"],
            capture_output=False,
        )
        if seed_res.returncode == 0:
            logger.info("Initial universe seeded successfully.")
            logger.info("Computing initial market regime and research scores for seed universe...")
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import asyncio; from apps.worker.jobs import sync_market_regime, compute_all_scores_job; "
                    "asyncio.run(sync_market_regime({})); asyncio.run(compute_all_scores_job({}))",
                ],
                capture_output=False,
            )
            logger.info("Initial regime and scores ready.")
        else:
            logger.warning("Initial universe seed exited with code %s.", seed_res.returncode)
    else:
        logger.info("Database already populated (%d instruments found). Skipping initial seed.", count)


if __name__ == "__main__":
    asyncio.run(bootstrap())
