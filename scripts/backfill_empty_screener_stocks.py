import asyncio
import logging
import random
import re
import time
from datetime import datetime, UTC

import httpx
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.logging import configure_logging
from packages.common.models import Instrument
from packages.fundamentals.ingestion import sync_fundamentals
from packages.fundamentals.models import RawProviderScrape, StructuredProviderData, FundamentalSnapshot
from packages.fundamentals.providers.screener_in_provider import (
    ScreenerInFundamentalProvider,
    ScreenerInQuarterlyFundamentalProvider,
)
from scripts.parse_structured_screener import parse_screener_html

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
BASE_URL = "https://www.screener.in"

async def get_candidate_instruments() -> list[Instrument]:
    async with session_scope() as session:
        instruments = (await session.execute(
            select(Instrument).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
        )).scalars().all()
        inst_by_id = {i.id: i for i in instruments}

        scrapes = (await session.execute(
            select(RawProviderScrape).where(RawProviderScrape.provider == "screener_in")
        )).scalars().all()

        latest_scrape_by_inst: dict = {}
        for s in scrapes:
            if s.instrument_id not in latest_scrape_by_inst or s.scraped_at > latest_scrape_by_inst[s.instrument_id].scraped_at:
                latest_scrape_by_inst[s.instrument_id] = s

        candidates = []
        for inst_id, s in latest_scrape_by_inst.items():
            if inst_id not in inst_by_id:
                continue
            html = s.html_content or ""
            idx = html.find('id="quarters"')
            if idx == -1:
                candidates.append(inst_by_id[inst_id])
                continue
            sub = html[idx:idx+4000]
            dates = re.findall(r'(?:Jun|Sep|Dec|Mar)\s+20\d\d', sub)
            if not dates:
                candidates.append(inst_by_id[inst_id])

        return sorted(candidates, key=lambda x: x.symbol)

async def process_instrument(
    client: httpx.AsyncClient,
    inst: Instrument,
    semaphore: asyncio.Semaphore,
    provider_fy: ScreenerInFundamentalProvider,
    provider_q: ScreenerInQuarterlyFundamentalProvider,
    idx: int,
    total: int,
) -> dict:
    async with semaphore:
        await asyncio.sleep(random.uniform(0.3, 0.8))
        symbol = inst.symbol
        url = f"{BASE_URL}/company/{symbol}/"
        try:
            resp = await client.get(url, timeout=20.0)
            if resp.status_code == 404:
                return {"symbol": symbol, "status": "404", "q_count": 0, "fy_count": 0}
            resp.raise_for_status()
            html = resp.text

            # Check if this standalone page actually has quarters data
            has_dates = bool(re.search(r'(?:Jun|Sep|Dec|Mar)\s+20\d\d', html[html.find('id="quarters"'):html.find('id="quarters"')+4000])) if 'id="quarters"' in html else False
            if not has_dates:
                return {"symbol": symbol, "status": "no_data_on_screener", "q_count": 0, "fy_count": 0}

            # 1. Save raw HTML
            async with session_scope() as session:
                await session.execute(
                    delete(RawProviderScrape).where(
                        RawProviderScrape.instrument_id == inst.id,
                        RawProviderScrape.provider == "screener_in"
                    )
                )
                scrape = RawProviderScrape(
                    instrument_id=inst.id,
                    provider="screener_in",
                    url=url,
                    html_content=html,
                    scraped_at=datetime.now(UTC),
                )
                session.add(scrape)
                await session.flush()
                scrape_id = scrape.id

                # 2. Parse structured data
                parsed = parse_screener_html(html)
                await session.execute(
                    delete(StructuredProviderData).where(
                        StructuredProviderData.instrument_id == inst.id
                    )
                )
                st = StructuredProviderData(
                    instrument_id=inst.id,
                    provider="screener_in",
                    data=parsed,
                    parsed_at=datetime.now(UTC),
                    source_scrape_id=scrape_id,
                )
                session.add(st)
                await session.commit()

            # 3. Ingest FundamentalSnapshots
            async with session_scope() as session:
                res_fy = await sync_fundamentals(provider_fy, session, inst)
                res_q = await sync_fundamentals(provider_q, session, inst)

            print(f"[{idx}/{total}] Fixed {symbol}: {res_q.rows_processed} Quarters, {res_fy.rows_processed} Annual FYs", flush=True)
            return {
                "symbol": symbol,
                "status": "success",
                "q_count": res_q.rows_processed,
                "fy_count": res_fy.rows_processed,
            }
        except Exception as exc:
            logger.error("Error fixing %s: %s", symbol, exc)
            print(f"[{idx}/{total}] FAILED {symbol}: {exc}", flush=True)
            return {"symbol": symbol, "status": f"error: {exc}", "q_count": 0, "fy_count": 0}

async def main(concurrency: int = 4):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    candidates = await get_candidate_instruments()
    total = len(candidates)
    print(f"\n=======================================================")
    print(f"Found {total} candidate instruments with empty scrapes.")
    print(f"Starting standalone scrape, parsing, and snapshot sync...")
    print(f"Concurrency: {concurrency}")
    print(f"=======================================================\n")

    provider_fy = ScreenerInFundamentalProvider()
    provider_q = ScreenerInQuarterlyFundamentalProvider()
    semaphore = asyncio.Semaphore(concurrency)

    headers = {"User-Agent": USER_AGENT}
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, limits=limits) as client:
        tasks = [
            process_instrument(client, inst, semaphore, provider_fy, provider_q, i + 1, total)
            for i, inst in enumerate(candidates)
        ]
        results = await asyncio.gather(*tasks)

    successes = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] != "success"]

    print(f"\n=======================================================")
    print(f"BACKFILL COMPLETE!")
    print(f"Successfully Fixed & Synced: {len(successes)} / {total}")
    print(f"Failed / No data: {len(failed)}")
    if failed:
        print("Sample un-synced:", failed[:10])
    print(f"=======================================================\n")

if __name__ == "__main__":
    asyncio.run(main(concurrency=4))
