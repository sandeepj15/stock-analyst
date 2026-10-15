import asyncio
import logging
import time

from sqlalchemy import select

from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.listing_queries import latest_fundamental_growth_subquery
from packages.common.logging import configure_logging
from packages.common.models import Instrument
from packages.fundamentals.ingestion import sync_fundamentals
from packages.fundamentals.providers.yfinance_fundamental_provider import (
    YFinanceFundamentalProvider,
    YFinanceQuarterlyFundamentalProvider,
)

logger = logging.getLogger(__name__)

async def get_missing_instruments() -> list[Instrument]:
    async with session_scope() as session:
        growth_sub = latest_fundamental_growth_subquery()
        stmt = (
            select(Instrument)
            .outerjoin(growth_sub, growth_sub.c.instrument_id == Instrument.id)
            .where(
                Instrument.active.is_(True),
                Instrument.instrument_type == "EQUITY",
                growth_sub.c.revenue_growth_yoy.is_(None),
                growth_sub.c.pat_growth_yoy.is_(None),
            )
        )
        return list((await session.execute(stmt)).scalars().all())

async def process_one(
    inst: Instrument,
    provider_q: YFinanceQuarterlyFundamentalProvider,
    provider_fy: YFinanceFundamentalProvider,
    semaphore: asyncio.Semaphore,
    idx: int,
    total: int,
) -> dict:
    async with semaphore:
        symbol = inst.symbol
        try:
            async with session_scope() as session:
                res_q = await sync_fundamentals(provider_q, session, inst)
                res_fy = await sync_fundamentals(provider_fy, session, inst)
            
            print(f"[{idx}/{total}] Synced {symbol}: {res_q.rows_processed} Q, {res_fy.rows_processed} FY", flush=True)
            return {"symbol": symbol, "status": "success", "q": res_q.rows_processed, "fy": res_fy.rows_processed}
        except Exception as exc:
            print(f"[{idx}/{total}] Error {symbol}: {exc}", flush=True)
            return {"symbol": symbol, "status": f"error: {exc}", "q": 0, "fy": 0}

async def main(concurrency: int = 5):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    missing = await get_missing_instruments()
    total = len(missing)
    print(f"\n=======================================================")
    print(f"Found {total} instruments missing YoY growth metrics.")
    print(f"Starting yfinance ingestion with concurrency={concurrency}...")
    print(f"=======================================================\n")

    provider_q = YFinanceQuarterlyFundamentalProvider()
    provider_fy = YFinanceFundamentalProvider()
    semaphore = asyncio.Semaphore(concurrency)

    t0 = time.time()
    tasks = [
        process_one(inst, provider_q, provider_fy, semaphore, i + 1, total)
        for i, inst in enumerate(missing)
    ]
    results = await asyncio.gather(*tasks)
    t1 = time.time()

    successes = [r for r in results if r["status"] == "success" and (r["q"] > 0 or r["fy"] > 0)]
    no_coverage = [r for r in results if r["status"] == "success" and r["q"] == 0 and r["fy"] == 0]
    errors = [r for r in results if r["status"].startswith("error")]

    print(f"\n=======================================================")
    print(f"COMPLETED in {t1 - t0:.1f}s")
    print(f"Successfully Filled: {len(successes)} / {total}")
    print(f"No Coverage on yfinance (e.g. tiny cap / SME): {len(no_coverage)}")
    print(f"Errors: {len(errors)}")
    print(f"=======================================================\n")

if __name__ == "__main__":
    asyncio.run(main(concurrency=6))
