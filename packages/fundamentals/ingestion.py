"""Fundamentals ingestion service (SPEC.md sections 12, 56-58).

`sync_fundamentals` mirrors `packages.market_data.ingestion.ingest_daily_bars`:
a single entry point used by both the Arq worker job and the seed script,
idempotent by construction (upsert on `(instrument_id, period_end,
period_type, source)` - running it twice with identical provider output
leaves the table in the same end state).

Never fabricates a value for a period/field the provider doesn't have -
if the provider returns zero snapshots for an instrument (common for
thinly-covered NSE tickers on yfinance), this records that as a
successful run with `rows_processed=0`, not a failure.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.models import Instrument
from packages.fundamentals.base import FundamentalDataProvider
from packages.fundamentals.models import FundamentalSnapshot

logger = logging.getLogger(__name__)

JOB_NAME = "fundamentals_sync"

UPSERT_COLUMNS = (
    "revenue",
    "ebitda",
    "ebit",
    "pat",
    "eps",
    "operating_cash_flow",
    "free_cash_flow",
    "total_assets",
    "total_liabilities",
    "total_debt",
    "cash",
    "equity",
    "shares_outstanding",
    "dividend_yield",
    "interest_expense",
    "current_assets",
    "current_liabilities",
    "source_timestamp",
    "field_sources",
)


class FundamentalsSyncResult(BaseModel):
    symbol: str
    exchange: str
    rows_processed: int
    rows_inserted: int
    rows_updated: int
    error_message: str | None = None


async def sync_fundamentals(
    provider: FundamentalDataProvider,
    session: AsyncSession,
    instrument: Instrument,
) -> FundamentalsSyncResult:
    """Fetch and idempotently upsert every available fundamentals snapshot for one instrument."""
    try:
        # Same rationale as packages/market_data/ingestion.py: run the
        # blocking provider call in a worker thread so concurrent
        # instruments' fundamentals syncs can actually overlap their
        # network I/O (SPEC.md section 59) instead of serializing on the
        # event loop.
        snapshots = await asyncio.to_thread(provider.get_fundamental_snapshots, instrument.symbol, instrument.exchange)
    except Exception as exc:
        logger.error(
            "fundamentals_sync failed",
            extra={"job": JOB_NAME, "symbol": instrument.symbol, "exchange": instrument.exchange, "error": str(exc)},
        )
        raise

    if not snapshots:
        logger.info(
            "fundamentals_sync: no coverage from provider",
            extra={"job": JOB_NAME, "symbol": instrument.symbol, "exchange": instrument.exchange},
        )
        return FundamentalsSyncResult(
            symbol=instrument.symbol, exchange=instrument.exchange, rows_processed=0, rows_inserted=0, rows_updated=0
        )

    keys = [(snap.period_end, snap.period_type, snap.source) for snap in snapshots]
    existing_result = await session.execute(
        select(FundamentalSnapshot.period_end, FundamentalSnapshot.period_type, FundamentalSnapshot.source).where(
            FundamentalSnapshot.instrument_id == instrument.id,
            FundamentalSnapshot.period_end.in_({k[0] for k in keys}),
        )
    )
    existing_keys = {(row.period_end, row.period_type, row.source) for row in existing_result.all()}

    values: list[dict[str, Any]] = [
        {
            "instrument_id": instrument.id,
            "period_end": snap.period_end,
            "period_type": snap.period_type,
            "revenue": snap.revenue,
            "ebitda": snap.ebitda,
            "ebit": snap.ebit,
            "pat": snap.pat,
            "eps": snap.eps,
            "operating_cash_flow": snap.operating_cash_flow,
            "free_cash_flow": snap.free_cash_flow,
            "total_assets": snap.total_assets,
            "total_liabilities": snap.total_liabilities,
            "total_debt": snap.total_debt,
            "cash": snap.cash,
            "equity": snap.equity,
            "shares_outstanding": snap.shares_outstanding,
            "dividend_yield": snap.dividend_yield,
            "interest_expense": snap.interest_expense,
            "current_assets": snap.current_assets,
            "current_liabilities": snap.current_liabilities,
            "source": snap.source,
            "source_timestamp": snap.source_timestamp,
            "field_sources": snap.field_sources or None,
        }
        for snap in snapshots
    ]

    insert_stmt = pg_insert(FundamentalSnapshot).values(values)
    update_set = {col: getattr(insert_stmt.excluded, col) for col in UPSERT_COLUMNS}

    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[
            FundamentalSnapshot.instrument_id,
            FundamentalSnapshot.period_end,
            FundamentalSnapshot.period_type,
            FundamentalSnapshot.source,
        ],
        set_=update_set,
    ).returning(FundamentalSnapshot.period_end, FundamentalSnapshot.period_type, FundamentalSnapshot.source)

    result = await session.execute(upsert_stmt)
    written_keys = {(row.period_end, row.period_type, row.source) for row in result.all()}

    rows_inserted = len(written_keys - existing_keys)
    rows_updated = len(written_keys & existing_keys)

    await session.commit()

    logger.info(
        "fundamentals_sync completed",
        extra={
            "job": JOB_NAME,
            "symbol": instrument.symbol,
            "exchange": instrument.exchange,
            "rows_processed": len(snapshots),
            "rows_inserted": rows_inserted,
            "rows_updated": rows_updated,
        },
    )

    return FundamentalsSyncResult(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        rows_processed=len(snapshots),
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
    )

