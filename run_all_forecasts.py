import asyncio
from apps.worker.jobs import generate_ml_forecasts_job

async def main():
    print("Starting ML forecast generation for all stocks...")
    result = await generate_ml_forecasts_job({})
    print(f"Finished: {result}")

if __name__ == "__main__":
    asyncio.run(main())
