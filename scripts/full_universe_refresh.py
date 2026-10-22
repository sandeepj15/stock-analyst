import argparse
import asyncio
import json
import logging
import os
import random
from datetime import datetime, UTC, date
from bs4 import BeautifulSoup
import httpx
from sqlalchemy import select, delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.logging import configure_logging
from packages.common.models import Instrument
from packages.fundamentals.models import RawProviderScrape, StructuredProviderData, FundamentalSnapshot
from packages.fundamentals.providers.screener_in_provider import (
    _parse_quarterly_table,
    SOURCE_NAME,
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

async def fetch_and_parse(client: httpx.AsyncClient, path: str):
    url = f"{BASE_URL}{path}"
    try:
        resp = await client.get(url, timeout=20.0)
        if resp.status_code == 429:
            return None, url, [], True
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            q_sec = soup.find("section", id="quarters")
            pq = _parse_quarterly_table(q_sec) if q_sec else []
            return resp.text, url, pq, False
    except Exception as e:
        logger.debug(f"Error fetching {url}: {e}")
    return None, url, [], False

async def get_best_screener_page(client: httpx.AsyncClient, symbol: str):
    """Pick between consolidated and standalone based on actual data freshness."""
    # 1. Fetch consolidated
    c_html, c_url, c_q, is_429 = await fetch_and_parse(client, f"/company/{symbol.upper()}/consolidated/")
    if is_429:
        return None, None, [], True
    c_latest = max((q["period_end"] for q in c_q), default=None)

    # 2. If consolidated is missing, empty, or older than 2026-06-30, fetch standalone
    if not c_latest or c_latest < date(2026, 6, 30):
        await asyncio.sleep(random.uniform(0.6, 1.0))
        s_html, s_url, s_q, is_429 = await fetch_and_parse(client, f"/company/{symbol.upper()}/")
        if is_429:
            return None, None, [], True
        s_latest = max((q["period_end"] for q in s_q), default=None)
        if s_q and (not c_latest or (s_latest and s_latest > c_latest)):
            return s_html, s_url, s_q, False

    if c_html and c_q:
        return c_html, c_url, c_q, False

    # 3. Fallback to standalone if consolidated had no quarters
    s_html, s_url, s_q, is_429 = await fetch_and_parse(client, f"/company/{symbol.upper()}/")
    if is_429:
        return None, None, [], True
    return s_html, s_url, s_q, False

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=3)
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

    # Query all active equity instruments with their current max quarterly period
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
    print(f"🚀 Starting Full Universe Fundamentals Sweep & Comparison", flush=True)
    print(f"Total candidates: {total} stocks", flush=True)
    print(f"Concurrency: {args.concurrency} | Authenticated Session: {bool(cookies)}", flush=True)
    print(f"=======================================================\n", flush=True)

    print(f"Precomputing universe valuation percentiles once for scoring...", flush=True)
    async with session_scope() as session:
        universe_val = await compute_universe_valuation_values(session, datetime.now(UTC))

    semaphore = asyncio.Semaphore(args.concurrency)
    updated_earnings = []
    rescued_ancient = []
    updated_shareholding = []
    already_synced = []
    missing_pages = []
    rate_limit_hits = 0

    async with httpx.AsyncClient(headers=headers, cookies=cookies, follow_redirects=True) as client:
        for idx, (inst_id, symbol, company_name, exchange, max_db_period) in enumerate(candidates, 1):
            async with semaphore:
                await asyncio.sleep(random.uniform(0.7, 1.3))

                html, url, parsed_quarters, is_429 = await get_best_screener_page(client, symbol)
                if is_429:
                    rate_limit_hits += 1
                    print(f"⚠️ [{idx}/{total}] {symbol}: Rate limit hit (429)! Backing off for 40s...", flush=True)
                    await asyncio.sleep(40.0)
                    html, url, parsed_quarters, is_429 = await get_best_screener_page(client, symbol)
                    if is_429:
                        print(f"❌ [{idx}/{total}] {symbol}: Repeated 429. Skipping.", flush=True)
                        continue

                if not html or not parsed_quarters:
                    missing_pages.append(symbol)
                    continue

                latest_screener_p = max(q["period_end"] for q in parsed_quarters)
                now = datetime.now(UTC)

                is_ancient_rescue = max_db_period is None or max_db_period < date(2026, 6, 30)
                is_new_quarter = max_db_period and latest_screener_p > max_db_period

                parsed_json = parse_screener_html(html)
                has_sep_shareholding = False
                if "shareholding" in parsed_json:
                    for k, val_dict in parsed_json["shareholding"].items():
                        if isinstance(val_dict, dict) and "Sep 2026" in val_dict:
                            has_sep_shareholding = True
                            break

                needs_db_update = is_new_quarter or is_ancient_rescue or has_sep_shareholding

                if not needs_db_update and latest_screener_p <= max_db_period:
                    already_synced.append(symbol)
                    if idx % 25 == 0 or idx == total:
                        print(f"[{idx}/{total}] Checked {symbol} (In Sync: {max_db_period})", flush=True)
                    continue

                # Update database
                try:
                    async with session_scope() as session:
                        # 1. Update raw scrape
                        await session.execute(
                            delete(RawProviderScrape).where(
                                RawProviderScrape.instrument_id == inst_id,
                                RawProviderScrape.provider == "screener_in",
                            )
                        )
                        raw_scrape = RawProviderScrape(
                            instrument_id=inst_id,
                            provider="screener_in",
                            url=url,
                            html_content=html,
                            scraped_at=now,
                        )
                        session.add(raw_scrape)
                        await session.flush()

                        # 2. Update structured JSON
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
                            parsed_at=now,
                            source_scrape_id=raw_scrape.id,
                        ))

                        # 3. Upsert quarterly snapshots
                        for q in parsed_quarters:
                            stmt_snap = pg_insert(FundamentalSnapshot).values(
                                instrument_id=inst_id,
                                period_end=q["period_end"],
                                period_type="Q",
                                revenue=q.get("revenue"),
                                ebitda=q.get("ebit"),
                                ebit=q.get("ebit"),
                                pat=q.get("pat"),
                                eps=q.get("eps"),
                                operating_cash_flow=None,
                                free_cash_flow=None,
                                total_assets=None,
                                total_liabilities=None,
                                total_debt=None,
                                cash=None,
                                equity=None,
                                shares_outstanding=None,
                                dividend_yield=None,
                                interest_expense=q.get("interest_expense"),
                                current_assets=None,
                                current_liabilities=None,
                                source="screener_in",
                                source_timestamp=now,
                            ).on_conflict_do_update(
                                constraint="uq_fundamental_snapshot_period_source",
                                set_={
                                    "revenue": q.get("revenue"),
                                    "ebitda": q.get("ebit"),
                                    "ebit": q.get("ebit"),
                                    "pat": q.get("pat"),
                                    "eps": q.get("eps"),
                                    "interest_expense": q.get("interest_expense"),
                                    "source_timestamp": now,
                                }
                            )
                            await session.execute(stmt_snap)

                        # 4. Recompute score if earnings updated or rescued
                        inst = await session.get(Instrument, inst_id)
                        if is_new_quarter or is_ancient_rescue:
                            await compute_research_score(session, inst, precomputed_universe_valuation=universe_val)

                        await session.commit()

                    if is_new_quarter:
                        updated_earnings.append({"symbol": symbol, "old": str(max_db_period), "new": str(latest_screener_p), "url": url})
                        print(f"🌟 [{idx}/{total}] {symbol}: NEW Q2 FY27 EARNINGS! {max_db_period} -> {latest_screener_p} (via {url.split('/')[-2]})", flush=True)
                    elif is_ancient_rescue:
                        rescued_ancient.append({"symbol": symbol, "old": str(max_db_period), "new": str(latest_screener_p), "url": url})
                        print(f"🔄 [{idx}/{total}] {symbol}: RESCUED ANCIENT DATA! {max_db_period} -> {latest_screener_p} (via {url.split('/')[-2]})", flush=True)
                    elif has_sep_shareholding:
                        updated_shareholding.append(symbol)
                        if idx % 25 == 0 or idx == total:
                            print(f"[{idx}/{total}] Updated Sep 2026 Shareholding for {symbol}", flush=True)

                except Exception as e:
                    print(f"❌ [{idx}/{total}] Error updating {symbol}: {e}", flush=True)

    # Sync institutional holdings table
    try:
        from packages.fundamentals.shareholding_flow import sync_all_institutional_holdings
        async with session_scope() as session:
            ih_count = await sync_all_institutional_holdings(session)
            print(f"\nSynced {ih_count} institutional holdings to database.", flush=True)
    except Exception as e:
        print(f"Warning syncing institutional holdings: {e}", flush=True)

    # Invalidate Redis caches
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        for pat in ["instruments_listing:*", "instruments_search:*", "signalforge:stock_diagnostic:*"]:
            keys = await r.keys(pat)
            if keys:
                await r.delete(*keys)
        await r.aclose()
        print("Purged Redis caches.", flush=True)
    except Exception as e:
        print(f"Redis purge warning: {e}", flush=True)

    print(f"\n=======================================================", flush=True)
    print(f"🎉 Full Universe Sweep & Comparison Completed!", flush=True)
    print(f"Total Scanned: {total}", flush=True)
    print(f"Newly Reported Q2 FY27 (Sep 2026) Earnings: {len(updated_earnings)}", flush=True)
    print(f"Rescued Ancient/Stale Stocks (< June 2026): {len(rescued_ancient)}", flush=True)
    print(f"Fresh September 2026 Shareholding Ingested: {len(updated_shareholding)}", flush=True)
    print(f"Already In Sync on Latest Available Data: {len(already_synced)}", flush=True)
    print(f"Missing / 404 Pages: {len(missing_pages)}", flush=True)
    print(f"Rate Limit 429 Hits (auto-recovered): {rate_limit_hits}", flush=True)
    print(f"=======================================================\n", flush=True)

    # Save detailed summary to JSON file
    summary_path = "/tmp/sweep_summary.json"
    with open(summary_path, "w") as f:
        json.dump({
            "scanned": total,
            "updated_earnings": updated_earnings,
            "rescued_ancient": rescued_ancient,
            "updated_shareholding_count": len(updated_shareholding),
            "already_synced_count": len(already_synced),
            "missing_pages": missing_pages,
            "completed_at": datetime.now(UTC).isoformat(),
        }, f, indent=2)
    print(f"Summary report written to {summary_path}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
