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

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, case, func, select, text
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
from packages.market_data.models import OHLCVDaily
from packages.momentum.models import MomentumScan
from packages.momentum.scanner import DEFAULT_SMA200_TREND_LOOKBACK_DAYS
from packages.regime.service import BREADTH_UNIVERSE_LABEL, get_latest_regime
from packages.scoring.bands import SCORE_BAND_THRESHOLDS, VERY_STRONG_LABEL
from packages.scoring.models import ResearchScore

router = APIRouter(prefix="/api/v1/market", tags=["market"])

# Canonical band display order (Very Weak -> Very Strong) - matches
# packages.scoring.bands.SCORE_BAND_THRESHOLDS exactly, never a
# hand-reordered copy.
BAND_ORDER: list[str] = [label for _, label in SCORE_BAND_THRESHOLDS] + [VERY_STRONG_LABEL]

# 1-hour Redis TTL for market aggregates. Invalidated by daily batch jobs.
MARKET_AGGREGATE_CACHE_TTL_SECONDS = 3600

# Fast in-process L1 cache for sub-millisecond market responses
_SECTORS_L1_CACHE: dict[str, tuple[float, SectorsResponse]] = {}
_REGIME_L1_CACHE: dict[str, tuple[float, MarketRegimeResponse]] = {}
_SCORE_DIST_L1_CACHE: dict[str, tuple[float, ScoreDistributionResponse]] = {}
_L1_TTL = 120.0
_SECTORS_L1_TTL = 120.0


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
async def get_market_regime(
    response: Response = None,
    session: AsyncSession = Depends(get_db_session),
) -> MarketRegimeResponse:
    """Latest classification. 404 if no regime has ever been computed yet.

    Multi-tier cached: L1 in-process RAM (sub-ms) -> L2 Redis (1 hr) -> DB fallback.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"

    now_ts = time.time()
    if "latest" in _REGIME_L1_CACHE:
        cached_time, cached_regime = _REGIME_L1_CACHE["latest"]
        if now_ts - cached_time < _L1_TTL:
            return cached_regime

    cache_key = "market_regime:v1"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        try:
            res = MarketRegimeResponse.model_validate(cached)
            _REGIME_L1_CACHE["latest"] = (now_ts, res)
            return res
        except Exception:
            pass

    regime = await get_latest_regime(session)
    if regime is None:
        raise HTTPException(
            status_code=404,
            detail="No market regime has been computed yet. Run the sync_market_regime worker job first.",
        )

    res = MarketRegimeResponse(
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
    _REGIME_L1_CACHE["latest"] = (now_ts, res)
    await cache.set_json(cache_key, res.model_dump(), MARKET_AGGREGATE_CACHE_TTL_SECONDS)
    return res


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
    response: Response = None,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> ScoreDistributionResponse:
    """How many active EQUITY instruments fall into each Research Score band.

    Multi-tier cached: L1 in-process RAM (sub-ms) -> L2 Redis (1 hr) -> Lean covering-index DB query.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"

    exchange_upper = exchange.upper()
    now_ts = time.time()
    if exchange_upper in _SCORE_DIST_L1_CACHE:
        cached_time, cached_dist = _SCORE_DIST_L1_CACHE[exchange_upper]
        if now_ts - cached_time < _L1_TTL:
            return cached_dist

    cache_key = f"market_score_distribution:v1:{exchange_upper}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        try:
            res = ScoreDistributionResponse.model_validate(cached)
            _SCORE_DIST_L1_CACHE[exchange_upper] = (now_ts, res)
            return res
        except Exception:
            pass

    # Lean subquery: selects only instrument_id and score, enabling Postgres to execute an Index-Only Scan
    # via ix_research_scores_covering without fetching heavy components JSONB off disk
    latest_scores = (
        select(
            ResearchScore.instrument_id.label("instrument_id"),
            ResearchScore.score.label("score"),
        )
        .distinct(ResearchScore.instrument_id)
        .order_by(ResearchScore.instrument_id, ResearchScore.computed_at.desc())
        .subquery()
    )
    band_expr = score_band_case(latest_scores.c.score)

    stmt = (
        select(band_expr.label("band"), func.count().label("band_count"))
        .select_from(Instrument)
        .outerjoin(latest_scores, latest_scores.c.instrument_id == Instrument.id)
        .where(Instrument.exchange == exchange_upper, Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
        .group_by(band_expr)
    )
    rows = (await session.execute(stmt)).all()

    counts_by_band: dict[str | None, int] = {row.band: row.band_count for row in rows}
    unscored_count = counts_by_band.pop(None, 0)
    bands = [ScoreBandCount(band=label, count=counts_by_band.get(label, 0)) for label in BAND_ORDER]
    universe_size = sum(b.count for b in bands) + unscored_count

    res = ScoreDistributionResponse(
        as_of=datetime.now(UTC).isoformat(),
        universe_size=universe_size,
        unscored_count=unscored_count,
        bands=bands,
    )
    _SCORE_DIST_L1_CACHE[exchange_upper] = (now_ts, res)
    await cache.set_json(cache_key, res.model_dump(), MARKET_AGGREGATE_CACHE_TTL_SECONDS)
    return res


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
    response: Response,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> SectorsResponse:
    """Per-sector aggregate: avg Research Score, avg day-over-day % price
    change, instrument count, and count passing Stage 2 Momentum.
    """
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"

    now = time.monotonic()
    exchange_upper = exchange.upper()

    # 1. Check L1 in-memory process cache (0.01ms)
    l1_entry = _SECTORS_L1_CACHE.get(exchange_upper)
    if l1_entry is not None and (now - l1_entry[0]) < _SECTORS_L1_TTL:
        return l1_entry[1]

    # 2. Check L2 Redis cache (~2ms)
    cache_key = f"market_sectors:v1:{exchange_upper}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        parsed = SectorsResponse.model_validate(cached)
        _SECTORS_L1_CACHE[exchange_upper] = (now, parsed)
        return parsed

    # 3. Optimized Database Query (lean window scan + covering index lookups)
    ranked_price = (
        select(
            OHLCVDaily.instrument_id.label("instrument_id"),
            OHLCVDaily.adjusted_close.label("adjusted_close"),
            func.row_number().over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc()).label("rn"),
            func.lead(OHLCVDaily.adjusted_close, 1).over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc()).label("prev_1d"),
        )
        .where(OHLCVDaily.trading_date >= text("CURRENT_DATE - INTERVAL '14 days'"))
    ).subquery()

    price_sub = (
        select(
            ranked_price.c.instrument_id,
            case(
                (and_(ranked_price.c.prev_1d.isnot(None), ranked_price.c.prev_1d != 0),
                 (ranked_price.c.adjusted_close - ranked_price.c.prev_1d) / ranked_price.c.prev_1d * 100.0),
                else_=None,
            ).label("day_change_pct"),
        )
        .where(ranked_price.c.rn == 1)
        .subquery()
    )

    score_sub = (
        select(
            ResearchScore.instrument_id,
            ResearchScore.score,
        )
        .distinct(ResearchScore.instrument_id)
        .order_by(ResearchScore.instrument_id, ResearchScore.computed_at.desc())
        .subquery()
    )

    momentum_sub = (
        select(
            MomentumScan.instrument_id,
            MomentumScan.passed,
        )
        .where(MomentumScan.sma200_trend_lookback_days == DEFAULT_SMA200_TREND_LOOKBACK_DAYS)
        .distinct(MomentumScan.instrument_id)
        .order_by(MomentumScan.instrument_id, MomentumScan.computed_at.desc())
        .subquery()
    )

    sector_label = func.coalesce(Instrument.sector, "Unclassified")

    stmt = (
        select(
            sector_label.label("sector"),
            func.count().label("instrument_count"),
            func.avg(score_sub.c.score).label("avg_score"),
            func.avg(price_sub.c.day_change_pct).label("avg_day_change_pct"),
            func.sum(case((momentum_sub.c.passed.is_(True), 1), else_=0)).label("momentum_pass_count"),
        )
        .select_from(Instrument)
        .outerjoin(score_sub, score_sub.c.instrument_id == Instrument.id)
        .outerjoin(momentum_sub, momentum_sub.c.instrument_id == Instrument.id)
        .outerjoin(price_sub, price_sub.c.instrument_id == Instrument.id)
        .where(Instrument.exchange == exchange_upper, Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
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

    response_obj = SectorsResponse(as_of=datetime.now(UTC).isoformat(), sectors=sectors)
    _SECTORS_L1_CACHE[exchange_upper] = (now, response_obj)
    await cache.set_json(cache_key, response_obj.model_dump(), MARKET_AGGREGATE_CACHE_TTL_SECONDS)
    return response_obj


class ForecastCallItem(BaseModel):
    symbol: str
    company_name: str
    pred_return_pct: float
    act_return_pct: float
    mape_pct: float


class PrecisionTier(BaseModel):
    tier: str
    label: str
    count: int
    pct: float
    win_rate_pct: float


class MlPerformanceResponse(BaseModel):
    as_of_date: str
    horizon_days: int
    evaluated_count: int
    correct_count: int
    incorrect_count: int
    directional_win_rate_pct: float
    avg_mape_pct: float
    median_mape_pct: float
    eval_start_date: str | None
    eval_end_date: str | None
    tiers: list[PrecisionTier]
    top_bullish_calls: list[ForecastCallItem]
    top_bearish_calls: list[ForecastCallItem]
    pinpoint_calls: list[ForecastCallItem]


@router.get("/ml-performance", response_model=MlPerformanceResponse)
async def get_ml_performance(
    as_of: str | None = Query(default=None, description="Optional YYYY-MM-DD to evaluate. Defaults to latest evaluated week."),
    session: AsyncSession = Depends(get_db_session),
) -> MlPerformanceResponse:
    """Historical accuracy & directional performance of 5-day ML forecasts.

    Returns the directional win-rate, MAPE error distribution tiers, and notable
    outperforming calls (bullish breakouts, bearish falls, and pinpoint forecasts)
    for the most recently realized forecast horizon.
    """
    cache_key = f"market_ml_performance:v1:{as_of or 'latest'}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return MlPerformanceResponse.model_validate(cached)

    # 1. Resolve target date
    if as_of:
        target_date_query = text("SELECT DISTINCT as_of_date FROM ml_forecasts WHERE as_of_date = :as_of AND evaluated_at IS NOT NULL LIMIT 1")
        res = await session.execute(target_date_query, {"as_of": as_of})
        row = res.first()
        if not row:
            raise HTTPException(status_code=404, detail=f"No evaluated forecasts found for date {as_of}")
        target_date = row[0]
    else:
        target_date_query = text("SELECT as_of_date FROM ml_forecasts WHERE evaluated_at IS NOT NULL GROUP BY as_of_date ORDER BY as_of_date DESC LIMIT 1")
        res = await session.execute(target_date_query)
        row = res.first()
        if not row:
            raise HTTPException(status_code=404, detail="No evaluated ML forecasts available yet.")
        target_date = row[0]

    # 2. Aggregate metrics and precision tiers
    agg_query = text("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN directional_accuracy THEN 1 END) as correct_count,
            COUNT(CASE WHEN NOT directional_accuracy THEN 1 END) as incorrect_count,
            ROUND(AVG(mape)::numeric * 100, 2) as avg_mape_pct,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY mape)::numeric * 100, 2) as median_mape_pct,
            COUNT(CASE WHEN mape < 0.02 THEN 1 END) as t1_count,
            COUNT(CASE WHEN mape < 0.02 AND directional_accuracy THEN 1 END) as t1_correct,
            COUNT(CASE WHEN mape >= 0.02 AND mape < 0.05 THEN 1 END) as t2_count,
            COUNT(CASE WHEN mape >= 0.02 AND mape < 0.05 AND directional_accuracy THEN 1 END) as t2_correct,
            COUNT(CASE WHEN mape >= 0.05 AND mape < 0.10 THEN 1 END) as t3_count,
            COUNT(CASE WHEN mape >= 0.05 AND mape < 0.10 AND directional_accuracy THEN 1 END) as t3_correct,
            COUNT(CASE WHEN mape >= 0.10 THEN 1 END) as t4_count,
            COUNT(CASE WHEN mape >= 0.10 AND directional_accuracy THEN 1 END) as t4_correct
        FROM ml_forecasts
        WHERE as_of_date = :target_date
          AND evaluated_at IS NOT NULL
    """)
    agg_res = await session.execute(agg_query, {"target_date": target_date})
    agg = agg_res.mappings().first()
    if not agg or agg["total"] == 0:
        raise HTTPException(status_code=404, detail="No evaluated forecasts found for target date.")

    total = int(agg["total"])
    correct = int(agg["correct_count"])
    incorrect = int(agg["incorrect_count"])
    win_rate = round((correct / total) * 100, 1) if total > 0 else 0.0

    def calc_tier(count: int, correct_in_tier: int, tier_id: str, label: str) -> PrecisionTier:
        pct = round((count / total) * 100, 1) if total > 0 else 0.0
        win = round((correct_in_tier / count) * 100, 1) if count > 0 else 0.0
        return PrecisionTier(tier=tier_id, label=label, count=count, pct=pct, win_rate_pct=win)

    tiers = [
        calc_tier(int(agg["t1_count"]), int(agg["t1_correct"]), "under_2", "Pinpoint (<2% Error)"),
        calc_tier(int(agg["t2_count"]), int(agg["t2_correct"]), "2_to_5", "Strong (2-5% Error)"),
        calc_tier(int(agg["t3_count"]), int(agg["t3_correct"]), "5_to_10", "Moderate (5-10% Error)"),
        calc_tier(int(agg["t4_count"]), int(agg["t4_correct"]), "over_10", "High Volatility (>10% Error)"),
    ]

    # 3. Notable calls
    base_calls_query = text("""
        WITH base AS (
            SELECT 
                i.symbol,
                i.company_name,
                m.mape,
                m.directional_accuracy,
                ROUND((((m.trajectory->-1->>'close')::numeric - (m.trajectory->0->>'close')::numeric) / NULLIF((m.trajectory->0->>'close')::numeric, 0)) * 100, 2) as pred_return_pct,
                ROUND((((m.actual_trajectory->-1->>'close')::numeric - (m.actual_trajectory->0->>'close')::numeric) / NULLIF((m.actual_trajectory->0->>'close')::numeric, 0)) * 100, 2) as act_return_pct,
                m.actual_trajectory->0->>'date' as start_date,
                m.actual_trajectory->-1->>'date' as end_date
            FROM ml_forecasts m
            JOIN instruments i ON m.instrument_id = i.id
            WHERE m.as_of_date = :target_date
              AND m.evaluated_at IS NOT NULL
        )
        SELECT * FROM base
    """)
    base_res = (await session.execute(base_calls_query, {"target_date": target_date})).mappings().all()

    eval_start_date = base_res[0]["start_date"] if base_res else None
    eval_end_date = base_res[0]["end_date"] if base_res else None

    # Filter bullish: pred > 0 and act > 0, sort by act_return_pct DESC
    bullish = [
        ForecastCallItem(
            symbol=r["symbol"],
            company_name=r["company_name"],
            pred_return_pct=float(r["pred_return_pct"]),
            act_return_pct=float(r["act_return_pct"]),
            mape_pct=round(float(r["mape"]) * 100, 2),
        )
        for r in sorted(
            [r for r in base_res if r["pred_return_pct"] is not None and r["act_return_pct"] is not None and r["pred_return_pct"] > 0 and r["act_return_pct"] > 0],
            key=lambda x: x["act_return_pct"],
            reverse=True,
        )[:6]
    ]

    # Filter bearish: pred < 0 and act < 0, sort by act_return_pct ASC
    bearish = [
        ForecastCallItem(
            symbol=r["symbol"],
            company_name=r["company_name"],
            pred_return_pct=float(r["pred_return_pct"]),
            act_return_pct=float(r["act_return_pct"]),
            mape_pct=round(float(r["mape"]) * 100, 2),
        )
        for r in sorted(
            [r for r in base_res if r["pred_return_pct"] is not None and r["act_return_pct"] is not None and r["pred_return_pct"] < 0 and r["act_return_pct"] < 0],
            key=lambda x: x["act_return_pct"],
        )[:6]
    ]

    # Filter pinpoint: directional_accuracy is True, sort by mape ASC
    pinpoint = [
        ForecastCallItem(
            symbol=r["symbol"],
            company_name=r["company_name"],
            pred_return_pct=float(r["pred_return_pct"] or 0),
            act_return_pct=float(r["act_return_pct"] or 0),
            mape_pct=round(float(r["mape"]) * 100, 2),
        )
        for r in sorted(
            [r for r in base_res if r["directional_accuracy"] and r["mape"] is not None],
            key=lambda x: x["mape"],
        )[:6]
    ]

    response = MlPerformanceResponse(
        as_of_date=str(target_date),
        horizon_days=5,
        evaluated_count=total,
        correct_count=correct,
        incorrect_count=incorrect,
        directional_win_rate_pct=win_rate,
        avg_mape_pct=float(agg["avg_mape_pct"] or 0),
        median_mape_pct=float(agg["median_mape_pct"] or 0),
        eval_start_date=eval_start_date,
        eval_end_date=eval_end_date,
        tiers=tiers,
        top_bullish_calls=bullish,
        top_bearish_calls=bearish,
        pinpoint_calls=pinpoint,
    )
    await cache.set_json(cache_key, response.model_dump(), MARKET_AGGREGATE_CACHE_TTL_SECONDS)
    return response


from packages.fundamentals.checklist import (
    ChecklistSummaryResponse,
    StockChecklistResult,
    get_all_checklist_results,
)


@router.get("/fundamental-checklist", response_model=ChecklistSummaryResponse)
async def get_fundamental_checklist(
    min_score: int = Query(default=6, ge=0, le=6, description="Minimum conditions met (0-6)"),
    sector: str | None = Query(default=None, description="Optional sector filter"),
    session: AsyncSession = Depends(get_db_session),
) -> ChecklistSummaryResponse:
    """Evaluate instruments against the 6-point institutional multibagger checklist framework.

    Conditions from the institutional checklist:
    1. Opportunity: Growing Industry & Large Growth Potential (Small/Mid Cap with established management)
    2. Large Aspiration: Active Capex, expansion & forward guidance
    3. Earnings: Revenue & Profits growth, expanding margins
    4. Quality: Return on capital (ROCE, ROE), positive cashflow, low debt
    5. Value Analysis: Analyst rating/targets sentiment + Low/Moderate valuation
    6. Shareholding Pattern: Increasing institutional ownership (FII/DII)
    """
    cache_key = f"market_fundamental_checklist:v1:{min_score}:{sector or 'all'}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return ChecklistSummaryResponse.model_validate(cached)

    result = await get_all_checklist_results(session, min_score=min_score, sector=sector)
    await cache.set_json(cache_key, result.model_dump(), MARKET_AGGREGATE_CACHE_TTL_SECONDS)
    return result


