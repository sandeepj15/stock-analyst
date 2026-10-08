"""Stage 2 Momentum Scanner endpoint (packages/momentum/, MOMENTUM_SCANNER.md).

`GET /api/v1/stocks/{symbol}/momentum-scan` - the full 8-condition
"Minervini Trend Template" breakdown for one instrument, Redis
cache-first (SPEC.md section 59) exactly like `/score`
(`apps/api/routes/scoring.py`).

No LLM calls anywhere in this module (SPEC.md section 81 rule 3).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import resolve_instrument_or_404
from packages.common import cache
from packages.common.db import get_db_session
from packages.momentum.scanner import DEFAULT_SMA200_TREND_LOOKBACK_DAYS
from packages.momentum.service import (
    MOMENTUM_SCAN_CACHE_TTL_SECONDS,
    MomentumScanResponse,
    compute_momentum_scan,
    momentum_scan_cache_key,
    to_momentum_scan_cache_payload,
)

router = APIRouter(prefix="/api/v1/stocks", tags=["momentum"])

# A caller may request a stricter trend-confirmation window (SPEC.md
# task spec: "~90-110 (4-5 months)") - bounded to a sane trading-day
# range rather than left unbounded.
MIN_LOOKBACK_DAYS = 5
MAX_LOOKBACK_DAYS = 252


@router.get("/{symbol}/momentum-scan", response_model=MomentumScanResponse)
async def get_momentum_scan(
    symbol: str,
    exchange: str = Query(default="NSE"),
    sma200_trend_lookback_days: int = Query(
        default=DEFAULT_SMA200_TREND_LOOKBACK_DAYS,
        ge=MIN_LOOKBACK_DAYS,
        le=MAX_LOOKBACK_DAYS,
        description=(
            "Trading days back to compare SMA200 against for condition 3 "
            "(default 22, ~1 month). Set to ~90-110 (4-5 months) for a "
            "stricter long-term-trend confirmation window."
        ),
    ),
    session: AsyncSession = Depends(get_db_session),
) -> MomentumScanResponse:
    """Full 8-condition Stage 2 Trend Template breakdown for `symbol`.

    Cache-first (`momentum_scan:v1:{instrument_id}:{sma200_trend_lookback_days}`,
    populated primarily by `apps/worker/jobs.py::compute_all_momentum_scans_job`'s
    write-through at the *default* lookback). A non-default
    `sma200_trend_lookback_days` always computes live (its own cache key
    is only populated by a prior on-demand call at that same value, not
    by the batch job) - this never fabricates a cached result for a
    lookback window it wasn't actually computed with.

    Never 404s/422s for "insufficient history" - a stock with less than
    ~252 trading days is a legitimate, clearly-labeled `evaluable: false`
    result (SPEC.md section 81 rule 23), not an error.
    """
    instrument = await resolve_instrument_or_404(session, symbol, exchange)
    cache_key = momentum_scan_cache_key(instrument.id, sma200_trend_lookback_days)

    cached = await cache.get_json(cache_key)
    if cached is not None:
        return MomentumScanResponse(**cached, cache_hit=True)

    result = await compute_momentum_scan(
        session, instrument, sma200_trend_lookback_days=sma200_trend_lookback_days
    )
    await cache.set_json(cache_key, to_momentum_scan_cache_payload(result), MOMENTUM_SCAN_CACHE_TTL_SECONDS)
    return result
