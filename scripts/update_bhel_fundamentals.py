import asyncio
import logging
from datetime import datetime, UTC
import re

import httpx
from bs4 import BeautifulSoup
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
from packages.scoring.engine import compute_research_score

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
BASE_URL = "https://www.screener.in"

def parse_screener_html(html_content: str) -> dict:
    soup = BeautifulSoup(html_content, "html.parser")
    structured_data = {}
    sections = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios", "shareholding"]
    for sec_id in sections:
        section = soup.find("section", id=sec_id)
        if not section:
            continue
        table = section.find("table", class_="data-table")
        if not table:
            continue
        thead = table.find("thead")
        tbody = table.find("tbody")
        if not thead or not tbody:
            continue
        headers = [th.get_text(strip=True) for th in thead.find_all("th")][1:]
        table_data = {}
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            metric_name = tds[0].get_text(strip=True).strip("+- \n\t")
            if not metric_name:
                continue
            values = [td.get_text(strip=True) for td in tds[1:]]
            table_data[metric_name] = dict(zip(headers, values))
        structured_data[sec_id] = table_data
    return structured_data

async def main():
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    print("=== Step 1: Locating BHEL Instrument ===")
    async with session_scope() as session:
        inst = (await session.execute(
            select(Instrument).where(Instrument.symbol == "BHEL")
        )).scalar_one_or_none()
        if not inst:
            print("ERROR: Instrument BHEL not found!")
            return

        print(f"Found instrument: {inst.symbol} ({inst.company_name}) [ID: {inst.id}]")

        # Check existing latest snapshot in DB
        latest_db_snap = (await session.execute(
            select(FundamentalSnapshot)
            .where(FundamentalSnapshot.instrument_id == inst.id, FundamentalSnapshot.period_type == "Q")
            .order_by(FundamentalSnapshot.period_end.desc())
            .limit(1)
        )).scalar_one_or_none()
        if latest_db_snap:
            print(f"Current Latest DB Snapshot: {latest_db_snap.period_end} | Revenue: {float(latest_db_snap.revenue or 0)/1e7:.1f} Cr | PAT: {float(latest_db_snap.pat or 0)/1e7:.1f} Cr")

    print("\n=== Step 2: Fetching Fresh HTML from Screener.in ===")
    urls = [
        f"{BASE_URL}/company/{inst.symbol}/consolidated/",
        f"{BASE_URL}/company/{inst.symbol}/",
    ]
    html = None
    chosen_url = None
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for url in urls:
            try:
                resp = await client.get(url, timeout=25.0)
                if resp.status_code == 200:
                    text = resp.text
                    idx = text.find('id="quarters"')
                    if idx != -1 and "Sep 2026" in text[idx:idx+4000]:
                        html = text
                        chosen_url = url
                        print(f"Successfully fetched {chosen_url} (Length: {len(html)} bytes, contains Sep 2026!)")
                        break
            except Exception as e:
                print(f"Error fetching {url}: {e}")

    if not html:
        print("ERROR: Failed to fetch valid HTML with new data from Screener.")
        return

    print("\n=== Step 3: Updating RawProviderScrape & StructuredProviderData ===")
    async with session_scope() as session:
        # Delete old screener scrape for BHEL and save new one
        await session.execute(
            delete(RawProviderScrape).where(
                RawProviderScrape.instrument_id == inst.id,
                RawProviderScrape.provider == "screener_in",
            )
        )
        scrape = RawProviderScrape(
            instrument_id=inst.id,
            provider="screener_in",
            url=chosen_url,
            html_content=html,
            scraped_at=datetime.now(UTC),
        )
        session.add(scrape)
        await session.flush()

        parsed_data = parse_screener_html(html)
        await session.execute(
            delete(StructuredProviderData).where(
                StructuredProviderData.instrument_id == inst.id,
                StructuredProviderData.provider == "screener_in",
            )
        )
        st = StructuredProviderData(
            instrument_id=inst.id,
            provider="screener_in",
            data=parsed_data,
            parsed_at=datetime.now(UTC),
            source_scrape_id=scrape.id,
        )
        session.add(st)
        await session.commit()
        print("Raw HTML and Structured JSON saved to DB successfully.")

    print("\n=== Step 4: Syncing FundamentalSnapshots into DB ===")
    provider_fy = ScreenerInFundamentalProvider()
    provider_q = ScreenerInQuarterlyFundamentalProvider()

    async with session_scope() as session:
        inst_fresh = await session.get(Instrument, inst.id)
        res_fy = await sync_fundamentals(provider_fy, session, inst_fresh)
        res_q = await sync_fundamentals(provider_q, session, inst_fresh)
        print(f"Sync Results: Quarterly rows={res_q.rows_processed} (inserted: {res_q.rows_inserted}, updated: {res_q.rows_updated})")
        print(f"Sync Results: Annual FY rows={res_fy.rows_processed} (inserted: {res_fy.rows_inserted}, updated: {res_fy.rows_updated})")

    print("\n=== Step 5: Verifying New Fundamental Snapshots in DB ===")
    async with session_scope() as session:
        snaps = (await session.execute(
            select(FundamentalSnapshot)
            .where(FundamentalSnapshot.instrument_id == inst.id, FundamentalSnapshot.period_type == "Q")
            .order_by(FundamentalSnapshot.period_end.desc())
            .limit(5)
        )).scalars().all()
        for s in snaps:
            print(f"  Period: {s.period_end} | Revenue: {float(s.revenue or 0)/1e7:,.1f} Cr | PAT: {float(s.pat or 0)/1e7:,.1f} Cr | EPS: {s.eps} | Source: {s.source} | Ingested: {s.ingested_at}")

    print("\n=== Step 6: Recomputing Research Scores for BHEL ===")
    async with session_scope() as session:
        inst_fresh = await session.get(Instrument, inst.id)
        score_res = await compute_research_score(session, inst_fresh)
        print(f"New Overall Score: {score_res.score:.2f} ({score_res.band}) | Confidence: {score_res.confidence:.1f}%")
        for comp in score_res.components:
            print(f"  Pillar {comp.name}: Score = {comp.score} (weight: {comp.weight_used}, contrib: {comp.contribution})")

    print("\n=== Step 7: Purging Redis Cache Keys ===")
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        keys_to_delete = []
        for pat in ["instruments_listing:*", "instruments_search:*", "*BHEL*", "score:*"]:
            found = await r.keys(pat)
            if found:
                keys_to_delete.extend(found)
        if keys_to_delete:
            await r.delete(*set(keys_to_delete))
            print(f"Purged {len(set(keys_to_delete))} Redis cache keys.")
        await r.aclose()
    except Exception as e:
        print(f"Redis purge warning: {e}")

    print("\n=== BHEL UPDATE COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    asyncio.run(main())
