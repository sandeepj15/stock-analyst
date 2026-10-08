#!/usr/bin/env python
"""Seed the NSE equity universe (legacy ~117 curated + ~750 Nifty Total Market) + ~2 years of daily bars.

Usage:
    python scripts/seed_dev_data.py                    # via `make seed` inside the api container
    python scripts/seed_dev_data.py --days 90           # shorter backfill for a quick smoke test
    python scripts/seed_dev_data.py --skip-universe     # legacy ~117-symbol behavior only
    python scripts/seed_dev_data.py --concurrency 10    # tune bounded-concurrency fan-out (default 6)

Idempotent: re-running this script is safe. Instrument rows are inserted
only if they don't already exist (matched on exchange+symbol); OHLCV
backfill goes through `ingest_daily_bars`, which is itself idempotent
(SPEC.md section 57).

Seeding order (SPEC.md section 11 corporate-action handling):
1. `apply_known_symbol_renames` - repoints any pre-existing TATAMOTORS/
   LTIM/ZOMATO rows to their current live ticker in place (preserving
   history) and ensures the old symbol resolves via `instrument_aliases`.
   See `packages/market_data/corporate_actions.py` for the verified
   root-cause evidence.
2. `ensure_instruments` - the original hand-curated ~117-symbol list
   (now using each entry's *current* ticker).
3. `ensure_universe_instruments` - fetches NSE's own ~750-symbol Nifty
   Total Market constituent list (`packages/market_data/universe.py`)
   and adds any instrument not already present (matched on
   exchange+symbol, so none of the ~117 above are duplicated under a
   different source).

OHLCV backfill then runs for every active EQUITY instrument, not just
the ones just-created, so re-running this script also catches up any
previously-failed symbol.

SPEC.md section 59 (rate limits): yfinance is an unofficial, free,
no-API-key wrapper around Yahoo Finance and can throttle/block bursty
sequential traffic at hundreds-of-symbols scale. Backfill therefore runs
with **bounded concurrency** (a handful of concurrent in-flight
requests, not hundreds, not fully sequential either) via
`packages.common.rate_limit`, each request further staggered by a small
randomized delay, with retry-with-backoff on transient provider errors.
The existing per-symbol try/except-and-continue pattern is preserved -
one bad/slow symbol can never abort the run - and each concurrent task
uses its own DB session (session_scope() per task), never a shared
session across concurrent coroutines.

If a symbol fails (network hiccup, provider error, delisting, etc.)
this script logs it, records a failed `data_ingestion_runs` row (via
`ingest_daily_bars` itself), and continues with the next symbol.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select

from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.logging import configure_logging
from packages.common.models import Instrument
from packages.common.rate_limit import ProviderHealth, RetryPolicy
from packages.market_data.corporate_actions import apply_known_symbol_renames
from packages.market_data.factory import get_provider
from packages.market_data.ingestion import ingest_daily_bars
from packages.market_data.universe import fetch_nse_universe

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 6

# (symbol, company_name, sector) - a reasonable sector guess for seed/demo purposes only.
SEED_INSTRUMENTS: list[tuple[str, str, str]] = [
    ("RELIANCE", "Reliance Industries Ltd", "Energy"),
    ("TCS", "Tata Consultancy Services Ltd", "Information Technology"),
    ("HDFCBANK", "HDFC Bank Ltd", "Financial Services"),
    ("INFY", "Infosys Ltd", "Information Technology"),
    ("ICICIBANK", "ICICI Bank Ltd", "Financial Services"),
    ("HINDUNILVR", "Hindustan Unilever Ltd", "Consumer Goods"),
    ("SBIN", "State Bank of India", "Financial Services"),
    ("BHARTIARTL", "Bharti Airtel Ltd", "Telecommunications"),
    ("ITC", "ITC Ltd", "Consumer Goods"),
    ("KOTAKBANK", "Kotak Mahindra Bank Ltd", "Financial Services"),
    ("LT", "Larsen & Toubro Ltd", "Infrastructure"),
    ("AXISBANK", "Axis Bank Ltd", "Financial Services"),
    ("ASIANPAINT", "Asian Paints Ltd", "Consumer Goods"),
    ("MARUTI", "Maruti Suzuki India Ltd", "Automobile"),
    ("SUNPHARMA", "Sun Pharmaceutical Industries Ltd", "Healthcare"),
    ("TITAN", "Titan Company Ltd", "Consumer Goods"),
    ("BAJFINANCE", "Bajaj Finance Ltd", "Financial Services"),
    ("WIPRO", "Wipro Ltd", "Information Technology"),
    ("ULTRACEMCO", "UltraTech Cement Ltd", "Materials"),
    ("NESTLEIND", "Nestle India Ltd", "Consumer Goods"),
    ("HCLTECH", "HCL Technologies Ltd", "Information Technology"),
    ("BAJAJFINSV", "Bajaj Finserv Ltd", "Financial Services"),
    ("ADANIENT", "Adani Enterprises Ltd", "Diversified"),
    ("ADANIPORTS", "Adani Ports and Special Economic Zone Ltd", "Infrastructure"),
    ("ONGC", "Oil & Natural Gas Corporation Ltd", "Energy"),
    ("NTPC", "NTPC Ltd", "Power"),
    ("POWERGRID", "Power Grid Corporation of India Ltd", "Power"),
    ("M&M", "Mahindra & Mahindra Ltd", "Automobile"),
    # Renamed/re-ticker'd as part of the 2026 Tata Motors demerger - the
    # original listing/history now trades as TMPV, not TATAMOTORS (see
    # packages/market_data/corporate_actions.py for the verified
    # root-cause/evidence). `apply_known_symbol_renames` also repoints any
    # pre-existing TATAMOTORS row in an older-seeded DB and keeps TATAMOTORS
    # searchable via instrument_aliases.
    ("TMPV", "Tata Motors Passenger Vehicles Ltd", "Automobile"),
    ("TATASTEEL", "Tata Steel Ltd", "Materials"),
    ("JSWSTEEL", "JSW Steel Ltd", "Materials"),
    ("HINDALCO", "Hindalco Industries Ltd", "Materials"),
    ("COALINDIA", "Coal India Ltd", "Energy"),
    ("INDUSINDBK", "IndusInd Bank Ltd", "Financial Services"),
    ("GRASIM", "Grasim Industries Ltd", "Diversified"),
    ("DRREDDY", "Dr. Reddy's Laboratories Ltd", "Healthcare"),
    ("CIPLA", "Cipla Ltd", "Healthcare"),
    ("DIVISLAB", "Divi's Laboratories Ltd", "Healthcare"),
    ("APOLLOHOSP", "Apollo Hospitals Enterprise Ltd", "Healthcare"),
    ("EICHERMOT", "Eicher Motors Ltd", "Automobile"),
    ("HEROMOTOCO", "Hero MotoCorp Ltd", "Automobile"),
    ("BAJAJ-AUTO", "Bajaj Auto Ltd", "Automobile"),
    ("TECHM", "Tech Mahindra Ltd", "Information Technology"),
    # Renamed from LTIM -> LTM (see packages/market_data/corporate_actions.py).
    ("LTM", "LTM Ltd", "Information Technology"),
    ("SBILIFE", "SBI Life Insurance Company Ltd", "Financial Services"),
    ("HDFCLIFE", "HDFC Life Insurance Company Ltd", "Financial Services"),
    ("ICICIPRULI", "ICICI Prudential Life Insurance Company Ltd", "Financial Services"),
    ("ICICIGI", "ICICI Lombard General Insurance Company Ltd", "Financial Services"),
    ("BRITANNIA", "Britannia Industries Ltd", "Consumer Goods"),
    ("DABUR", "Dabur India Ltd", "Consumer Goods"),
    ("GODREJCP", "Godrej Consumer Products Ltd", "Consumer Goods"),
    ("PIDILITIND", "Pidilite Industries Ltd", "Materials"),
    ("HAVELLS", "Havells India Ltd", "Consumer Durables"),
    ("SIEMENS", "Siemens Ltd", "Capital Goods"),
    ("ABB", "ABB India Ltd", "Capital Goods"),
    ("BEL", "Bharat Electronics Ltd", "Defence"),
    ("BPCL", "Bharat Petroleum Corporation Ltd", "Energy"),
    ("IOC", "Indian Oil Corporation Ltd", "Energy"),
    ("GAIL", "GAIL (India) Ltd", "Energy"),
    ("VEDL", "Vedanta Ltd", "Materials"),
    ("SHREECEM", "Shree Cement Ltd", "Materials"),
    ("AMBUJACEM", "Ambuja Cements Ltd", "Materials"),
    ("ACC", "ACC Ltd", "Materials"),
    ("DLF", "DLF Ltd", "Realty"),
    ("GODREJPROP", "Godrej Properties Ltd", "Realty"),
    ("PNB", "Punjab National Bank", "Financial Services"),
    ("BANKBARODA", "Bank of Baroda", "Financial Services"),
    ("CANBK", "Canara Bank", "Financial Services"),
    ("IDFCFIRSTB", "IDFC First Bank Ltd", "Financial Services"),
    ("FEDERALBNK", "Federal Bank Ltd", "Financial Services"),
    ("AUBANK", "AU Small Finance Bank Ltd", "Financial Services"),
    ("BANDHANBNK", "Bandhan Bank Ltd", "Financial Services"),
    ("CHOLAFIN", "Cholamandalam Investment and Finance Company Ltd", "Financial Services"),
    ("MUTHOOTFIN", "Muthoot Finance Ltd", "Financial Services"),
    ("PFC", "Power Finance Corporation Ltd", "Financial Services"),
    ("RECLTD", "REC Ltd", "Financial Services"),
    ("LICI", "Life Insurance Corporation of India", "Financial Services"),
    ("INDIGO", "InterGlobe Aviation Ltd", "Aviation"),
    ("IRCTC", "Indian Railway Catering and Tourism Corporation Ltd", "Travel"),
    # Renamed from ZOMATO -> ETERNAL in 2024 (see packages/market_data/corporate_actions.py).
    ("ETERNAL", "Eternal Ltd", "Consumer Services"),
    ("NAUKRI", "Info Edge (India) Ltd", "Information Technology"),
    ("TRENT", "Trent Ltd", "Consumer Services"),
    ("DMART", "Avenue Supermarts Ltd", "Consumer Services"),
    ("PAGEIND", "Page Industries Ltd", "Textiles"),
    ("BERGEPAINT", "Berger Paints India Ltd", "Consumer Goods"),
    ("COLPAL", "Colgate-Palmolive (India) Ltd", "Consumer Goods"),
    ("MARICO", "Marico Ltd", "Consumer Goods"),
    ("TATACONSUM", "Tata Consumer Products Ltd", "Consumer Goods"),
    ("UPL", "UPL Ltd", "Materials"),
    ("SRF", "SRF Ltd", "Materials"),
    ("PIIND", "PI Industries Ltd", "Materials"),
    ("TATAPOWER", "Tata Power Company Ltd", "Power"),
    ("ADANIGREEN", "Adani Green Energy Ltd", "Power"),
    ("ADANIPOWER", "Adani Power Ltd", "Power"),
    ("SAIL", "Steel Authority of India Ltd", "Materials"),
    ("NMDC", "NMDC Ltd", "Materials"),
    ("JINDALSTEL", "Jindal Steel & Power Ltd", "Materials"),
    ("MOTHERSON", "Samvardhana Motherson International Ltd", "Automobile"),
    ("BOSCHLTD", "Bosch Ltd", "Automobile"),
    ("HINDPETRO", "Hindustan Petroleum Corporation Ltd", "Energy"),
    ("SHRIRAMFIN", "Shriram Finance Ltd", "Financial Services"),
    ("TVSMOTOR", "TVS Motor Company Ltd", "Automobile"),
    ("ASHOKLEY", "Ashok Leyland Ltd", "Automobile"),
    ("POLYCAB", "Polycab India Ltd", "Consumer Durables"),
    ("LUPIN", "Lupin Ltd", "Healthcare"),
    ("AUROPHARMA", "Aurobindo Pharma Ltd", "Healthcare"),
    ("TORNTPHARM", "Torrent Pharmaceuticals Ltd", "Healthcare"),
    ("MFSL", "Max Financial Services Ltd", "Financial Services"),
    ("INDHOTEL", "The Indian Hotels Company Ltd", "Consumer Services"),
    ("UNITDSPR", "United Spirits Ltd", "Consumer Goods"),
    ("YESBANK", "Yes Bank Ltd", "Financial Services"),
    ("IDEA", "Vodafone Idea Ltd", "Telecommunications"),
    ("GMRAIRPORT", "GMR Airports Ltd", "Infrastructure"),
    ("OFSS", "Oracle Financial Services Software Ltd", "Information Technology"),
    ("PERSISTENT", "Persistent Systems Ltd", "Information Technology"),
    ("COFORGE", "Coforge Ltd", "Information Technology"),
    ("MPHASIS", "Mphasis Ltd", "Information Technology"),
]

EXCHANGE = "NSE"


async def ensure_instruments(session) -> list[Instrument]:
    instruments: list[Instrument] = []
    for symbol, company_name, sector in SEED_INSTRUMENTS:
        existing = (
            await session.execute(select(Instrument).where(Instrument.symbol == symbol, Instrument.exchange == EXCHANGE))
        ).scalar_one_or_none()
        if existing is not None:
            instruments.append(existing)
            continue

        instrument = Instrument(
            symbol=symbol,
            exchange=EXCHANGE,
            company_name=company_name,
            sector=sector,
            instrument_type="EQUITY",
            currency="INR",
        )
        session.add(instrument)
        instruments.append(instrument)

    await session.commit()
    logger.info("seed: instruments ready", extra={"count": len(instruments)})
    return instruments


async def ensure_universe_instruments(session) -> dict[str, int]:
    """Fetch NSE's ~750-symbol Nifty Total Market universe and add any new instrument.

    Matches on (exchange, symbol) exactly like `ensure_instruments` - any
    symbol already present (the legacy ~117, or anything a previous run
    of this function already added) is left untouched, so this never
    creates a duplicate-but-differently-sourced row for an instrument
    that already exists. Returns counts, not instruments, since the
    universe is large enough that the caller should re-query active
    instruments from the DB rather than hold ~750 ORM objects in memory
    across the whole script run.
    """
    try:
        universe = fetch_nse_universe()
    except Exception as exc:
        logger.error("seed: NSE universe fetch failed entirely, skipping universe seeding", extra={"error": str(exc)})
        print(f"WARNING: could not fetch the NSE universe list ({exc}); continuing with the legacy seed list only.")
        return {"fetched": 0, "newly_created": 0, "already_present": 0}

    existing_symbols = set(
        (await session.execute(select(Instrument.symbol).where(Instrument.exchange == EXCHANGE))).scalars().all()
    )

    created = 0
    for entry in universe:
        if entry.symbol in existing_symbols:
            continue
        session.add(
            Instrument(
                symbol=entry.symbol,
                exchange=EXCHANGE,
                company_name=entry.company_name,
                industry=entry.industry,
                isin=entry.isin,
                instrument_type="EQUITY",
                currency="INR",
            )
        )
        existing_symbols.add(entry.symbol)
        created += 1

    await session.commit()
    summary = {"fetched": len(universe), "newly_created": created, "already_present": len(universe) - created}
    logger.info("seed: universe instruments ready", extra=summary)
    return summary


@dataclass
class BackfillSummary:
    succeeded: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)  # (symbol, error)


async def _backfill_one(
    symbol: str,
    exchange: str,
    start: date,
    end: date,
    provider,
    retry_policy: RetryPolicy,
    health: ProviderHealth,
    summary: BackfillSummary,
) -> None:
    """Backfill one instrument's OHLCV, with jitter + retry-with-backoff, in its own DB session.

    Each concurrent task gets its own `session_scope()` - never a shared
    SQLAlchemy session across concurrent coroutines (SPEC.md section 59 /
    this task's concurrency addendum). The idempotent upsert in
    `ingest_daily_bars` already makes individual writes safe even if two
    tasks happened to touch overlapping rows, but giving each task its
    own session/connection avoids any shared-session state issues
    entirely, matching how `apps/worker/jobs.py::compute_all_scores_job`
    already isolates per-instrument work.
    """
    # NOTE: an `await asyncio.sleep` (not the blocking `sleep_with_jitter`
    # helper) - this runs inside a concurrently-gathered coroutine, and a
    # blocking `time.sleep` here would stall the whole event loop (and
    # therefore every other "concurrent" task) for its duration.
    await asyncio.sleep(random.uniform(0.1, 0.3))

    attempt = 0
    last_exc: Exception | None = None
    while attempt < retry_policy.max_attempts:
        attempt += 1
        try:
            async with session_scope() as session:
                refreshed = (
                    await session.execute(select(Instrument).where(Instrument.symbol == symbol, Instrument.exchange == exchange))
                ).scalar_one()
                result = await ingest_daily_bars(provider, session, refreshed, start, end)
            logger.info(
                "seed: backfilled instrument",
                extra={"symbol": symbol, "status": result.status.value, "rows_inserted": result.rows_inserted, "attempt": attempt},
            )
            health.record_success()
            summary.succeeded += 1
            return
        except Exception as exc:
            last_exc = exc
            health.record_failure()
            if attempt >= retry_policy.max_attempts:
                break
            delay = retry_policy.delay_for_attempt(attempt)
            logger.warning(
                "seed: transient backfill failure, retrying",
                extra={"symbol": symbol, "attempt": attempt, "error": str(exc)},
            )
            await asyncio.sleep(delay)

    logger.error(
        "seed: failed to backfill instrument after retries, continuing with next",
        extra={"symbol": symbol, "error": str(last_exc)},
    )
    summary.failed += 1
    summary.failures.append((symbol, str(last_exc)))


async def backfill_bars(instrument_refs: list[tuple[str, str]], days: int, concurrency: int) -> BackfillSummary:
    """Backfill OHLCV for every `(symbol, exchange)` pair, with bounded concurrency.

    SPEC.md section 59: capped concurrency (`concurrency`, default
    `DEFAULT_CONCURRENCY` = 6) rather than either fully sequential or
    unbounded fan-out - a handful of in-flight yfinance requests at a
    time, each additionally staggered by a small random delay
    (`sleep_with_jitter`) and retried with exponential backoff on
    transient failure. One symbol's permanent failure never aborts the
    batch - it's recorded in `BackfillSummary.failures` and the run
    continues.
    """
    settings = get_settings()
    provider = get_provider(settings)
    end = date.today()
    start = end - timedelta(days=days)
    retry_policy = RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=10.0)
    health = ProviderHealth(name="yfinance_dev", failure_threshold=50)

    summary = BackfillSummary()
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_one(symbol: str, exchange: str) -> None:
        async with semaphore:
            await _backfill_one(symbol, exchange, start, end, provider, retry_policy, health, summary)

    started_at = time.monotonic()
    await asyncio.gather(*(_run_one(symbol, exchange) for symbol, exchange in instrument_refs))
    elapsed = time.monotonic() - started_at

    logger.info(
        "seed: backfill batch complete",
        extra={
            "succeeded": summary.succeeded,
            "failed": summary.failed,
            "elapsed_seconds": round(elapsed, 1),
            "concurrency": concurrency,
            "provider_consecutive_failures": health.consecutive_failures,
        },
    )
    return summary


async def main(days: int, skip_universe: bool, concurrency: int) -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    async with session_scope() as session:
        rename_outcomes = await apply_known_symbol_renames(session)
        for outcome in rename_outcomes:
            logger.info(
                "seed: corporate-action symbol rename check",
                extra={"old_symbol": outcome.old_symbol, "new_symbol": outcome.new_symbol, "applied": outcome.applied, "reason": outcome.reason},
            )

    async with session_scope() as session:
        await ensure_instruments(session)

    universe_summary = {"fetched": 0, "newly_created": 0, "already_present": 0}
    if not skip_universe:
        async with session_scope() as session:
            universe_summary = await ensure_universe_instruments(session)

    async with session_scope() as session:
        stmt = select(Instrument.symbol, Instrument.exchange).where(
            Instrument.active.is_(True), Instrument.instrument_type == "EQUITY"
        )
        instrument_refs = [(row.symbol, row.exchange) for row in (await session.execute(stmt)).all()]

    print(
        f"Universe ready: {len(instrument_refs)} active EQUITY instruments "
        f"(NSE universe fetch: {universe_summary['fetched']} fetched, {universe_summary['newly_created']} newly created)."
    )

    summary = await backfill_bars(instrument_refs, days, concurrency)
    logger.info("seed: done", extra={"succeeded": summary.succeeded, "failed": summary.failed})
    print(
        f"Seed complete. Backfilled {summary.succeeded} instruments, {summary.failed} failed "
        f"out of {len(instrument_refs)} total."
    )
    if summary.failures:
        print("Failed symbols:")
        for symbol, error in summary.failures:
            print(f"  {symbol}: {error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=730, help="Number of calendar days to backfill (default: ~2 years)")
    parser.add_argument(
        "--skip-universe", action="store_true", help="Skip fetching the ~750-symbol NSE universe; seed only the legacy ~117 list"
    )
    parser.add_argument(
        "--concurrency", type=int, default=DEFAULT_CONCURRENCY, help=f"Max concurrent in-flight provider requests (default: {DEFAULT_CONCURRENCY})"
    )
    args = parser.parse_args()
    asyncio.run(main(args.days, args.skip_universe, args.concurrency))
