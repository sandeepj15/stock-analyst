"""Daily OHLCV ingestion service (SPEC.md sections 56-58).

`ingest_daily_bars` is the single entry point used by both the Arq worker
job (`apps/worker/jobs.py`) and the seed script. It is intentionally
idempotent: running it twice with identical provider output must not
create duplicate rows and must leave `ohlcv_daily` in the same end state
(see `tests/unit/test_ingestion_idempotency.py`).

Flow per SPEC.md section 102 (collect -> validate -> normalize ->
analytics...): this module covers collect + validate + normalize (upsert).
It never fabricates missing data - the data quality layer only reports
issues, and ingestion persists exactly what the provider returned.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.db import session_scope
from packages.common.models import Instrument
from packages.common.rate_limit import ProviderHealth, RetryPolicy
from packages.market_data.base import DailyBar, MarketDataProvider
from packages.market_data.models import (
    DataIngestionRun,
    DataQualityEvent,
    IngestionStatus,
    OHLCVDaily,
    QualitySeverity,
)
from packages.market_data.quality import run_all_quality_checks

logger = logging.getLogger(__name__)

JOB_NAME = "market_data_sync"

UPSERT_COLUMNS = ("open", "high", "low", "close", "volume", "adjusted_close", "source_timestamp")

# Shared default for every bounded-concurrency batch caller below
# (`apps/worker/jobs.py::sync_daily_bars`) - matches
# `scripts/seed_dev_data.py::DEFAULT_CONCURRENCY`, the value already
# proven safe against yfinance at the ~750-symbol scale (SPEC.md section
# 59: a handful of concurrent in-flight requests, never hundreds, never
# fully sequential either).
DEFAULT_INGESTION_CONCURRENCY = 6


class IngestionResult(BaseModel):
    """Outcome of a single `ingest_daily_bars` call."""

    ingestion_run_id: str
    status: IngestionStatus
    rows_processed: int
    rows_inserted: int
    rows_updated: int
    quality_issue_count: int
    error_message: str | None = None


async def ingest_daily_bars(
    provider: MarketDataProvider,
    session: AsyncSession,
    instrument: Instrument,
    start: date,
    end: date,
) -> IngestionResult:
    """Fetch, validate, and idempotently upsert daily bars for one instrument.

    Always records a `data_ingestion_runs` row and any `data_quality_events`
    rows, then commits. Raises on provider failure after recording the
    failure (callers - e.g. the seed script - must still catch and continue
    with the next instrument, per SPEC.md section 58: never silently use
    stale data as if fresh).
    """
    run = DataIngestionRun(job_name=JOB_NAME, instrument_id=instrument.id, status=IngestionStatus.running)
    session.add(run)
    await session.flush()

    try:
        # `provider.get_daily_bars` is a blocking/sync call (yfinance does
        # its own network I/O under the hood, no asyncio support). Running
        # it via `asyncio.to_thread` - rather than calling it directly -
        # is what makes it safe/useful to run many instruments' ingestion
        # concurrently via `asyncio.gather` (SPEC.md section 59): each
        # concurrent call actually overlaps its network wait in its own
        # worker thread instead of blocking the single event-loop thread
        # for every other in-flight instrument.
        bars = await asyncio.to_thread(provider.get_daily_bars, instrument.symbol, instrument.exchange, start, end)
    except Exception as exc:
        run.status = IngestionStatus.failed
        run.error_message = str(exc)
        run.finished_at = datetime.now(UTC)
        await session.commit()
        logger.error(
            "market_data_sync failed",
            extra={"job": JOB_NAME, "symbol": instrument.symbol, "exchange": instrument.exchange, "error": str(exc)},
        )
        raise

    bar_dicts = [b.model_dump() for b in bars]
    issues = run_all_quality_checks(bar_dicts, start, end)
    for issue in issues:
        session.add(
            DataQualityEvent(
                instrument_id=instrument.id,
                ingestion_run_id=run.id,
                event_type=issue.event_type,
                severity=issue.severity,
                message=issue.message,
                details=issue.details,
            )
        )

    # Deduplicate on the natural key, keeping the last occurrence. Real
    # duplicates are still reported above via detect_duplicates(); this
    # just prevents "ON CONFLICT DO UPDATE command cannot affect row a
    # second time" if a provider ever returns the same (date, source) twice
    # in one response.
    deduped: dict[tuple[date, str], DailyBar] = {}
    for bar in bars:
        deduped[(bar.trading_date, bar.source)] = bar
    rows = list(deduped.values())

    rows_inserted = 0
    rows_updated = 0

    if rows:
        keys = [(bar.trading_date, bar.source) for bar in rows]
        existing_result = await session.execute(
            select(OHLCVDaily.trading_date, OHLCVDaily.source).where(
                OHLCVDaily.instrument_id == instrument.id,
                OHLCVDaily.trading_date.in_({k[0] for k in keys}),
            )
        )
        existing_keys = {(row.trading_date, row.source) for row in existing_result.all()}

        values = [
            {
                "instrument_id": instrument.id,
                "trading_date": bar.trading_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "adjusted_close": bar.adjusted_close,
                "source": bar.source,
                "source_timestamp": bar.source_timestamp,
                "data_version": 1,
            }
            for bar in rows
        ]

        insert_stmt = pg_insert(OHLCVDaily).values(values)
        update_set = {col: getattr(insert_stmt.excluded, col) for col in UPSERT_COLUMNS}
        update_set["data_version"] = OHLCVDaily.data_version + 1

        # The WHERE clause makes this a true no-op (row untouched, not
        # returned) when the incoming data is identical to what's already
        # stored - this is what makes re-running ingestion with identical
        # input leave the table in exactly the same end state.
        changed = (
            (OHLCVDaily.open != insert_stmt.excluded.open)
            | (OHLCVDaily.high != insert_stmt.excluded.high)
            | (OHLCVDaily.low != insert_stmt.excluded.low)
            | (OHLCVDaily.close != insert_stmt.excluded.close)
            | (OHLCVDaily.volume != insert_stmt.excluded.volume)
            | (OHLCVDaily.adjusted_close != insert_stmt.excluded.adjusted_close)
            | (OHLCVDaily.source_timestamp != insert_stmt.excluded.source_timestamp)
        )

        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[OHLCVDaily.instrument_id, OHLCVDaily.trading_date, OHLCVDaily.source],
            set_=update_set,
            where=changed,
        ).returning(OHLCVDaily.trading_date, OHLCVDaily.source)

        result = await session.execute(upsert_stmt)
        written_keys = {(row.trading_date, row.source) for row in result.all()}

        rows_inserted = len(written_keys - existing_keys)
        rows_updated = len(written_keys & existing_keys)

    run.status = (
        IngestionStatus.partial
        if any(issue.severity == QualitySeverity.error for issue in issues)
        else IngestionStatus.success
    )
    run.finished_at = datetime.now(UTC)
    run.rows_processed = len(bars)
    run.rows_inserted = rows_inserted
    run.rows_updated = rows_updated
    await session.commit()

    logger.info(
        "market_data_sync completed",
        extra={
            "job": JOB_NAME,
            "symbol": instrument.symbol,
            "exchange": instrument.exchange,
            "rows_processed": len(bars),
            "rows_inserted": rows_inserted,
            "rows_updated": rows_updated,
            "quality_issue_count": len(issues),
            "status": run.status.value,
        },
    )

    return IngestionResult(
        ingestion_run_id=str(run.id),
        status=run.status,
        rows_processed=len(bars),
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        quality_issue_count=len(issues),
    )


async def ingest_daily_bars_for_instruments(
    provider: MarketDataProvider,
    instrument_refs: list[tuple[uuid.UUID, str, str]],
    start: date,
    end: date,
    *,
    concurrency: int = DEFAULT_INGESTION_CONCURRENCY,
    retry_policy: RetryPolicy | None = None,
) -> dict[str, Any]:
    """Bounded-concurrency, retrying batch sync for many instruments at once.

    This is the same semaphore-capped concurrent-fetch-with-retry/backoff
    pattern already proven at the ~750-symbol scale in
    `scripts/seed_dev_data.py::backfill_bars`/`_backfill_one` (SPEC.md
    section 59) - a handful of in-flight provider calls at a time (never
    fully sequential, never unbounded fan-out), each additionally
    staggered by a small random delay and retried with exponential
    backoff on transient failure. `apps/worker/jobs.py::sync_daily_bars`
    uses this instead of looping sequentially so the daily after-close
    pipeline (`daily_market_close_sync`) stays fast even against the full
    live universe.

    `instrument_refs` is `(instrument_id, symbol, exchange)` tuples, not
    live ORM `Instrument` objects, specifically so each concurrent task
    can open its *own* `session_scope()` and re-attach the row itself -
    never a single SQLAlchemy session shared across concurrent
    coroutines (unsafe with asyncpg).

    One instrument's permanent failure never aborts the batch - it's
    recorded in the returned `failed` list and the run continues with
    the rest, matching every other batch job in `apps/worker/jobs.py`.
    """
    retry_policy = retry_policy or RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=10.0)
    health = ProviderHealth(name="market_data_sync_batch", failure_threshold=50)
    results: dict[str, Any] = {"synced": [], "failed": []}
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_one(instrument_id: uuid.UUID, symbol: str, exchange: str) -> None:
        async with semaphore:
            # `await asyncio.sleep` (not a blocking `time.sleep`) - this
            # runs inside a concurrently-gathered coroutine, so a blocking
            # sleep here would stall every other "concurrent" task too.
            await asyncio.sleep(random.uniform(0.1, 0.3))

            attempt = 0
            last_exc: Exception | None = None
            while attempt < retry_policy.max_attempts:
                attempt += 1
                try:
                    async with session_scope() as session:
                        instrument = await session.get(Instrument, instrument_id)
                        if instrument is None:
                            raise ValueError(f"instrument {instrument_id} no longer exists")
                        result = await ingest_daily_bars(provider, session, instrument, start, end)
                    health.record_success()
                    results["synced"].append({"symbol": symbol, "status": result.status.value})
                    return
                except Exception as exc:  # noqa: BLE001 - caller-wide failure isolation, see docstring
                    last_exc = exc
                    health.record_failure()
                    if attempt >= retry_policy.max_attempts:
                        break
                    delay = retry_policy.delay_for_attempt(attempt)
                    logger.warning(
                        "market_data_sync_batch: transient failure, retrying",
                        extra={"symbol": symbol, "exchange": exchange, "attempt": attempt, "error": str(exc)},
                    )
                    await asyncio.sleep(delay)

            logger.error(
                "market_data_sync_batch: instrument failed after retries, continuing with next",
                extra={"symbol": symbol, "exchange": exchange, "error": str(last_exc)},
            )
            results["failed"].append({"symbol": symbol, "error": str(last_exc)})

    await asyncio.gather(*(_run_one(i, s, e) for i, s, e in instrument_refs))
    return results
