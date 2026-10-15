import asyncio
import logging
import time
from packages.common.config import get_settings
from packages.common.logging import configure_logging
from apps.worker.jobs import (
    sync_quarterly_fundamentals_job,
    sync_fundamentals_job,
    compute_all_scores_job,
)

logger = logging.getLogger(__name__)

async def main():
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    t0 = time.time()
    print("=== 1/3: Starting Quarterly Fundamentals Sync ===", flush=True)
    res_q = await sync_quarterly_fundamentals_job({})
    print(
        f"Quarterly sync completed in {time.time() - t0:.1f}s: "
        f"Synced={len(res_q.get('synced', []))}, Failed={len(res_q.get('failed', []))}",
        flush=True,
    )

    t1 = time.time()
    print("=== 2/3: Starting Annual Fundamentals Sync ===", flush=True)
    res_fy = await sync_fundamentals_job({})
    print(
        f"Annual sync completed in {time.time() - t1:.1f}s: "
        f"Synced={len(res_fy.get('synced', []))}, Failed={len(res_fy.get('failed', []))}",
        flush=True,
    )

    t2 = time.time()
    print("=== 3/3: Recomputing Research Scores for all instruments ===", flush=True)
    res_scores = await compute_all_scores_job({})
    print(
        f"Scores computation completed in {time.time() - t2:.1f}s: "
        f"Synced={len(res_scores.get('synced', []))}, Failed={len(res_scores.get('failed', []))}",
        flush=True,
    )

    print(f"=== ALL DONE in {time.time() - t0:.1f}s! ===", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
