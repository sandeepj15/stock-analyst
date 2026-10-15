import asyncio
import logging
import time
from apps.worker.jobs import compute_all_scores_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

async def main():
    print("Starting full re-computation of research scores for all active stocks...")
    t0 = time.time()
    results = await compute_all_scores_job({})
    t1 = time.time()
    scored = len(results.get("scored", []))
    failed = len(results.get("failed", []))
    print(f"\n==========================================")
    print(f"Research Score Recomputation Completed!")
    print(f"Total Scored: {scored}")
    print(f"Total Failed: {failed}")
    print(f"Elapsed Time: {t1 - t0:.2f} seconds")
    if failed > 0:
        print("\nFailed instruments summary:")
        for f in results.get("failed", [])[:20]:
            print(" -", f)
    print(f"==========================================")

if __name__ == "__main__":
    asyncio.run(main())
