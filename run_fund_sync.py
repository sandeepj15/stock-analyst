import asyncio
from packages.common.config import get_settings
from packages.common.logging import configure_logging
from apps.worker.jobs import sync_quarterly_fundamentals_job

async def main():
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    await sync_quarterly_fundamentals_job({})

asyncio.run(main())
