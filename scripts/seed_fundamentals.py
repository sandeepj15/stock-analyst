#!/usr/bin/env python
"""Backfill fundamentals snapshots for every currently-seeded instrument.

Usage:
    python scripts/seed_fundamentals.py                     # via `make seed-fundamentals` inside the api container
    python scripts/seed_fundamentals.py --concurrency 10    # tune bounded-concurrency fan-out (default 6)
    FUNDAMENTAL_PROVIDER=yfinance_tradingview_fallback python scripts/seed_fundamentals.py
                                                              # use the tradingview-ta fallback (see DATA_SOURCES.md)
    python scripts/seed_fundamentals.py --quarterly          # backfill period_type="Q" instead of FY/TTM
                                                              # (YFinanceQuarterlyFundamentalProvider - see
                                                              # packages/fundamentals/providers/yfinance_fundamental_provider.py
                                                              # for its coverage caveat)

Idempotent: `sync_fundamentals` upserts on `(instrument_id, period_end,
period_type, source)` (SPEC.md section 57), so re-running this script is
safe.

SPEC.md section 59 (rate limits): both yfinance and tradingview-ta are
unofficial, free, no-API-key endpoints that can throttle/block bursty
sequential traffic at hundreds-of-symbols scale. This script therefore
runs with **bounded concurrency** (a handful of concurrent in-flight
requests, not hundreds, not fully sequential) via
`packages.common.rate_limit`, each request staggered by a small
randomized delay, with retry-with-backoff on transient failures. Each
concurrent task uses its own DB session (`session_scope()` per task) -
`sync_fundamentals`'s idempotent upsert makes concurrent writes safe
either way, but per-task sessions avoid any shared-session state issue
entirely.

Per-symbol try/except-and-continue, same pattern as
`scripts/seed_dev_data.py`: a single symbol's provider failure (network
hiccup, or - expected and NOT a bug - zero fundamentals coverage from
every configured provider for that NSE ticker) never aborts the rest of
the run.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.logging import configure_logging
from packages.common.models import Instrument
from packages.common.rate_limit import ProviderHealth, RetryPolicy
from packages.fundamentals.factory import get_fundamental_provider, get_quarterly_fundamental_provider
from packages.fundamentals.ingestion import sync_fundamentals
from packages.fundamentals.models import FundamentalSnapshot

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 6

# Hard wall-clock cap per instrument, regardless of which layer misbehaves
# (provider HTTP call, DB, thread pool). Discovered necessary live: a
# quarterly backfill run hung for 51 minutes on one instrument - screener.in
# logged a "200 OK" status line but the connection then stalled reading the
# body without httpx's own timeout ever firing, holding a DB session "idle
# in transaction" the whole time and blocking every instrument queued
# behind it (concurrency=1 at the time, but this protects any concurrency).
# Generous enough for legitimate slow pages/retries, far below "an hour".
PER_INSTRUMENT_TIMEOUT_SECONDS = 60


@dataclass
class FundamentalsSummary:
    succeeded: int = 0
    failed: int = 0
    no_coverage: int = 0
    total_snapshots: int = 0
    fallback_filled: int = 0  # instruments where >=1 field came from a non-primary provider
    failures: list[tuple[str, str]] = field(default_factory=list)


async def _sync_one(
    symbol: str,
    exchange: str,
    provider,
    retry_policy: RetryPolicy,
    health: ProviderHealth,
    summary: FundamentalsSummary,
    timeout_seconds: float = PER_INSTRUMENT_TIMEOUT_SECONDS,
) -> None:
    await asyncio.sleep(random.uniform(0.1, 0.3))

    attempt = 0
    last_exc: Exception | None = None
    while attempt < retry_policy.max_attempts:
        attempt += 1
        try:

            async def _do_sync() -> tuple[object, object]:
                async with session_scope() as session:
                    refreshed = (
                        await session.execute(
                            select(Instrument).where(Instrument.symbol == symbol, Instrument.exchange == exchange)
                        )
                    ).scalar_one()
                    sync_result = await sync_fundamentals(provider, session, refreshed)

                    # Inspect what actually got persisted so the run summary can
                    # honestly report how many instruments were only covered
                    # because of the fallback provider (SPEC.md section 2.1 -
                    # evidence/provenance must stay inspectable, including in
                    # this script's own reporting).
                    latest_row = (
                        await session.execute(
                            select(FundamentalSnapshot)
                            .where(FundamentalSnapshot.instrument_id == refreshed.id)
                            .order_by(FundamentalSnapshot.period_end.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    return sync_result, latest_row

            result, latest = await asyncio.wait_for(_do_sync(), timeout=timeout_seconds)

            if result.rows_processed == 0:
                summary.no_coverage += 1
            else:
                summary.total_snapshots += result.rows_processed
                if latest is not None and latest.field_sources:
                    non_primary = {
                        field_name: src for field_name, src in latest.field_sources.items() if src != latest.source
                    }
                    if non_primary:
                        summary.fallback_filled += 1

            logger.info(
                "seed_fundamentals: backfilled instrument",
                extra={"symbol": symbol, "rows_processed": result.rows_processed, "attempt": attempt},
            )
            health.record_success()
            summary.succeeded += 1
            return
        except Exception as exc:
            # Bare `TimeoutError` (asyncio.wait_for's) has no message of its
            # own - name it explicitly so the log doesn't just say "error: ".
            error_text = f"timed out after {timeout_seconds}s" if isinstance(exc, TimeoutError) else str(exc)
            last_exc = exc
            health.record_failure()
            if attempt >= retry_policy.max_attempts:
                break
            delay = retry_policy.delay_for_attempt(attempt)
            logger.warning(
                "seed_fundamentals: transient failure, retrying",
                extra={"symbol": symbol, "attempt": attempt, "error": error_text},
            )
            await asyncio.sleep(delay)

    final_error = f"timed out after {timeout_seconds}s" if isinstance(last_exc, TimeoutError) else str(last_exc)
    logger.error(
        "seed_fundamentals: failed to sync instrument after retries, continuing with next",
        extra={"symbol": symbol, "error": final_error},
    )
    summary.failed += 1
    summary.failures.append((symbol, final_error))


async def main(concurrency: int, quarterly: bool) -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    provider = get_quarterly_fundamental_provider(settings) if quarterly else get_fundamental_provider(settings)
    retry_policy = RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=10.0)
    health = ProviderHealth(name="fundamentals", failure_threshold=50)

    async with session_scope() as session:
        stmt = select(Instrument.symbol, Instrument.exchange).where(
            Instrument.active.is_(True), Instrument.instrument_type == "EQUITY"
        )
        instrument_refs = [(row.symbol, row.exchange) for row in (await session.execute(stmt)).all()]

    summary = FundamentalsSummary()
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_one(symbol: str, exchange: str) -> None:
        async with semaphore:
            await _sync_one(symbol, exchange, provider, retry_policy, health, summary)

    started_at = time.monotonic()
    await asyncio.gather(*(_run_one(symbol, exchange) for symbol, exchange in instrument_refs))
    elapsed = time.monotonic() - started_at

    logger.info(
        "seed_fundamentals: done",
        extra={
            "succeeded": summary.succeeded,
            "failed": summary.failed,
            "no_coverage": summary.no_coverage,
            "total_snapshots": summary.total_snapshots,
            "fallback_filled": summary.fallback_filled,
            "elapsed_seconds": round(elapsed, 1),
        },
    )
    print(
        f"Fundamentals seed complete ({len(instrument_refs)} instruments, concurrency={concurrency}, "
        f"elapsed={elapsed:.1f}s). {summary.succeeded} synced OK "
        f"({summary.no_coverage} had zero coverage from every configured provider - expected for many NSE "
        f"tickers, {summary.fallback_filled} gained >=1 field purely from the fallback provider), "
        f"{summary.failed} failed, {summary.total_snapshots} total snapshot rows processed."
    )
    if summary.failures:
        print("Failed symbols:")
        for symbol, error in summary.failures:
            print(f"  {symbol}: {error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--concurrency", type=int, default=DEFAULT_CONCURRENCY, help=f"Max concurrent in-flight provider requests (default: {DEFAULT_CONCURRENCY})"
    )
    parser.add_argument(
        "--quarterly", action="store_true", help='Backfill period_type="Q" snapshots instead of FY/TTM'
    )
    args = parser.parse_args()
    asyncio.run(main(args.concurrency, args.quarterly))
