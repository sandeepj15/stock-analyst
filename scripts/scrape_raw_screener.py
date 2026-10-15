import argparse
import asyncio
import logging
from datetime import datetime, UTC
import random

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.logging import configure_logging
from packages.common.models import Instrument
from packages.common.rate_limit import ProviderHealth, RetryPolicy, call_with_retry
from packages.fundamentals.models import RawProviderScrape

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
BASE_URL = "https://www.screener.in"

async def _fetch_html(symbol: str, exchange: str) -> str | None:
    if exchange.upper() != "NSE":
        return None

    def _do_request() -> str | None:
        with httpx.Client(follow_redirects=True) as client:
            for path in (f"/company/{symbol.upper()}/consolidated/", f"/company/{symbol.upper()}/"):
                resp = client.get(f"{BASE_URL}{path}", headers={"User-Agent": USER_AGENT}, timeout=30.0)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                # If consolidated returns 200 with an empty table skeleton (no period headers),
                # fall back to the standalone page instead of storing empty tables.
                if "consolidated" in path:
                    idx = resp.text.find('id="quarters"')
                    if idx != -1:
                        sub = resp.text[idx:idx+4000]
                        if not any(m in sub for m in ("Jun 20", "Sep 20", "Dec 20", "Mar 20")):
                            continue
                    else:
                        continue
                return resp.text
        return None

    return await asyncio.to_thread(_do_request)

async def _scrape_one(symbol: str, exchange: str, instrument_id, retry_policy, health, semaphore):
    async with semaphore:
        await asyncio.sleep(random.uniform(5.0, 10.0))
        attempt = 0
        while attempt < retry_policy.max_attempts:
            attempt += 1
            try:
                html_content = await _fetch_html(symbol, exchange)
                if not html_content:
                    return False
                
                async with session_scope() as session:
                    stmt = pg_insert(RawProviderScrape).values(
                        instrument_id=instrument_id,
                        provider="screener_in",
                        url=f"{BASE_URL}/company/{symbol.upper()}/",
                        html_content=html_content,
                        scraped_at=datetime.now(UTC)
                    )
                    await session.execute(stmt)
                    await session.commit()
                
                logger.info(f"Scraped raw HTML for {symbol}")
                health.record_success()
                return True
            except Exception as exc:
                health.record_failure()
                if attempt >= retry_policy.max_attempts:
                    logger.error(f"Failed to scrape {symbol}: {exc}")
                    break
                await asyncio.sleep(retry_policy.delay_for_attempt(attempt))
        return False

async def main(concurrency: int):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    
    retry_policy = RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=10.0)
    health = ProviderHealth(name="screener_in_raw", failure_threshold=50)
    semaphore = asyncio.Semaphore(concurrency)

    async with session_scope() as session:
        scraped_stmt = select(RawProviderScrape.instrument_id).where(RawProviderScrape.provider == "screener_in")
        scraped_ids = set((await session.execute(scraped_stmt)).scalars().all())

        stmt = select(Instrument).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
        all_instruments = (await session.execute(stmt)).scalars().all()
        
        instruments = [inst for inst in all_instruments if inst.id not in scraped_ids]
        logger.info(f"Skipping {len(all_instruments) - len(instruments)} already scraped instruments. {len(instruments)} remaining.")
    
    tasks = [_scrape_one(inst.symbol, inst.exchange, inst.id, retry_policy, health, semaphore) for inst in instruments]
    results = await asyncio.gather(*tasks)
    
    succeeded = sum(1 for r in results if r)
    print(f"Finished raw scraping. Succeeded: {succeeded}/{len(instruments)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(main(args.concurrency))
