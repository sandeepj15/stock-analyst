"""Analyst Rating / 1-Year Price Target endpoint.

`GET /api/v1/stocks/{symbol}/analyst-rating` - the latest persisted
analyst-consensus price target (`packages/analyst_estimates/`) plus
`upside_pct`, computed on demand against the instrument's latest close
price (never stored - the underlying price changes continuously, same
reasoning as `packages/fundamentals/derive.py::compute_valuation_metrics`).

Coverage is genuinely partial: many mid/small-cap NSE names have zero
analyst coverage. `has_coverage=False` + every numeric field `null` is
the honest "missing" state here, never a fabricated number (SPEC.md
section 81 rule 8) - same convention as `/fundamentals`'s
`has_fundamental_data`.

Redis-cached (SPEC.md section 59), write-through populated by
`apps/worker/jobs.py::sync_analyst_estimates_job` - same shape as
`packages/scoring/engine.py`'s score cache. `upside_pct` is **not**
itself part of the cached payload (it depends on the current price,
which the batch job does not re-fetch) - it is always computed fresh
against the latest persisted close at request time, cache hit or not.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import resolve_instrument_or_404
from packages.analyst_estimates.ingestion import (
    ANALYST_RATING_CACHE_TTL_SECONDS,
    analyst_rating_cache_key,
    to_analyst_estimate_cache_payload,
)
from packages.analyst_estimates.models import AnalystEstimate
from packages.common import cache
from packages.common.db import get_db_session
from packages.market_data.history import load_ohlcv_dataframe

router = APIRouter(prefix="/api/v1/stocks", tags=["analyst-rating"])


class AnalystRatingResponse(BaseModel):
    symbol: str
    exchange: str
    has_coverage: bool
    target_mean_price: float | None
    target_high_price: float | None
    target_low_price: float | None
    target_median_price: float | None
    current_price: float | None
    # (target_mean_price - current_price) / current_price * 100. Positive
    # = upside (target above current price, shown green by the UI).
    # Negative = downside (shown red). `null` whenever either input is
    # missing - never computed from a fabricated price or target.
    upside_pct: float | None
    recommendation_mean: float | None
    recommendation_key: str | None
    number_of_analyst_opinions: int | None
    source: str | None
    source_timestamp: str | None
    data_age_days: int | None
    reason: str | None
    cache_hit: bool = False


def _empty_response(symbol: str, exchange: str) -> AnalystRatingResponse:
    return AnalystRatingResponse(
        symbol=symbol,
        exchange=exchange,
        has_coverage=False,
        target_mean_price=None,
        target_high_price=None,
        target_low_price=None,
        target_median_price=None,
        current_price=None,
        upside_pct=None,
        recommendation_mean=None,
        recommendation_key=None,
        number_of_analyst_opinions=None,
        source=None,
        source_timestamp=None,
        data_age_days=None,
        reason="no_analyst_coverage",
    )


@router.get("/{symbol}/analyst-rating", response_model=AnalystRatingResponse)
async def get_analyst_rating(
    symbol: str,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> AnalystRatingResponse:
    instrument = await resolve_instrument_or_404(session, symbol, exchange)
    now = datetime.now(UTC)

    cache_key = analyst_rating_cache_key(instrument.id)
    cached = await cache.get_json(cache_key)
    if cached is not None:
        payload = dict(cached)
        cache_hit = True
    else:
        stmt = select(AnalystEstimate).where(AnalystEstimate.instrument_id == instrument.id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return _empty_response(instrument.symbol, instrument.exchange)
        payload = to_analyst_estimate_cache_payload(row)
        await cache.set_json(cache_key, payload, ANALYST_RATING_CACHE_TTL_SECONDS)
        cache_hit = False

    source_timestamp = datetime.fromisoformat(payload["source_timestamp"])
    data_age_days = (now.date() - source_timestamp.date()).days

    from packages.market_data.models import OHLCVDaily

    stmt_price = (
        select(OHLCVDaily.adjusted_close)
        .where(OHLCVDaily.instrument_id == instrument.id)
        .order_by(OHLCVDaily.trading_date.desc(), OHLCVDaily.ingested_at.desc())
        .limit(1)
    )
    latest_adj = (await session.execute(stmt_price)).scalar_one_or_none()
    current_price = float(latest_adj) if latest_adj is not None else None

    target_mean = payload["target_mean_price"]
    upside_pct: float | None = None
    if target_mean is not None and current_price is not None and current_price != 0:
        upside_pct = (target_mean - current_price) / current_price * 100.0

    return AnalystRatingResponse(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        has_coverage=True,
        target_mean_price=target_mean,
        target_high_price=payload["target_high_price"],
        target_low_price=payload["target_low_price"],
        target_median_price=payload["target_median_price"],
        current_price=current_price,
        upside_pct=upside_pct,
        recommendation_mean=payload["recommendation_mean"],
        recommendation_key=payload["recommendation_key"],
        number_of_analyst_opinions=payload["number_of_analyst_opinions"],
        source=payload["source"],
        source_timestamp=payload["source_timestamp"],
        data_age_days=data_age_days,
        reason=None,
        cache_hit=cache_hit,
    )
