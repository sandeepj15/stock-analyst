import asyncio
import logging
import time
from packages.common.db import session_scope
from apps.worker.jobs import (
    sync_market_regime,
    compute_all_momentum_scans_job,
    generate_ml_forecasts_job
)
from packages.common import cache
from apps.worker.jobs import INSTRUMENTS_LISTING_CACHE_PATTERN

logging.basicConfig(level=logging.INFO)

async def main():
    ctx = {}
    print('Syncing market regime (Market Pulse)...')
    await sync_market_regime(ctx)
    print('Computing momentum scans (Stage 2 flags)...')
    await compute_all_momentum_scans_job(ctx)
    print('Generating ML forecasts...')
    await generate_ml_forecasts_job(ctx)
    print('Clearing cache...')
    await cache.delete_pattern(INSTRUMENTS_LISTING_CACHE_PATTERN)
    print('All missed jobs completed!')

if __name__ == "__main__":
    asyncio.run(main())
