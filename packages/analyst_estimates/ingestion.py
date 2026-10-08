"""Analyst-estimate ingestion service.

`sync_analyst_estimate` mirrors `packages.fundamentals.ingestion.sync_fundamentals`:
a single entry point used by both the Arq worker job
(`apps/worker/jobs.py::sync_analyst_estimates_job`) and any ad-hoc
script, idempotent by construction (upsert on `instrument_id` - running
it twice with identical provider output leaves the table in the same
end state, and running it with fresh provider output simply overwrites
the single row - see `packages/analyst_estimates/models.py`'s docstring
for why this is not an append-only table).

Never fabricates a value - if the provider returns `None` (zero analyst
coverage, common for thinly-covered NSE tickers), this deletes any
stale existing row for the instrument and records the run as a
successful "no coverage" outcome, not a failure.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.analyst_estimates.base import AnalystEstimateProvider
from packages.analyst_estimates.models import AnalystEstimate
from packages.common.models import Instrument

logger = logging.getLogger(__name__)

JOB_NAME = "analyst_estimates_sync"

UPSERT_COLUMNS = (
    "target_mean_price",
    "target_high_price",
    "target_low_price",
    "target_median_price",
    "recommendation_mean",
    "recommendation_key",
    "number_of_analyst_opinions",
    "source",
    "source_timestamp",
    "field_sources",
)


class AnalystEstimateSyncResult(BaseModel):
    symbol: str
    exchange: str
    has_coverage: bool
    source: str | None = None


# --- Redis caching (SPEC.md section 59) - mirrors
# packages/scoring/engine.py's score-cache pattern: `apps/api/routes/
# analyst.py`'s on-demand route and `apps/worker/jobs.py::
# sync_analyst_estimates_job`'s write-through both read/write this exact
# cache key + JSON shape. TTL (6 hours) is a safety net, not the primary
# population mechanism - analyst targets refresh far less often than
# prices (this task's own "don't put this in the daily cron" rule), so a
# longer TTL than the score cache (30 min) is appropriate here.
ANALYST_RATING_CACHE_KEY_PREFIX = "analyst_rating:v1"
ANALYST_RATING_CACHE_TTL_SECONDS = 6 * 3600


def analyst_rating_cache_key(instrument_id: object) -> str:
    return f"{ANALYST_RATING_CACHE_KEY_PREFIX}:{instrument_id}"


def to_analyst_estimate_cache_payload(row: AnalystEstimate) -> dict:
    """JSON-serializable dict of the persisted row only - never includes
    `current_price`/`upside_pct` (always computed fresh against the
    latest close at request time, by `apps/api/routes/analyst.py`), same
    "cache the persisted facts, compute the price-dependent part live"
    split as `packages.scoring.engine.to_score_response_payload`.
    """
    return {
        "target_mean_price": float(row.target_mean_price) if row.target_mean_price is not None else None,
        "target_high_price": float(row.target_high_price) if row.target_high_price is not None else None,
        "target_low_price": float(row.target_low_price) if row.target_low_price is not None else None,
        "target_median_price": float(row.target_median_price) if row.target_median_price is not None else None,
        "recommendation_mean": float(row.recommendation_mean) if row.recommendation_mean is not None else None,
        "recommendation_key": row.recommendation_key,
        "number_of_analyst_opinions": row.number_of_analyst_opinions,
        "source": row.source,
        "source_timestamp": row.source_timestamp.isoformat(),
    }


async def sync_analyst_estimate(
    provider: AnalystEstimateProvider,
    session: AsyncSession,
    instrument: Instrument,
) -> AnalystEstimateSyncResult:
    """Fetch and idempotently upsert the current analyst estimate for one instrument."""
    try:
        # Blocking provider call off the event loop, same rationale as
        # packages/fundamentals/ingestion.py::sync_fundamentals (so
        # concurrent instruments' syncs can overlap their network I/O).
        estimate = await asyncio.to_thread(provider.get_analyst_estimate, instrument.symbol, instrument.exchange)
    except Exception as exc:
        logger.error(
            "analyst_estimates_sync failed",
            extra={"job": JOB_NAME, "symbol": instrument.symbol, "exchange": instrument.exchange, "error": str(exc)},
        )
        raise

    if estimate is None:
        logger.info(
            "analyst_estimates_sync: no coverage from provider",
            extra={"job": JOB_NAME, "symbol": instrument.symbol, "exchange": instrument.exchange},
        )
        # Clear any stale prior coverage (e.g. an instrument that used to
        # have analyst coverage and no longer does) - never leave a
        # fabricated-looking stale row behind.
        await session.execute(delete(AnalystEstimate).where(AnalystEstimate.instrument_id == instrument.id))
        await session.commit()
        return AnalystEstimateSyncResult(symbol=instrument.symbol, exchange=instrument.exchange, has_coverage=False)

    values = {
        "id": uuid.uuid4(),
        "instrument_id": instrument.id,
        "target_mean_price": estimate.target_mean_price,
        "target_high_price": estimate.target_high_price,
        "target_low_price": estimate.target_low_price,
        "target_median_price": estimate.target_median_price,
        "recommendation_mean": estimate.recommendation_mean,
        "recommendation_key": estimate.recommendation_key,
        "number_of_analyst_opinions": estimate.number_of_analyst_opinions,
        "source": estimate.source,
        "source_timestamp": estimate.source_timestamp,
        "field_sources": estimate.field_sources or None,
    }

    insert_stmt = pg_insert(AnalystEstimate).values(**values)
    update_set = {col: getattr(insert_stmt.excluded, col) for col in UPSERT_COLUMNS}
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[AnalystEstimate.instrument_id], set_=update_set
    )
    await session.execute(upsert_stmt)
    await session.commit()

    logger.info(
        "analyst_estimates_sync completed",
        extra={"job": JOB_NAME, "symbol": instrument.symbol, "exchange": instrument.exchange, "source": estimate.source},
    )
    return AnalystEstimateSyncResult(
        symbol=instrument.symbol, exchange=instrument.exchange, has_coverage=True, source=estimate.source
    )


async def sync_analyst_estimates_batch(
    provider: AnalystEstimateProvider,
    session: AsyncSession,
    instruments: list[Instrument],
) -> list[AnalystEstimateSyncResult]:
    """Fetch and idempotently upsert current analyst estimates for multiple instruments using bulk fetching."""
    if not instruments:
        return []
        
    inst_tuples = [(i.symbol, i.exchange) for i in instruments]
    inst_map = {(i.symbol, i.exchange): i for i in instruments}
    
    try:
        results_dict = await asyncio.to_thread(provider.get_analyst_estimates_batch, inst_tuples)
    except Exception as exc:
        logger.error(
            "analyst_estimates_batch_sync failed completely",
            extra={"job": JOB_NAME, "error": str(exc)},
        )
        raise
        
    final_results = []
    
    for symbol, exchange in inst_tuples:
        instrument = inst_map[(symbol, exchange)]
        estimate = results_dict.get((symbol, exchange))
        
        if estimate is None:
            await session.execute(delete(AnalystEstimate).where(AnalystEstimate.instrument_id == instrument.id))
            final_results.append(AnalystEstimateSyncResult(symbol=symbol, exchange=exchange, has_coverage=False))
            continue
            
        values = {
            "id": uuid.uuid4(),
            "instrument_id": instrument.id,
            "target_mean_price": estimate.target_mean_price,
            "target_high_price": estimate.target_high_price,
            "target_low_price": estimate.target_low_price,
            "target_median_price": estimate.target_median_price,
            "recommendation_mean": estimate.recommendation_mean,
            "recommendation_key": estimate.recommendation_key,
            "number_of_analyst_opinions": estimate.number_of_analyst_opinions,
            "source": estimate.source,
            "source_timestamp": estimate.source_timestamp,
            "field_sources": estimate.field_sources or None,
        }

        insert_stmt = pg_insert(AnalystEstimate).values(**values)
        update_set = {col: getattr(insert_stmt.excluded, col) for col in UPSERT_COLUMNS}
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[AnalystEstimate.instrument_id], set_=update_set
        )
        await session.execute(upsert_stmt)
        final_results.append(AnalystEstimateSyncResult(
            symbol=symbol, exchange=exchange, has_coverage=True, source=estimate.source
        ))
        
    await session.commit()
    return final_results
