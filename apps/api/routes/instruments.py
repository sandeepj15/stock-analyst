"""Read-only instrument endpoints (SPEC.md section 48 subset).

No authentication/tenant isolation here - these endpoints only expose
public reference data (instrument master + OHLCV), not user-owned data.
Auth/tenant isolation is deferred to the production-hardening phase
(SPEC.md section 101, "Final Build Priority" step 16 / section 96).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import InstrumentNotFoundError, resolve_instrument
from packages.analyst_estimates.models import AnalystEstimate
from packages.common import cache
from packages.common.db import get_db_session
from packages.common.listing_queries import (
    latest_ml_forecast_subquery,
    latest_fundamental_growth_subquery,
    latest_momentum_subquery,
    latest_price_change_subquery,
    latest_research_score_subquery, latest_vcp_subquery,
)
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily
from packages.scoring.bands import score_band

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])

SortKey = Literal[
    "symbol", "company_name", "sector", "score", "momentum_pass", "is_vcp_setup", "analyst_upside_pct", "day_change_pct", "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "return_1y_pct", "revenue_growth_yoy", "pat_growth_yoy", "ml_forecast_5d_pct"
]
SortOrder = Literal["asc", "desc"]

# Short TTL (SPEC.md section 59): this listing backs the home page's
# main browse/sort table across ~750 rows, re-fetched on every column
# sort click. 90 seconds is long enough to make repeated loads/sort
# clicks within a session feel instant, short enough that a page left
# open never shows minutes-old data - well inside the "stale after 5
# days" heuristic every other endpoint here already uses for the
# underlying OHLCV data itself, and both batch jobs (score + momentum)
# are expected to run far less often than this TTL anyway.
LISTING_CACHE_TTL_SECONDS = 300


class InstrumentSummary(BaseModel):
    symbol: str
    exchange: str
    company_name: str
    sector: str | None
    instrument_type: str
    active: bool
    # Most recently *persisted* `research_scores` row for this instrument
    # (see packages/scoring/models.py), never computed live here - this
    # endpoint must stay cheap even for the full universe. `null` when no
    # score has been persisted yet (e.g. a fresh DB before
    # `apps/worker/jobs.py::compute_all_scores_job` has run). Band is
    # derived from `score` with the same `score_band` function the
    # on-demand `/score` endpoint uses - never recomputed differently.
    score: float | None = None
    confidence: float | None = None
    band: str | None = None
    # Most recently *persisted* `momentum_scans` row at the default
    # SMA200-trend-lookback (packages/momentum/, Stage 2 Momentum
    # Scanner), never computed live here - same "cheap, pre-persisted
    # join, never a live rescan" rule as `score` above. `null` when no
    # scan has been persisted yet, or when the stock has insufficient
    # history to evaluate (never a fabricated true/false either way -
    # SPEC.md section 81 rule 23).
    momentum_pass: bool | None = None
    distance_from_52w_high_pct: float | None = None
    # Day-over-day % price change, from the two most recently *persisted*
    # OHLCV bars (latest close vs. the one before it) - `null` whenever
    # an instrument has fewer than two bars ever ingested (a boundary
    # case, never a crash/fabricated value - SPEC.md section 81 rule 8).
    day_change_pct: float | None = None
    return_1w_pct: float | None = None
    return_1m_pct: float | None = None
    return_3m_pct: float | None = None
    return_6m_pct: float | None = None
    return_1y_pct: float | None = None
    ml_forecast_5d_pct: float | None = None
    # Most recently *persisted* `analyst_estimates` row (see
    # packages/analyst_estimates/) - 1-year analyst consensus price
    # target and the Wall-Street buy/hold/sell recommendation key.
    # `analyst_upside_pct` is computed here, at request time, against
    # this same listing's latest persisted close (never stored - the
    # underlying price changes continuously). `null` for every one of
    # these three fields whenever the instrument has zero analyst
    # coverage (common for mid/small-cap NSE names) or no OHLCV yet -
    # never fabricated.
    analyst_target_price: float | None = None
    analyst_upside_pct: float | None = None
    analyst_recommendation: str | None = None
    revenue_growth_yoy: float | None = None
    pat_growth_yoy: float | None = None
    is_vcp_setup: bool | None = None



class LatestBar(BaseModel):
    trading_date: str
    close: float
    adjusted_close: float
    volume: int
    source: str


class InstrumentDetail(InstrumentSummary):
    isin: str | None
    industry: str | None
    currency: str
    description: str | None = None
    ai_summary: str | None = None
    key_points: str | None = None
    website_url: str | None = None
    latest_bar: LatestBar | None
    data_freshness_seconds: float | None


@router.get("/search", response_model=list[InstrumentSummary])
async def search_instruments(
    q: str = Query(..., min_length=1, description="Substring match on symbol or company name"),
    limit: int = Query(default=20, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[InstrumentSummary]:
    latest_scores = latest_research_score_subquery()
    latest_momentum = latest_momentum_subquery()
    latest_price = latest_price_change_subquery()
    latest_growth = latest_fundamental_growth_subquery()
    latest_ml = latest_ml_forecast_subquery()

    latest_vcp = latest_vcp_subquery()

    upside_expr = case(
        (
            and_(
                AnalystEstimate.target_mean_price.isnot(None),
                latest_price.c.latest_close.isnot(None),
                latest_price.c.latest_close != 0,
            ),
            (AnalystEstimate.target_mean_price - latest_price.c.latest_close) / latest_price.c.latest_close * 100.0,
        ),
        else_=None,
    )
    
    ml_forecast_pct_expr = case(
        (
            and_(
                latest_ml.c.ml_forecast_close.isnot(None),
                latest_price.c.latest_close.isnot(None),
                latest_price.c.latest_close != 0,
            ),
            (latest_ml.c.ml_forecast_close - latest_price.c.latest_close) / latest_price.c.latest_close * 100.0,
        ),
        else_=None,
    )

    pattern = f"%{q.strip()}%"
    stmt = (
        select(
            Instrument,
            latest_scores.c.score,
            latest_scores.c.confidence,
            latest_momentum.c.passed,
            latest_vcp.c.is_vcp_setup,
            latest_momentum.c.distance_from_52w_high_pct,
            latest_price.c.day_change_pct,
            latest_price.c.return_1w_pct,
            latest_price.c.return_1m_pct,
            latest_price.c.return_3m_pct,
            latest_price.c.return_6m_pct,
            latest_price.c.return_1y_pct,
            latest_growth.c.revenue_growth_yoy,
            latest_growth.c.pat_growth_yoy,
            AnalystEstimate.target_mean_price,
            upside_expr.label("analyst_upside_pct"),
            ml_forecast_pct_expr.label("ml_forecast_5d_pct"),
            AnalystEstimate.recommendation_key,
        )
        .outerjoin(latest_scores, latest_scores.c.instrument_id == Instrument.id)
        .outerjoin(latest_momentum, latest_momentum.c.instrument_id == Instrument.id)
        .outerjoin(latest_vcp, latest_vcp.c.instrument_id == Instrument.id)
        .outerjoin(latest_price, latest_price.c.instrument_id == Instrument.id)
        .outerjoin(latest_growth, latest_growth.c.instrument_id == Instrument.id)
        .outerjoin(latest_ml, latest_ml.c.instrument_id == Instrument.id)
        .outerjoin(AnalystEstimate, AnalystEstimate.instrument_id == Instrument.id)
        .where((Instrument.symbol.ilike(pattern)) | (Instrument.company_name.ilike(pattern)))
        .order_by(Instrument.symbol)
        .limit(limit)
    )
    
    result = await session.execute(stmt)
    rows = result.all()

    summaries: list[InstrumentSummary] = []
    for (
        instrument,
        score,
        confidence,
        passed,
        is_vcp_setup,
        distance_from_high,
        day_change_pct,
        ret_1w,
        ret_1m,
        ret_3m,
        ret_6m,
        ret_1y,
        rev_growth,
        pat_growth,
        analyst_target_price,
        analyst_upside_pct,
        ml_forecast_5d_pct,
        analyst_recommendation,
    ) in rows:
        score_value = float(score) if score is not None else None
        summaries.append(
            InstrumentSummary(
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                company_name=instrument.company_name,
                sector=instrument.sector,
                instrument_type=instrument.instrument_type,
                active=instrument.active,
                score=score_value,
                confidence=float(confidence) if confidence is not None else None,
                band=score_band(score_value) if score_value is not None else None,
                momentum_pass=bool(passed) if passed is not None else None,
                is_vcp_setup=bool(is_vcp_setup) if is_vcp_setup is not None else None,
                distance_from_52w_high_pct=float(distance_from_high) if distance_from_high is not None else None,
                day_change_pct=float(day_change_pct) if day_change_pct is not None else None,
                return_1w_pct=float(ret_1w) if ret_1w is not None else None,
                return_1m_pct=float(ret_1m) if ret_1m is not None else None,
                return_3m_pct=float(ret_3m) if ret_3m is not None else None,
                return_6m_pct=float(ret_6m) if ret_6m is not None else None,
                return_1y_pct=float(ret_1y) if ret_1y is not None else None,
                revenue_growth_yoy=float(rev_growth) if rev_growth is not None else None,
                pat_growth_yoy=float(pat_growth) if pat_growth is not None else None,
                analyst_target_price=float(analyst_target_price) if analyst_target_price is not None else None,
                analyst_upside_pct=float(analyst_upside_pct) if analyst_upside_pct is not None else None,
                ml_forecast_5d_pct=float(ml_forecast_5d_pct) if ml_forecast_5d_pct is not None else None,
                analyst_recommendation=analyst_recommendation,
            )
        )
    return summaries


@router.get("", response_model=list[InstrumentSummary])
async def list_instruments(
    exchange: str = Query(default="NSE"),
    active_only: bool = Query(default=True),
    sort: SortKey = Query(default="symbol", description="Column to sort by"),
    order: SortOrder = Query(default="asc", description="asc or desc"),
    momentum_pass: bool | None = Query(
        default=None,
        description="If true, only return instruments whose latest Stage 2 Momentum Scan passed all 8 conditions.",
    ),
    sector: str | None = Query(default=None, description="Filter by sector exactly (case insensitive)."),
    min_score: float | None = Query(default=None, description="Minimum score (0-100)."),
    max_score: float | None = Query(default=None, description="Maximum score (0-100)."),
    session: AsyncSession = Depends(get_db_session),
) -> list[InstrumentSummary]:
    """List every seeded instrument (symbol/company_name/sector/score/momentum_pass/...).

    Used by the web frontend to populate the home page browse table
    (SPEC.md section 48/87, section 39's "Setup Scanner" concept). Unlike
    `/search`, this takes no query string and returns the full universe,
    each row left-joined with its most recently *persisted*
    `research_scores` row and its most recently *persisted*
    `momentum_scans` row at the default lookback - never computed live
    (see `InstrumentSummary.score`/`momentum_pass` docstrings above).

    `sort`/`order` are server-side (not left to the frontend to re-sort a
    partial page) so this stays correct however many instruments exist.
    When `sort=score` or `sort=momentum_pass`, instruments with no
    persisted value yet always sort last regardless of `order` (nulls
    are neither "best" nor "worst" - they are simply "not yet known").
    `?momentum_pass=true` turns this listing into an actual Stage 2
    scanner view (SPEC.md section 39): only instruments whose latest
    scan was a genuine, evaluable PASS are returned (never a stock whose
    scan was `null`/not-evaluable).

    Short-TTL cached in Redis (`LISTING_CACHE_TTL_SECONDS`, SPEC.md
    section 59) - see the module-level comment above for the TTL choice.
    """
    cache_key = (
        f"instruments_listing:v1:{exchange.upper()}:{active_only}:{sort}:{order}:{momentum_pass}:{sector}:{min_score}:{max_score}"
    )
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return [InstrumentSummary.model_validate(row) for row in cached]

    # Shared "latest row per instrument" subquery builders
    # (packages/common/listing_queries.py) - factored out so the new
    # `GET /api/v1/market/score-distribution` and `GET
    # /api/v1/market/sectors` endpoints (UI/UX "Market Pulse" task) reuse
    # the exact same efficient SQL instead of a second hand-written copy.
    latest_scores = latest_research_score_subquery()
    latest_momentum = latest_momentum_subquery()
    latest_price = latest_price_change_subquery()
    latest_growth = latest_fundamental_growth_subquery()
    latest_ml = latest_ml_forecast_subquery()
    latest_vcp = latest_vcp_subquery()

    upside_expr = case(
        (
            and_(
                AnalystEstimate.target_mean_price.isnot(None),
                latest_price.c.latest_close.isnot(None),
                latest_price.c.latest_close != 0,
            ),
            (AnalystEstimate.target_mean_price - latest_price.c.latest_close) / latest_price.c.latest_close * 100.0,
        ),
        else_=None,
    )

    ml_forecast_pct_expr = case(
        (
            and_(
                latest_ml.c.ml_forecast_close.isnot(None),
                latest_price.c.latest_close.isnot(None),
                latest_price.c.latest_close != 0,
            ),
            (latest_ml.c.ml_forecast_close - latest_price.c.latest_close) / latest_price.c.latest_close * 100.0,
        ),
        else_=None,
    )

    stmt = (
        select(
            Instrument,
            latest_scores.c.score,
            latest_scores.c.confidence,
            latest_momentum.c.passed,
            latest_vcp.c.is_vcp_setup,
            latest_momentum.c.distance_from_52w_high_pct,
            latest_price.c.day_change_pct,
            latest_price.c.return_1w_pct,
            latest_price.c.return_1m_pct,
            latest_price.c.return_3m_pct,
            latest_price.c.return_6m_pct,
            latest_price.c.return_1y_pct,
            latest_growth.c.revenue_growth_yoy,
            latest_growth.c.pat_growth_yoy,
            AnalystEstimate.target_mean_price,
            upside_expr.label("analyst_upside_pct"),
            ml_forecast_pct_expr.label("ml_forecast_5d_pct"),
            AnalystEstimate.recommendation_key,
        )
        .outerjoin(latest_scores, latest_scores.c.instrument_id == Instrument.id)
        .outerjoin(latest_momentum, latest_momentum.c.instrument_id == Instrument.id)
        .outerjoin(latest_vcp, latest_vcp.c.instrument_id == Instrument.id)
        .outerjoin(latest_price, latest_price.c.instrument_id == Instrument.id)
        .outerjoin(latest_growth, latest_growth.c.instrument_id == Instrument.id)
        .outerjoin(latest_ml, latest_ml.c.instrument_id == Instrument.id)
        .outerjoin(AnalystEstimate, AnalystEstimate.instrument_id == Instrument.id)
        .where(Instrument.exchange == exchange.upper())
    )
    if active_only:
        stmt = stmt.where(Instrument.active.is_(True))
    if momentum_pass is not None and isinstance(momentum_pass, bool):
        stmt = stmt.where(latest_momentum.c.passed == momentum_pass)
    if sector and isinstance(sector, str):
        stmt = stmt.where(func.lower(Instrument.sector) == sector.lower())
    if min_score is not None and isinstance(min_score, (int, float)):
        stmt = stmt.where(latest_scores.c.score >= min_score)
    if max_score is not None and isinstance(max_score, (int, float)):
        stmt = stmt.where(latest_scores.c.score <= max_score)

    sort_columns: dict[SortKey, Any] = {
        "symbol": Instrument.symbol,
        "company_name": Instrument.company_name,
        "sector": Instrument.sector,
        "score": latest_scores.c.score,
        "momentum_pass": latest_momentum.c.passed,
        "is_vcp_setup": latest_vcp.c.is_vcp_setup,

        "analyst_upside_pct": upside_expr,
        "day_change_pct": latest_price.c.day_change_pct,
        "return_1w_pct": latest_price.c.return_1w_pct,
        "return_1m_pct": latest_price.c.return_1m_pct,
        "return_3m_pct": latest_price.c.return_3m_pct,
        "return_6m_pct": latest_price.c.return_6m_pct,
        "return_1y_pct": latest_price.c.return_1y_pct,
        "revenue_growth_yoy": latest_growth.c.revenue_growth_yoy,
        "pat_growth_yoy": latest_growth.c.pat_growth_yoy,
        "ml_forecast_5d_pct": ml_forecast_pct_expr,
    }
    sort_column = sort_columns[sort]
    direction = sort_column.desc() if order == "desc" else sort_column.asc()

    if sort in ("score", "momentum_pass", "is_vcp_setup", "analyst_upside_pct", "day_change_pct", "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "return_1y_pct", "revenue_growth_yoy", "pat_growth_yoy", "ml_forecast_5d_pct"):
        # Nulls always sort last, in either direction (see docstring above).
        stmt = stmt.order_by(nulls_last(direction), Instrument.symbol.asc())
    else:
        stmt = stmt.order_by(direction, Instrument.symbol.asc())

    result = await session.execute(stmt)
    rows = result.all()

    summaries: list[InstrumentSummary] = []
    for (
        instrument,
        score,
        confidence,
        passed,
        is_vcp_setup,
        distance_from_high,
        day_change_pct,
        ret_1w,
        ret_1m,
        ret_3m,
        ret_6m,
        ret_1y,
        rev_growth,
        pat_growth,
        analyst_target_price,
        analyst_upside_pct,
        ml_forecast_5d_pct,
        analyst_recommendation,
    ) in rows:
        score_value = float(score) if score is not None else None
        summaries.append(
            InstrumentSummary(
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                company_name=instrument.company_name,
                sector=instrument.sector,
                instrument_type=instrument.instrument_type,
                active=instrument.active,
                score=score_value,
                confidence=float(confidence) if confidence is not None else None,
                band=score_band(score_value) if score_value is not None else None,
                momentum_pass=bool(passed) if passed is not None else None,
                is_vcp_setup=bool(is_vcp_setup) if is_vcp_setup is not None else None,
                distance_from_52w_high_pct=float(distance_from_high) if distance_from_high is not None else None,
                day_change_pct=float(day_change_pct) if day_change_pct is not None else None,
                return_1w_pct=float(ret_1w) if ret_1w is not None else None,
                return_1m_pct=float(ret_1m) if ret_1m is not None else None,
                return_3m_pct=float(ret_3m) if ret_3m is not None else None,
                return_6m_pct=float(ret_6m) if ret_6m is not None else None,
                return_1y_pct=float(ret_1y) if ret_1y is not None else None,
                revenue_growth_yoy=float(rev_growth) if rev_growth is not None else None,
                pat_growth_yoy=float(pat_growth) if pat_growth is not None else None,
                analyst_target_price=float(analyst_target_price) if analyst_target_price is not None else None,
                analyst_upside_pct=float(analyst_upside_pct) if analyst_upside_pct is not None else None,
                ml_forecast_5d_pct=float(ml_forecast_5d_pct) if ml_forecast_5d_pct is not None else None,
                analyst_recommendation=analyst_recommendation,
            )
        )

    await cache.set_json(cache_key, [s.model_dump() for s in summaries], LISTING_CACHE_TTL_SECONDS)
    return summaries


@router.get("/{symbol}", response_model=InstrumentDetail)
async def get_instrument(
    symbol: str,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> InstrumentDetail:
    try:
        instrument = await resolve_instrument(session, symbol, exchange)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    bar_stmt = (
        select(OHLCVDaily)
        .where(OHLCVDaily.instrument_id == instrument.id)
        .order_by(OHLCVDaily.trading_date.desc())
        .limit(1)
    )
    bar_result = await session.execute(bar_stmt)
    latest = bar_result.scalar_one_or_none()

    latest_bar = None
    freshness_seconds = None
    if latest is not None:
        latest_bar = LatestBar(
            trading_date=latest.trading_date.isoformat(),
            close=float(latest.close),
            adjusted_close=float(latest.adjusted_close),
            volume=int(latest.volume),
            source=latest.source,
        )
        latest_dt = datetime.combine(latest.trading_date, datetime.min.time(), tzinfo=UTC)
        freshness_seconds = (datetime.now(UTC) - latest_dt).total_seconds()

    return InstrumentDetail(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        company_name=instrument.company_name,
        sector=instrument.sector,
        industry=instrument.industry,
        instrument_type=instrument.instrument_type,
        currency=instrument.currency,
        isin=instrument.isin,
        active=instrument.active,
        description=instrument.description,
        ai_summary=instrument.ai_summary,
        key_points=instrument.key_points,
        website_url=instrument.website_url,
        latest_bar=latest_bar,
        data_freshness_seconds=freshness_seconds,
    )
