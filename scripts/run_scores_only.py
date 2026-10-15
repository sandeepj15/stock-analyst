import asyncio
import logging
from packages.common.db import session_scope
from apps.worker.jobs import compute_all_scores_job, sync_analyst_estimates_job

logging.basicConfig(level=logging.INFO)

async def main():
    print('Syncing analyst estimates...')
    await sync_analyst_estimates_job({})
    print('Computing scores and ML forecasts...')
    await compute_all_scores_job({})

if __name__ == "__main__":
    asyncio.run(main())
