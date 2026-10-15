#!/bin/bash
set -e

echo "Expanding universe to top 1500..."
DATABASE_URL=postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge .venv/bin/python scripts/expand_universe.py

echo "Starting OHLCV backfill (this will take a while)..."
docker compose exec -T worker python scripts/seed_dev_data.py --skip-universe

echo "Triggering ML forecasts and scores calculation..."
cat << 'PYEOF' > scripts/run_all_jobs.py
import asyncio
import logging
from packages.common.db import session_scope
from apps.worker.jobs import compute_all_scores_job, sync_analyst_estimates_job, sync_quarterly_fundamentals_job

logging.basicConfig(level=logging.INFO)

async def main():
    print('Syncing fundamentals...')
    await sync_quarterly_fundamentals_job({})
    print('Syncing analyst estimates...')
    await sync_analyst_estimates_job({})
    print('Computing scores and ML forecasts...')
    await compute_all_scores_job({})

if __name__ == "__main__":
    asyncio.run(main())
PYEOF

docker compose exec -T worker python scripts/run_all_jobs.py
echo "All done!"
