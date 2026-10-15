"""Stage 2 Momentum Scanner endpoint (packages/momentum/, MOMENTUM_SCANNER.md).

`GET /api/v1/stocks/{symbol}/momentum-scan` - the full 8-condition
"Minervini Trend Template" breakdown for one instrument, Redis
cache-first (SPEC.md section 59) exactly like `/score`
(`apps/api/routes/scoring.py`).

No LLM calls anywhere in this module (SPEC.md section 81 rule 3).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import resolve_instrument_or_404
from packages.common import cache
from packages.common.db import get_db_session
from packages.momentum.models import MomentumScan
from packages.momentum.rs_rank import RS_RANK_UNIVERSE_LABEL
from packages.momentum.scanner import DEFAULT_SMA200_TREND_LOOKBACK_DAYS
from packages.momentum.service import (
    MOMENTUM_SCAN_CACHE_TTL_SECONDS,
    ConditionOut,
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

    # Fast path: check if we have a persisted momentum scan in the database first
    stmt = (
        select(MomentumScan)
        .where(
            MomentumScan.instrument_id == instrument.id,
            MomentumScan.sma200_trend_lookback_days == sma200_trend_lookback_days,
        )
        .order_by(MomentumScan.computed_at.desc())
        .limit(1)
    )
    latest_row = (await session.execute(stmt)).scalar_one_or_none()
    if latest_row is not None:
        result = MomentumScanResponse(
            instrument_id=str(latest_row.instrument_id),
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            scan_date=latest_row.scan_date.isoformat() if latest_row.scan_date else None,
            evaluable=latest_row.passed is not None,
            passed=latest_row.passed,
            conditions=[ConditionOut(**c) for c in (latest_row.conditions or [])],
            distance_from_52w_high_pct=float(latest_row.distance_from_52w_high_pct) if latest_row.distance_from_52w_high_pct is not None else None,
            rs_rank=float(latest_row.rs_rank) if latest_row.rs_rank is not None else None,
            rs_rank_universe=RS_RANK_UNIVERSE_LABEL,
            sma200_trend_lookback_days=latest_row.sma200_trend_lookback_days,
            methodology_version=latest_row.methodology_version,
            computed_at=latest_row.computed_at.isoformat(),
            reason=None,
            cache_hit=False,
        )
        await cache.set_json(cache_key, to_momentum_scan_cache_payload(result), MOMENTUM_SCAN_CACHE_TTL_SECONDS)
        return result

    result = await compute_momentum_scan(
        session, instrument, sma200_trend_lookback_days=sma200_trend_lookback_days
    )
    await cache.set_json(cache_key, to_momentum_scan_cache_payload(result), MOMENTUM_SCAN_CACHE_TTL_SECONDS)
    return result
