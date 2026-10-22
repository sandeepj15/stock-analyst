import argparse
import asyncio
import logging
from datetime import datetime, UTC, date
import os
import random
import re

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, delete, text
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
    _parse_quarterly_table,
)
from packages.scoring.components import compute_universe_valuation_values
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

async def fetch_screener_page(client: httpx.AsyncClient, symbol: str) -> tuple[str | None, str | None, bool]:
    """Try consolidated first, then standalone. Returns (html, url, is_rate_limited)."""
    for path in (f"/company/{symbol.upper()}/consolidated/", f"/company/{symbol.upper()}/"):
        url = f"{BASE_URL}{path}"
        try:
            resp = await client.get(url, timeout=20.0)
            if resp.status_code == 429:
                return None, None, True
            if resp.status_code == 200:
                html = resp.text
                if 'id="quarters"' in html:
                    if "consolidated" in path:
                        idx = html.find('id="quarters"')
                        sub = html[idx:idx+4000]
                        if not any(m in sub for m in ("Jun 20", "Sep 20", "Dec 20", "Mar 20")):
                            continue
                    return html, url, False
        except Exception as e:
            logger.debug(f"Fetch error {url}: {e}")
    return None, None, False

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    cookies = {}
    if settings.SCREENER_SESSION_ID:
        cookies["sessionid"] = settings.SCREENER_SESSION_ID
    if settings.SCREENER_CSRF_TOKEN:
        cookies["csrftoken"] = settings.SCREENER_CSRF_TOKEN

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    # Query candidate instruments ordered by market liquidity/turnover
    query = text("""
        WITH max_qtr AS (
            SELECT instrument_id, MAX(period_end) as max_period
            FROM fundamental_snapshots
            WHERE period_type = 'Q'
            GROUP BY instrument_id
        ),
        latest_turnover AS (
            SELECT DISTINCT ON (instrument_id) instrument_id, (close * volume) as turnover
            FROM ohlcv_daily
            ORDER BY instrument_id, trading_date DESC
        )
        SELECT i.id, i.symbol, i.company_name, i.exchange, m.max_period
        FROM instruments i
        LEFT JOIN max_qtr m ON m.instrument_id = i.id
        LEFT JOIN latest_turnover t ON t.instrument_id = i.id
        WHERE i.active = true AND i.instrument_type = 'EQUITY'
          AND (m.max_period IS NULL OR m.max_period <= '2026-06-30')
        ORDER BY t.turnover DESC NULLS LAST
    """)

    async with session_scope() as session:
        rows = (await session.execute(query)).all()
        candidates = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]

    if args.offset:
        candidates = candidates[args.offset:]
    if args.limit:
        candidates = candidates[:args.limit]

    total = len(candidates)
    print(f"\n=======================================================", flush=True)
    print(f"🚀 Starting Earnings Season Sweep", flush=True)
    print(f"Candidates to check: {total} stocks (June 2026 or older in DB)", flush=True)
    print(f"Concurrency: {args.concurrency} | Authenticated Session: {bool(cookies)}", flush=True)
    print(f"=======================================================\n", flush=True)

    print(f"Precomputing universe valuation percentiles once for the sweep...", flush=True)
    async with session_scope() as session:
        universe_val = await compute_universe_valuation_values(session, datetime.now(UTC))

    provider_fy = ScreenerInFundamentalProvider()
    provider_q = ScreenerInQuarterlyFundamentalProvider()
    semaphore = asyncio.Semaphore(args.concurrency)

    updated_stocks = []
    skipped_count = 0
    not_found_count = 0
    rate_limit_hits = 0

    async with httpx.AsyncClient(headers=headers, cookies=cookies, follow_redirects=True) as client:
        for idx, (inst_id, symbol, company_name, exchange, max_period) in enumerate(candidates, 1):
            async with semaphore:
                await asyncio.sleep(random.uniform(0.8, 1.6))

                html, url, is_429 = await fetch_screener_page(client, symbol)
                if is_429:
                    rate_limit_hits += 1
                    print(f"⚠️ [{idx}/{total}] {symbol}: Rate limit hit (429)! Backing off for 45s...", flush=True)
                    await asyncio.sleep(45.0)
                    html, url, is_429 = await fetch_screener_page(client, symbol)
                    if is_429:
                        print(f"❌ [{idx}/{total}] {symbol}: Repeated 429. Skipping.", flush=True)
                        continue

                if not html:
                    not_found_count += 1
                    continue

                # Check if new quarter exists in HTML
                soup = BeautifulSoup(html, "html.parser")
                q_sec = soup.find("section", id="quarters")
                if not q_sec:
                    continue

                parsed_quarters = _parse_quarterly_table(q_sec)
                if not parsed_quarters:
                    continue

                latest_screener_p = max(q["period_end"] for q in parsed_quarters)
                if max_period and latest_screener_p <= max_period:
                    skipped_count += 1
                    if idx % 25 == 0 or idx == total:
                        print(f"[{idx}/{total}] Scanned up to {symbol} (Unchanged: {latest_screener_p})", flush=True)
                    continue

                # NEW DATA FOUND!
                new_q = next((q for q in parsed_quarters if q["period_end"] == latest_screener_p), {})
                rev_cr = float(new_q.get("revenue") or 0) / 1e7
                pat_cr = float(new_q.get("pat") or 0) / 1e7
                print(f"🌟 [{idx}/{total}] {symbol}: NEW QUARTER FOUND! Period: {latest_screener_p} | Sales: ₹{rev_cr:,.1f} Cr | PAT: ₹{pat_cr:,.1f} Cr", flush=True)

                try:
                    async with session_scope() as session:
                        # 1. Update raw HTML
                        await session.execute(
                            delete(RawProviderScrape).where(
                                RawProviderScrape.instrument_id == inst_id,
                                RawProviderScrape.provider == "screener_in",
                            )
                        )
                        scrape = RawProviderScrape(
                            instrument_id=inst_id,
                            provider="screener_in",
                            url=url,
                            html_content=html,
                            scraped_at=datetime.now(UTC),
                        )
                        session.add(scrape)
                        await session.flush()

                        # 2. Update structured JSON
                        parsed_json = parse_screener_html(html)
                        await session.execute(
                            delete(StructuredProviderData).where(
                                StructuredProviderData.instrument_id == inst_id,
                                StructuredProviderData.provider == "screener_in",
                            )
                        )
                        session.add(StructuredProviderData(
                            instrument_id=inst_id,
                            provider="screener_in",
                            data=parsed_json,
                            parsed_at=datetime.now(UTC),
                            source_scrape_id=scrape.id,
                        ))

                        # 3. Ingest snapshots
                        inst = await session.get(Instrument, inst_id)
                        await sync_fundamentals(provider_fy, session, inst)
                        await sync_fundamentals(provider_q, session, inst)

                        # 4. Recompute score
                        await compute_research_score(session, inst, precomputed_universe_valuation=universe_val)
                        await session.commit()

                    updated_stocks.append({
                        "symbol": symbol,
                        "period": str(latest_screener_p),
                        "revenue_cr": round(rev_cr, 1),
                        "pat_cr": round(pat_cr, 1),
                    })
                except Exception as e:
                    print(f"❌ Error updating {symbol}: {e}", flush=True)

    # Invalidate Redis caches if any stocks updated
    if updated_stocks:
        print(f"\nPurging Redis listing caches for {len(updated_stocks)} updated stocks...", flush=True)
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            for pat in ["instruments_listing:*", "instruments_search:*"]:
                keys = await r.keys(pat)
                if keys:
                    await r.delete(*keys)
            await r.aclose()
        except Exception as e:
            print(f"Redis purge warning: {e}", flush=True)

    print(f"\n=======================================================", flush=True)
    print(f"🎉 Earnings Season Sweep Completed!", flush=True)
    print(f"Total Scanned: {total}", flush=True)
    print(f"New Data Found & Updated: {len(updated_stocks)} stocks", flush=True)
    print(f"Already Latest on Screener: {skipped_count}", flush=True)
    for u in updated_stocks:
        print(f"  • {u['symbol']}: {u['period']} | Sales: ₹{u['revenue_cr']} Cr | PAT: ₹{u['pat_cr']} Cr", flush=True)
    print(f"=======================================================\n", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
