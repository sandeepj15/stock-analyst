"""High-Performance 5-Worker Parallel Screener.in Sweep & Synchronizer.

Discovers and ingests fresh quarterly earnings (Q2 FY27 / Sep 2026) and
shareholding updates across the active equity universe.
Runs 5 concurrent workers, respects rate limits with shared backoff,
ignores recently verified stocks, updates Bronze/Silver/Gold layers,
and recalculates Research Strength scores.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.logging import configure_logging
from packages.common.models import Instrument
from packages.fundamentals.earnings_sync import (
    fetch_bse_financial_results_feed,
    fetch_screener_latest_results_feed,
)
from packages.fundamentals.models import (
    FundamentalSnapshot,
    RawProviderScrape,
    StructuredProviderData,
)
from packages.fundamentals.providers.screener_in_provider import _parse_quarterly_table
from packages.fundamentals.shareholding_flow import sync_all_institutional_holdings
from packages.scoring.components import compute_universe_valuation_values
from packages.scoring.engine import compute_research_score
from scripts.parse_structured_screener import parse_screener_html

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
BASE_URL = "https://www.screener.in"


async def fetch_and_parse(
    client: httpx.AsyncClient, path: str, rate_limit_event: asyncio.Event, request_lock: asyncio.Lock
) -> tuple[str | None, str, list[dict[str, Any]], bool]:
    """Fetch a screener page and parse quarterly table with smooth request pacing."""
    url = f"{BASE_URL}{path}"
    try:
        await rate_limit_event.wait()
        async with request_lock:
            await asyncio.sleep(random.uniform(2.2, 3.2))
            resp = await client.get(url, timeout=20.0)
        if resp.status_code == 429:
            return None, url, [], True
        if resp.status_code == 200:
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            q_sec = soup.find("section", id="quarters")
            pq = _parse_quarterly_table(q_sec) if q_sec else []
            return html, url, pq, False
    except Exception as e:
        logger.debug(f"Error fetching {url}: {e}")
    return None, url, [], False


async def get_best_screener_page(
    client: httpx.AsyncClient, symbol: str, rate_limit_event: asyncio.Event, request_lock: asyncio.Lock
) -> tuple[str | None, str | None, list[dict[str, Any]], bool]:
    """Pick between consolidated and standalone based on data freshness."""
    sym = symbol.upper()
    # 1. Fetch consolidated
    c_html, c_url, c_q, is_429 = await fetch_and_parse(client, f"/company/{sym}/consolidated/", rate_limit_event, request_lock)
    if is_429:
        return None, None, [], True
    c_latest = max((q["period_end"] for q in c_q), default=None)

    # If consolidated returned quarterly data up to 2026, use it directly (authoritative)
    if c_html and c_q and c_latest and c_latest >= date(2026, 3, 31):
        return c_html, c_url, c_q, False

    # 2. Only check standalone if consolidated is missing quarters (standalone-only company)
    s_html, s_url, s_q, is_429 = await fetch_and_parse(client, f"/company/{sym}/", rate_limit_event, request_lock)
    if is_429:
        return None, None, [], True
    if s_html and s_q:
        return s_html, s_url, s_q, False

    return c_html, c_url, c_q, False


async def worker(
    worker_id: int,
    queue: asyncio.Queue,
    client: httpx.AsyncClient,
    rate_limit_event: asyncio.Event,
    request_lock: asyncio.Lock,
    stats: dict[str, Any],
    universe_val: Any,
    total_candidates: int,
    lock: asyncio.Lock,
):
    """Worker task processing items from the queue concurrently."""
    # Stagger worker startup to avoid initial request burst
    await asyncio.sleep(worker_id * 0.5)

    while True:
        try:
            item = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        inst_id, symbol, company_name, exchange, max_db_period = item

        # Check if rate limit pause is active
        await rate_limit_event.wait()

        # Fetch page with retry on rate limit (network calls smoothly paced via request_lock)
        html, url, parsed_quarters, is_429 = await get_best_screener_page(client, symbol, rate_limit_event, request_lock)

        if is_429:
            now_ts = time.time()
            async with lock:
                if now_ts - stats.get("last_429_ts", 0) > 40.0:
                    stats["last_429_ts"] = now_ts
                    rate_limit_event.clear()
                    stats["rate_limit_hits"] += 1
                    print(
                        f"⚠️ [Worker-{worker_id}] Rate limit (429) hit on {symbol}! Pausing all workers for 40s...",
                        flush=True,
                    )
                    await asyncio.sleep(40.0)
                    rate_limit_event.set()
                    print(f"▶️ [Worker-{worker_id}] Resuming all workers...", flush=True)

            # Wait for rate limit event to be set (in case another worker triggered it)
            await rate_limit_event.wait()

            # Retry after pause
            html, url, parsed_quarters, is_429 = await get_best_screener_page(client, symbol, rate_limit_event, request_lock)
            if is_429:
                print(f"❌ [Worker-{worker_id}] Repeated 429 on {symbol}. Skipping.", flush=True)
                async with lock:
                    stats["completed"] += 1
                queue.task_done()
                continue

        if not html or not parsed_quarters:
            async with lock:
                stats["missing"] += 1
                stats["completed"] += 1
            queue.task_done()
            continue

        latest_screener_p = max(q["period_end"] for q in parsed_quarters)
        now = datetime.now(UTC)

        is_new_quarter = (max_db_period is None) or (latest_screener_p > max_db_period)
        is_ancient_rescue = (max_db_period is not None) and (max_db_period < date(2026, 6, 30)) and (latest_screener_p >= date(2026, 6, 30))

        # Check structured JSON for newly reported shareholding
        parsed_json = parse_screener_html(html)
        has_sep_shareholding = False
        if "shareholding" in parsed_json:
            for k, val_dict in parsed_json["shareholding"].items():
                if isinstance(val_dict, dict) and "Sep 2026" in val_dict:
                    has_sep_shareholding = True
                    break

        needs_update = is_new_quarter or is_ancient_rescue or has_sep_shareholding

        if not needs_update:
            try:
                async with session_scope() as session:
                    await session.execute(
                        text("UPDATE raw_provider_scrapes SET scraped_at = :now WHERE instrument_id = :id AND provider = 'screener_in'"),
                        {"now": now, "id": inst_id},
                    )
            except Exception:
                pass
            async with lock:
                stats["unchanged"] += 1
                stats["completed"] += 1
                completed = stats["completed"]
                if completed % 50 == 0 or completed == total_candidates:
                    print(
                        f"[{completed}/{total_candidates}] Checked {symbol} (Unchanged: {max_db_period})",
                        flush=True,
                    )
            queue.task_done()
            continue

        # Ingest new data
        try:
            new_score_val = None
            async with session_scope() as session:
                # 1. Update raw scrape HTML (Bronze)
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

                # 2. Extract and update logo if available
                logo_match = re.search(r'https://cdn-media\.screener\.in/company-logos/[^"\'\s<>]+', html)
                inst = await session.get(Instrument, inst_id)
                if logo_match and inst:
                    inst.logo_url = logo_match.group(0)

                # 3. Update structured JSON (Silver)
                await session.execute(
                    delete(StructuredProviderData).where(
                        StructuredProviderData.instrument_id == inst_id,
                        StructuredProviderData.provider == "screener_in",
                    )
                )
                session.add(
                    StructuredProviderData(
                        instrument_id=inst_id,
                        provider="screener_in",
                        data=parsed_json,
                        parsed_at=now,
                        source_scrape_id=raw_scrape.id,
                    )
                )

                # 4. Upsert quarterly snapshots (Gold)
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
                        },
                    )
                    await session.execute(stmt_snap)

                # 5. Recompute Research Score
                if inst and (is_new_quarter or is_ancient_rescue):
                    try:
                        res = await compute_research_score(
                            session, inst, precomputed_universe_valuation=universe_val
                        )
                        new_score_val = res.score
                    except Exception as score_exc:
                        logger.warning(f"Score recomputation notice for {symbol}: {score_exc}")

                await session.commit()

            # Record update
            matching_q = next((q for q in parsed_quarters if q["period_end"] == latest_screener_p), {})
            rev_cr = float(matching_q.get("revenue") or 0) / 1e7
            pat_cr = float(matching_q.get("pat") or 0) / 1e7

            async with lock:
                stats["completed"] += 1
                completed = stats["completed"]
                if is_new_quarter:
                    stats["updated_earnings"].append({
                        "symbol": symbol,
                        "old": str(max_db_period),
                        "new": str(latest_screener_p),
                        "revenue_cr": round(rev_cr, 1),
                        "pat_cr": round(pat_cr, 1),
                        "score": round(new_score_val, 1) if new_score_val else None,
                        "url": url,
                    })
                    score_str = f" | New Score: {new_score_val:.1f}" if new_score_val else ""
                    print(
                        f"🌟 [Worker-{worker_id}] [{completed}/{total_candidates}] {symbol}: NEW Q2 FY27 EARNINGS! "
                        f"{max_db_period} -> {latest_screener_p} | Sales: ₹{rev_cr:,.1f} Cr | PAT: ₹{pat_cr:,.1f} Cr{score_str}",
                        flush=True,
                    )
                elif is_ancient_rescue:
                    stats["rescued"].append(symbol)
                    print(
                        f"🔄 [Worker-{worker_id}] [{completed}/{total_candidates}] {symbol}: Rescued Ancient Data -> {latest_screener_p}",
                        flush=True,
                    )
                elif has_sep_shareholding:
                    stats["updated_shareholding"].append(symbol)
                    print(
                        f"📊 [Worker-{worker_id}] [{completed}/{total_candidates}] {symbol}: Updated Sep 2026 Shareholding",
                        flush=True,
                    )

        except Exception as e:
            print(f"❌ [Worker-{worker_id}] Error saving {symbol}: {e}", flush=True)
            async with lock:
                stats["completed"] += 1

        queue.task_done()


async def main():
    parser = argparse.ArgumentParser(description="Parallel 5-Worker Screener.in Sync")
    parser.add_argument("--workers", type=int, default=5, help="Number of parallel workers (default: 5)")
    parser.add_argument("--limit", type=int, default=None, help="Optional limit for testing")
    parser.add_argument("--session-id", type=str, default=None, help="screener.in sessionid cookie")
    parser.add_argument("--csrf-token", type=str, default=None, help="screener.in csrftoken cookie")
    parser.add_argument("--include-recently-scraped", action="store_true", help="Do not skip recently scraped stocks")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    session_id = args.session_id or settings.SCREENER_SESSION_ID
    csrf_token = args.csrf_token or settings.SCREENER_CSRF_TOKEN

    cookies = {}
    if session_id:
        cookies["sessionid"] = session_id
    if csrf_token:
        cookies["csrftoken"] = csrf_token

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }

    print("\n=======================================================", flush=True)
    print("🚀 SignalForge High-Performance Screener.in Parallel Sync", flush=True)
    print(f"Workers: {args.workers} in parallel", flush=True)
    print(f"Authenticated Session: {'Active (valid cookies)' if session_id else 'None'}", flush=True)
    print("=======================================================\n", flush=True)

    # 1. Fetch live feed items from BSE & Screener results feed
    print("🔍 Fetching live earnings feeds from BSE and Screener...", flush=True)
    bse_items = fetch_bse_financial_results_feed()
    screener_items = fetch_screener_latest_results_feed()
    all_feed_items = bse_items + screener_items
    print(f"Found {len(bse_items)} BSE announcements and {len(screener_items)} Screener feed announcements.", flush=True)

    # 2. Query universe with latest quarterly period, last scrape timestamp, and turnover
    print("📊 Querying database instruments & fundamentals status...", flush=True)
    query = text("""
        WITH max_qtr AS (
            SELECT instrument_id, MAX(period_end) as max_period
            FROM fundamental_snapshots
            WHERE period_type = 'Q'
            GROUP BY instrument_id
        ),
        last_scrape AS (
            SELECT instrument_id, MAX(scraped_at) as last_scraped
            FROM raw_provider_scrapes
            WHERE provider = 'screener_in'
            GROUP BY instrument_id
        ),
        latest_turnover AS (
            SELECT DISTINCT ON (instrument_id) instrument_id, (close * volume) as turnover
            FROM ohlcv_daily
            ORDER BY instrument_id, trading_date DESC
        )
        SELECT i.id, i.symbol, i.company_name, i.exchange, m.max_period, ls.last_scraped, t.turnover
        FROM instruments i
        LEFT JOIN max_qtr m ON m.instrument_id = i.id
        LEFT JOIN last_scrape ls ON ls.instrument_id = i.id
        LEFT JOIN latest_turnover t ON t.instrument_id = i.id
        WHERE i.active = true AND i.instrument_type = 'EQUITY'
        ORDER BY t.turnover DESC NULLS LAST
    """)

    async with session_scope() as session:
        rows = (await session.execute(query)).all()

    # Build symbol & clean company name lookup
    inst_lookup: dict[str, str] = {}
    for r in rows:
        _, sym, cname, _, _, _, _ = r
        inst_lookup[sym.lower()] = sym.upper()
        clean = re.sub(r"\b(Ltd|Limited|LTD)\b\.?", "", cname).strip().lower()
        inst_lookup[clean] = sym.upper()

    feed_symbols: set[str] = set()
    for item in all_feed_items:
        code = item.bse_code.lower()
        if code in inst_lookup:
            feed_symbols.add(inst_lookup[code])
            continue
        k = item.clean_name.lower()
        if k in inst_lookup:
            feed_symbols.add(inst_lookup[k])
            continue
        for ik, iv in inst_lookup.items():
            if len(k) >= 6 and (k in ik or ik in k):
                feed_symbols.add(iv)
                break
    print(f"🎯 Matched {len(feed_symbols)} feed announcements to active equities.", flush=True)

    # 3. Filter candidates:
    # Always prioritize feed symbols in Priority 0
    # For others, ignore if already have 2026-09-30 (Q2 FY27) or verified within 6 hours
    candidates_priority_0 = []
    candidates_priority_1 = []
    ignored_count = 0

    for r in rows:
        inst_id, symbol, company_name, exchange, max_period, last_scraped, turnover = r
        sym_upper = symbol.upper()

        in_live_feed = sym_upper in feed_symbols
        already_has_sep_2026 = (max_period is not None) and (max_period >= date(2026, 9, 30))
        recently_scraped = (last_scraped is not None) and (last_scraped >= datetime.now(UTC) - timedelta(hours=6))

        if not args.include_recently_scraped and not in_live_feed:
            if already_has_sep_2026 or recently_scraped:
                ignored_count += 1
                continue

        item = (inst_id, symbol, company_name, exchange, max_period)
        if in_live_feed:
            candidates_priority_0.append(item)
        else:
            candidates_priority_1.append(item)

    all_candidates = candidates_priority_0 + candidates_priority_1
    if args.limit:
        all_candidates = all_candidates[:args.limit]

    total = len(all_candidates)
    print(f"Total Universe: {len(rows)} active stocks", flush=True)
    print(f"Ignored (Already Up-to-Date with Q2 FY27): {ignored_count} stocks", flush=True)
    print(f"Priority 0 (Live Results Feed): {len(candidates_priority_0)} stocks", flush=True)
    print(f"Priority 1 (Turnover Ordered): {len(candidates_priority_1)} stocks", flush=True)
    print(f"Candidates Queue to Sweep: {total} stocks", flush=True)

    if total == 0:
        print("✅ All stocks are already up-to-date! No sweep needed.", flush=True)
        return

    # 4. Precompute universe valuation percentiles once for scoring
    print("\n⚡ Precomputing universe valuation percentiles for scoring...", flush=True)
    async with session_scope() as session:
        universe_val = await compute_universe_valuation_values(session, datetime.now(UTC))
    print("✅ Precomputed universe valuation percentiles successfully.", flush=True)

    # 5. Populate Queue and Launch 5 Parallel Workers
    queue = asyncio.Queue()
    for item in all_candidates:
        queue.put_nowait(item)

    rate_limit_event = asyncio.Event()
    rate_limit_event.set()  # Initial state: active
    lock = asyncio.Lock()
    request_lock = asyncio.Lock()

    stats = {
        "completed": 0,
        "unchanged": 0,
        "missing": 0,
        "rate_limit_hits": 0,
        "updated_earnings": [],
        "rescued": [],
        "updated_shareholding": [],
    }

    print(f"\n🚀 Launching {args.workers} Parallel Workers now...\n", flush=True)
    start_time = datetime.now(UTC)

    async with httpx.AsyncClient(headers=headers, cookies=cookies, follow_redirects=True, timeout=25.0) as client:
        workers = [
            asyncio.create_task(
                worker(
                    worker_id=i + 1,
                    queue=queue,
                    client=client,
                    rate_limit_event=rate_limit_event,
                    request_lock=request_lock,
                    stats=stats,
                    universe_val=universe_val,
                    total_candidates=total,
                    lock=lock,
                )
            )
            for i in range(args.workers)
        ]

        await queue.join()

        # Cancel any idle worker tasks
        for w in workers:
            w.cancel()

    duration = (datetime.now(UTC) - start_time).total_seconds()

    # 6. Post-sweep sync of institutional holdings
    print("\n📊 Updating institutional holding dynamics (Smart Money Flow)...", flush=True)
    try:
        async with session_scope() as session:
            ih_count = await sync_all_institutional_holdings(session)
            print(f"✅ Synced {ih_count} institutional holding records.", flush=True)
    except Exception as e:
        print(f"Warning during institutional sync: {e}", flush=True)

    # 7. Invalidate Redis Caches
    print("\n🧹 Purging Redis caches for real-time frontend reflection...", flush=True)
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        patterns = [
            "instruments_listing:*",
            "instruments_search:*",
            "signalforge:stock_diagnostic:*",
            "stock_price:*",
            "breakout:*",
            "multibagger:*",
        ]
        purged = 0
        for pat in patterns:
            keys = await r.keys(pat)
            if keys:
                await r.delete(*keys)
                purged += len(keys)
        await r.aclose()
        print(f"✅ Purged {purged} cached keys from Redis.", flush=True)
    except Exception as e:
        print(f"Warning purging Redis: {e}", flush=True)

    # 8. Summary Report
    updated = stats["updated_earnings"]
    print("\n" + "=" * 60, flush=True)
    print("🎉 Screener.in Parallel Sweep Finished!", flush=True)
    print(f"Duration: {duration:.1f}s ({duration / 60:.2f} mins)", flush=True)
    print(f"Total Scanned: {stats['completed']}", flush=True)
    print(f"Newly Reported Q2 FY27 (Sep 2026) Results: {len(updated)} stocks", flush=True)
    print(f"Rescued Ancient Stocks (< Jun 2026): {len(stats['rescued'])} stocks", flush=True)
    print(f"Updated Sep 2026 Shareholding: {len(stats['updated_shareholding'])} stocks", flush=True)
    print(f"Unchanged on Screener: {stats['unchanged']}", flush=True)
    print(f"429 Rate Limit Hits (Recovered): {stats['rate_limit_hits']}", flush=True)
    print("=" * 60 + "\n", flush=True)

    if updated:
        print("📈 Newly Ingested Q2 FY27 Earnings:", flush=True)
        for u in updated:
            sc = f" | Research Score: {u['score']}" if u['score'] else ""
            print(
                f"  • {u['symbol']:12} | {u['new']} | Revenue: ₹{u['revenue_cr']:>10,.1f} Cr | PAT: ₹{u['pat_cr']:>8,.1f} Cr{sc}",
                flush=True,
            )

    report_path = "/tmp/screener_parallel_sweep_summary.json"
    with open(report_path, "w") as f:
        json.dump({
            "completed_at": datetime.now(UTC).isoformat(),
            "duration_seconds": duration,
            "total_scanned": stats["completed"],
            "newly_reported_earnings": updated,
            "rescued_count": len(stats["rescued"]),
            "updated_shareholding_count": len(stats["updated_shareholding"]),
            "unchanged_count": stats["unchanged"],
            "rate_limit_hits": stats["rate_limit_hits"],
        }, f, indent=2)
    print(f"\nDetailed report saved to {report_path}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
