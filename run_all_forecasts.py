import asyncio
from apps.worker.jobs import generate_ml_forecasts_job
from packages.common import cache

async def main():
    print("Starting ML forecast generation for all stocks...")
    result = await generate_ml_forecasts_job({})
    print(f"Finished: {result}")
    deleted = await cache.delete_pattern("instruments_listing:v1:*")
    print(f"Invalidated listing cache ({deleted} keys deleted)")

if __name__ == "__main__":
    asyncio.run(main())
