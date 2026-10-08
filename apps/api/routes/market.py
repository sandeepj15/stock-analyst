"""Market-wide endpoints (SPEC.md sections 15, 48, Phase 3).

`GET /api/v1/market/regime` - the latest stored market regime
classification plus the underlying feature values that produced it, so
it is explainable rather than a black box (same evidence-first
philosophy as the Research Score). See `packages/regime/` and
`docs/architecture/market_regime.md` for the full rule table.

`GET /api/v1/market/score-distribution` and `GET /api/v1/market/sectors`
(UI/UX "Market Pulse" home-page dashboard task) back the score-band bar
chart and sector heatmap respectively - both are single grouped SQL
queries (never a per-instrument loop, SPEC.md section 59) built from the
shared "latest row per instrument" subqueries in
`packages/common/listing_queries.py`, and both are short-TTL Redis
cached, same reasoning as `GET /api/v1/instruments`.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common import cache
from packages.common.db import get_db_session
from packages.common.listing_queries import (
    latest_momentum_subquery,
    latest_price_change_subquery,
    latest_research_score_subquery,
    score_band_case,
)
from packages.common.models import Instrument
from packages.regime.service import BREADTH_UNIVERSE_LABEL, get_latest_regime
from packages.scoring.bands import SCORE_BAND_THRESHOLDS, VERY_STRONG_LABEL

router = APIRouter(prefix="/api/v1/market", tags=["market"])

# Canonical band display order (Very Weak -> Very Strong) - matches
# packages.scoring.bands.SCORE_BAND_THRESHOLDS exactly, never a
# hand-reordered copy.
BAND_ORDER: list[str] = [label for _, label in SCORE_BAND_THRESHOLDS] + [VERY_STRONG_LABEL]

# Short TTL, same reasoning/value as apps/api/routes/instruments.py's
# LISTING_CACHE_TTL_SECONDS - both of these aggregate queries are over
# the same ~750-instrument universe and are invalidated by the same
# daily batch jobs (research scores, OHLCV).
MARKET_AGGREGATE_CACHE_TTL_SECONDS = 90


class MarketRegimeResponse(BaseModel):
    date: str
    regime: str
    nifty_close: float
    nifty_vs_200dma_pct: float | None
    breadth_above_50dma_pct: float | None
    breadth_above_200dma_pct: float | None
    rolling_volatility_pct: float | None
    rule_version: str
    breadth_universe: str
    computed_at: str


@router.get("/regime", response_model=MarketRegimeResponse)
async def get_market_regime(session: AsyncSession = Depends(get_db_session)) -> MarketRegimeResponse:
    """Latest classification. 404 if no regime has ever been computed yet.

    Run via the `sync_market_regime` worker job or
    `packages.regime.service.compute_and_store_regime` - this endpoint is
    read-only and never computes on the fly (it would otherwise have to
    refresh the Nifty benchmark + scan the full seeded universe inline on
    every GET, which belongs in a scheduled job - SPEC.md section 56).
    """
    regime = await get_latest_regime(session)
    if regime is None:
        raise HTTPException(
            status_code=404,
            detail="No market regime has been computed yet. Run the sync_market_regime worker job first.",
        )

    return MarketRegimeResponse(
        date=regime.date.isoformat(),
        regime=regime.regime.value,
        nifty_close=float(regime.nifty_close),
        nifty_vs_200dma_pct=float(regime.nifty_vs_200dma_pct) if regime.nifty_vs_200dma_pct is not None else None,
        breadth_above_50dma_pct=float(regime.breadth_above_50dma_pct) if regime.breadth_above_50dma_pct is not None else None,
        breadth_above_200dma_pct=float(regime.breadth_above_200dma_pct) if regime.breadth_above_200dma_pct is not None else None,
        rolling_volatility_pct=float(regime.rolling_volatility_pct) if regime.rolling_volatility_pct is not None else None,
        rule_version=regime.rule_version,
        breadth_universe=BREADTH_UNIVERSE_LABEL,
        computed_at=regime.computed_at.isoformat(),
    )


class ScoreBandCount(BaseModel):
    band: str
    count: int


class ScoreDistributionResponse(BaseModel):
    as_of: str
    universe_size: int
    unscored_count: int
    bands: list[ScoreBandCount]


@router.get("/score-distribution", response_model=ScoreDistributionResponse)
async def get_score_distribution(
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> ScoreDistributionResponse:
    """How many active EQUITY instruments fall into each Research Score band.

    Backs the home page's score-distribution bar chart. A single grouped
    query (never 756 individual `/score` lookups, SPEC.md section 59):
    outer-joins every active instrument to its most recently persisted
    `research_scores` row (`packages/common/listing_queries.py`, the same
    helper `GET /api/v1/instruments` uses), buckets by the exact same
    `score_band` thresholds via `score_band_case`, and lets Postgres do
    the counting. Instruments with no persisted score yet are counted
    separately as `unscored_count`, never miscounted into any band.
    """
    cache_key = f"market_score_distribution:v1:{exchange.upper()}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return ScoreDistributionResponse.model_validate(cached)

    latest_scores = latest_research_score_subquery()
    band_expr = score_band_case(latest_scores.c.score)

    stmt = (
        # Labeled "band_count" rather than "count" - `Row` objects are
        # tuple-like and already expose a `.count()` *method*, which
        # would otherwise shadow a same-named `.count` column attribute
        # (mypy correctly flags this; a differently-named label sidesteps
        # the collision entirely rather than needing a cast/ignore).
        select(band_expr.label("band"), func.count().label("band_count"))
        .select_from(Instrument)
        .outerjoin(latest_scores, latest_scores.c.instrument_id == Instrument.id)
        .where(Instrument.exchange == exchange.upper(), Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
        .group_by(band_expr)
    )
    rows = (await session.execute(stmt)).all()

    counts_by_band: dict[str | None, int] = {row.band: row.band_count for row in rows}
    unscored_count = counts_by_band.pop(None, 0)
    bands = [ScoreBandCount(band=label, count=counts_by_band.get(label, 0)) for label in BAND_ORDER]
    universe_size = sum(b.count for b in bands) + unscored_count

    response = ScoreDistributionResponse(
        as_of=datetime.now(UTC).isoformat(),
        universe_size=universe_size,
        unscored_count=unscored_count,
        bands=bands,
    )
    await cache.set_json(cache_key, response.model_dump(), MARKET_AGGREGATE_CACHE_TTL_SECONDS)
    return response


class SectorSummary(BaseModel):
    sector: str
    instrument_count: int
    avg_score: float | None
    avg_day_change_pct: float | None
    momentum_pass_count: int


class SectorsResponse(BaseModel):
    as_of: str
    sectors: list[SectorSummary]


@router.get("/sectors", response_model=SectorsResponse)
async def get_sector_summary(
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> SectorsResponse:
    """Per-sector aggregate: avg Research Score, avg day-over-day % price
    change, instrument count, and count passing Stage 2 Momentum.

    Backs the home page's sector heatmap/grid. A single grouped query
    (never a per-sector or per-instrument loop): outer-joins every active
    instrument to its latest score / latest momentum scan / latest
    day-over-day price change (all three from the shared
    `packages/common/listing_queries.py` helpers) and lets Postgres
    aggregate per `COALESCE(sector, 'Unclassified')` group. Instruments
    with no persisted score/scan/price-change simply don't contribute to
    that particular average/count (SQL `AVG`/`SUM` already skip `NULL`s)
    - never fabricated into a 0.
    """
    cache_key = f"market_sectors:v1:{exchange.upper()}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return SectorsResponse.model_validate(cached)

    latest_scores = latest_research_score_subquery()
    latest_momentum = latest_momentum_subquery()
    latest_price = latest_price_change_subquery()

    sector_label = func.coalesce(Instrument.sector, "Unclassified")
    momentum_pass_count_expr = func.sum(case((latest_momentum.c.passed.is_(True), 1), else_=0))

    stmt = (
        select(
            sector_label.label("sector"),
            func.count().label("instrument_count"),
            func.avg(latest_scores.c.score).label("avg_score"),
            func.avg(latest_price.c.day_change_pct).label("avg_day_change_pct"),
            momentum_pass_count_expr.label("momentum_pass_count"),
        )
        .select_from(Instrument)
        .outerjoin(latest_scores, latest_scores.c.instrument_id == Instrument.id)
        .outerjoin(latest_momentum, latest_momentum.c.instrument_id == Instrument.id)
        .outerjoin(latest_price, latest_price.c.instrument_id == Instrument.id)
        .where(Instrument.exchange == exchange.upper(), Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
        .group_by(sector_label)
        .order_by(sector_label)
    )
    rows = (await session.execute(stmt)).all()

    sectors = [
        SectorSummary(
            sector=row.sector,
            instrument_count=row.instrument_count,
            avg_score=float(row.avg_score) if row.avg_score is not None else None,
            avg_day_change_pct=float(row.avg_day_change_pct) if row.avg_day_change_pct is not None else None,
            momentum_pass_count=int(row.momentum_pass_count or 0),
        )
        for row in rows
    ]

    response = SectorsResponse(as_of=datetime.now(UTC).isoformat(), sectors=sectors)
    await cache.set_json(cache_key, response.model_dump(), MARKET_AGGREGATE_CACHE_TTL_SECONDS)
    return response
