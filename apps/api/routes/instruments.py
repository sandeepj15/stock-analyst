"""Read-only instrument endpoints (SPEC.md section 48 subset).

No authentication/tenant isolation here - these endpoints only expose
public reference data (instrument master + OHLCV), not user-owned data.
Auth/tenant isolation is deferred to the production-hardening phase
(SPEC.md section 101, "Final Build Priority" step 16 / section 96).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import Numeric, String, and_, case, cast, func, nulls_last, select, text
from sqlalchemy.dialects.postgresql import JSONPATH
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
    latest_research_score_subquery,
    latest_vcp_subquery,
    latest_institutional_holdings_subquery,
)
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily
from packages.scoring.bands import score_band

router = APIRouter(prefix="/api/v1/instruments", tags=["instruments"])

SortKey = Literal[
    "symbol", "company_name", "sector", "score", "fundamental_score", "is_multibagger", "momentum_pass", "is_vcp_setup", "analyst_upside_pct", "analyst_recommendation", "day_change_pct", "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "return_1y_pct", "revenue_growth_yoy", "pat_growth_yoy", "ml_forecast_5d_pct", "tv_momentum_flag", "fii_current", "fii_change_qoq_pct", "distance_from_52w_high_pct"
]
SortOrder = Literal["asc", "desc"]

# Cache for 30 minutes in Redis so navigation and universe browsing
# respond in < 1ms without expensive uncached DB joins on every request.
LISTING_CACHE_TTL_SECONDS = 1800


async def get_multibagger_symbol_set(session: AsyncSession) -> set[str]:
    cache_key = "multibagger_symbols:v1"
    cached = await cache.get_json(cache_key)
    if cached is not None and isinstance(cached, list):
        return set(cached)
    from packages.fundamentals.checklist import get_all_checklist_results
    res = await get_all_checklist_results(session, min_score=6)
    symbols = [item.symbol for item in res.items if item.conditions_met == 6]
    await cache.set_json(cache_key, symbols, 3600)
    return set(symbols)


async def get_52w_breakout_map(session: AsyncSession) -> dict[str, float]:
    """Return map of { symbol: breakout_pct } for stocks strictly closing above their 52-week high.
    
    A stock qualifies if and only if its latest closing price is strictly greater than the maximum high
    of all daily bars over the trailing 52 weeks (365 calendar days) prior to the latest bar.
    Intraday wicks that exceed the 52W high but close below it are strictly excluded.
    Cached in Redis for fast (< 1ms) universe lookups.
    """
    cache_key = "52w_breakout_stocks_map:v2"
    cached = await cache.get_json(cache_key)
    if cached is not None and isinstance(cached, dict):
        return cached

    stmt = text("""
        WITH latest_bars AS (
            SELECT p.instrument_id, p.trading_date, p.close
            FROM ohlcv_daily p
            JOIN (
                SELECT instrument_id, MAX(trading_date) as max_date
                FROM ohlcv_daily
                GROUP BY instrument_id
            ) lat ON p.instrument_id = lat.instrument_id AND p.trading_date = lat.max_date
        ),
        prior_52w AS (
            SELECT 
                p_sub.instrument_id,
                MAX(p_sub.high) as prior_high
            FROM ohlcv_daily p_sub
            JOIN latest_bars lb ON p_sub.instrument_id = lb.instrument_id
            WHERE p_sub.trading_date >= lb.trading_date - INTERVAL '365 days'
              AND p_sub.trading_date < lb.trading_date
            GROUP BY p_sub.instrument_id
        )
        SELECT 
            i.symbol,
            ROUND(((lb.close - p52.prior_high) / p52.prior_high * 100.0)::numeric, 2) as breakout_pct
        FROM instruments i
        JOIN latest_bars lb ON i.id = lb.instrument_id
        JOIN prior_52w p52 ON i.id = p52.instrument_id
        WHERE lb.close > p52.prior_high
          AND i.active IS TRUE
        ORDER BY breakout_pct DESC;
    """)
    result = await session.execute(stmt)
    breakout_map = {row[0].upper(): float(row[1]) for row in result.all()}
    await cache.set_json(cache_key, breakout_map, 3600)
    return breakout_map


class InstrumentSummary(BaseModel):
    symbol: str
    exchange: str
    company_name: str
    logo_url: str | None = None
    sector: str | None
    instrument_type: str
    active: bool
    score: float | None = None
    confidence: float | None = None
    band: str | None = None
    fundamental_score: float | None = None
    fundamental_band: str | None = None
    is_multibagger: bool | None = None
    momentum_pass: bool | None = None
    is_52w_breakout: bool = False
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
    tv_signal_1d: str | None = None
    tv_signal_1w: str | None = None
    tv_momentum_flag: str | None = None
    fii_current: float | None = None
    fii_change_qoq_pct: float | None = None



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
    clean_q = q.strip().upper()

    # 1. Check if universe listing is already in Redis cache (< 1ms response)
    cached_universe = await cache.get_json("instruments_listing:v2:NSE:True:symbol:asc:None:None:None:None")
    if not cached_universe:
        cached_universe = await cache.get_json("instruments_listing:v2:NSE:true:symbol:asc:None:None:None:None")

    if cached_universe:
        def rank_match(item: dict) -> tuple[int, str]:
            sym = item.get("symbol", "").upper()
            name = (item.get("company_name") or "").upper()
            if sym == clean_q:
                return (0, sym)
            if sym.startswith(clean_q):
                return (1, sym)
            if name.startswith(clean_q):
                return (2, sym)
            return (3, sym)

        matches = [
            item for item in cached_universe
            if clean_q in item.get("symbol", "").upper() or clean_q in (item.get("company_name") or "").upper()
        ]
        matches.sort(key=rank_match)
        return [InstrumentSummary.model_validate(row) for row in matches[:limit]]

    # 2. Check dedicated search query cache
    search_cache_key = f"instruments_search:v2:{clean_q}:{limit}"
    cached_search = await cache.get_json(search_cache_key)
    if cached_search is not None:
        return [InstrumentSummary.model_validate(row) for row in cached_search]

    # 3. Find matching instrument IDs first for fast indexed filtering
    pattern = f"%{clean_q}%"
    id_stmt = (
        select(Instrument.id)
        .where((Instrument.symbol.ilike(pattern)) | (Instrument.company_name.ilike(pattern)))
        .limit(limit)
    )
    id_res = await session.execute(id_stmt)
    matching_ids = id_res.scalars().all()
    if not matching_ids:
        return []

    latest_scores = latest_research_score_subquery()
    latest_momentum = latest_momentum_subquery()
    latest_price = latest_price_change_subquery()
    latest_growth = latest_fundamental_growth_subquery()
    latest_ml = latest_ml_forecast_subquery()
    latest_vcp = latest_vcp_subquery()
    latest_holdings = latest_institutional_holdings_subquery()

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
            latest_scores.c.components,
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
            latest_holdings.c.fii_current,
            latest_holdings.c.fii_qoq_change.label("fii_change_qoq_pct"),
        )
        .outerjoin(latest_scores, latest_scores.c.instrument_id == Instrument.id)
        .outerjoin(latest_momentum, latest_momentum.c.instrument_id == Instrument.id)
        .outerjoin(latest_vcp, latest_vcp.c.instrument_id == Instrument.id)
        .outerjoin(latest_price, latest_price.c.instrument_id == Instrument.id)
        .outerjoin(latest_growth, latest_growth.c.instrument_id == Instrument.id)
        .outerjoin(latest_ml, latest_ml.c.instrument_id == Instrument.id)
        .outerjoin(latest_holdings, latest_holdings.c.instrument_id == Instrument.id)
        .outerjoin(AnalystEstimate, AnalystEstimate.instrument_id == Instrument.id)
        .where(Instrument.id.in_(matching_ids))
        .order_by(Instrument.symbol)
    )
    
    result = await session.execute(stmt)
    rows = result.all()
    multibagger_symbols = await get_multibagger_symbol_set(session)
    breakout_map = await get_52w_breakout_map(session)
    from packages.market_data.tradingview_signals import get_universe_tradingview_signals
    tv_signals_map = await get_universe_tradingview_signals()

    summaries: list[InstrumentSummary] = []
    for (
        instrument,
        score,
        confidence,
        components,
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
        fii_current,
        fii_change_qoq_pct,
    ) in rows:
        score_value = float(score) if score is not None else None
        fundamental_score = None
        if components and isinstance(components, list):
            for comp in components:
                if comp.get("name") == "fundamentals":
                    f_val = comp.get("score")
                    fundamental_score = round(float(f_val), 1) if f_val is not None else None
                    break
        fundamental_band = score_band(fundamental_score) if fundamental_score is not None else None
        is_mb = (instrument.symbol in multibagger_symbols) if multibagger_symbols is not None else False
        tv_info = tv_signals_map.get(instrument.symbol.upper(), {})
        analyst_rec = analyst_recommendation or tv_info.get("tv_analyst_rating")
        if analyst_rec:
            analyst_rec = analyst_rec.upper()
        sym_upper = instrument.symbol.upper()
        is_bo = sym_upper in breakout_map
        dist_high_val = breakout_map[sym_upper] if is_bo else (float(distance_from_high) if distance_from_high is not None else None)
        summaries.append(
            InstrumentSummary(
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                company_name=instrument.company_name,
                logo_url=instrument.logo_url,
                sector=instrument.sector,
                instrument_type=instrument.instrument_type,
                active=instrument.active,
                score=score_value,
                confidence=float(confidence) if confidence is not None else None,
                band=score_band(score_value) if score_value is not None else None,
                fundamental_score=fundamental_score,
                fundamental_band=fundamental_band,
                is_multibagger=is_mb,
                momentum_pass=bool(passed) if passed is not None else None,
                is_vcp_setup=bool(is_vcp_setup) if is_vcp_setup is not None else None,
                is_52w_breakout=is_bo,
                distance_from_52w_high_pct=dist_high_val,
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
                analyst_recommendation=analyst_rec,
                tv_signal_1d=tv_info.get("tv_signal_1d"),
                tv_signal_1w=tv_info.get("tv_signal_1w"),
                tv_momentum_flag=tv_info.get("tv_momentum_flag"),
                fii_current=float(fii_current) if fii_current is not None else None,
                fii_change_qoq_pct=float(fii_change_qoq_pct) if fii_change_qoq_pct is not None else None,
            )
        )
    await cache.set_json(search_cache_key, [s.model_dump() for s in summaries], 300)
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
    breakout_only: bool | None = Query(
        default=None,
        description="If true, only return instruments closing at or above their 52-week high (breakout).",
    ),
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
        f"instruments_listing:v2:{exchange.upper()}:{active_only}:{sort}:{order}:{momentum_pass}:{sector}:{min_score}:{max_score}:{breakout_only}"
    )
    raw_cached = await cache.get_raw(cache_key)
    if raw_cached is not None:
        return Response(content=raw_cached, media_type="application/json")

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
    latest_holdings = latest_institutional_holdings_subquery()

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

    multibagger_symbols = await get_multibagger_symbol_set(session)

    stmt = (
        select(
            Instrument,
            latest_scores.c.score,
            latest_scores.c.confidence,
            latest_scores.c.components,
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
            latest_holdings.c.fii_current,
            latest_holdings.c.fii_qoq_change.label("fii_change_qoq_pct"),
        )
        .outerjoin(latest_scores, latest_scores.c.instrument_id == Instrument.id)
        .outerjoin(latest_momentum, latest_momentum.c.instrument_id == Instrument.id)
        .outerjoin(latest_vcp, latest_vcp.c.instrument_id == Instrument.id)
        .outerjoin(latest_price, latest_price.c.instrument_id == Instrument.id)
        .outerjoin(latest_growth, latest_growth.c.instrument_id == Instrument.id)
        .outerjoin(latest_ml, latest_ml.c.instrument_id == Instrument.id)
        .outerjoin(latest_holdings, latest_holdings.c.instrument_id == Instrument.id)
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
    breakout_map = await get_52w_breakout_map(session)
    breakout_symbols = set(breakout_map.keys())

    if breakout_only is True:
        stmt = stmt.where(Instrument.symbol.in_(breakout_symbols))

    fund_score_expr = cast(
        func.nullif(
            cast(
                func.jsonb_path_query_first(
                    latest_scores.c.components,
                    cast('$[*] ? (@.name == "fundamentals").score', JSONPATH),
                ),
                String,
            ),
            "null",
        ),
        Numeric,
    )

    sort_columns: dict[SortKey, Any] = {
        "symbol": Instrument.symbol,
        "company_name": Instrument.company_name,
        "sector": Instrument.sector,
        "score": latest_scores.c.score,
        "fundamental_score": fund_score_expr,
        "is_multibagger": Instrument.symbol.in_(multibagger_symbols),
        "momentum_pass": latest_momentum.c.passed,
        "is_vcp_setup": latest_vcp.c.is_vcp_setup,
        "distance_from_52w_high_pct": latest_momentum.c.distance_from_52w_high_pct,

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
        "tv_momentum_flag": Instrument.symbol,
        "analyst_recommendation": case(
            (AnalystEstimate.recommendation_key.in_(("strong_buy", "STRONG_BUY")), 4),
            (AnalystEstimate.recommendation_key.in_(("buy", "BUY")), 3),
            (AnalystEstimate.recommendation_key.in_(("sell", "SELL")), 2),
            (AnalystEstimate.recommendation_key.in_(("strong_sell", "STRONG_SELL")), 1),
            else_=None,
        ),
        "fii_current": latest_holdings.c.fii_current,
        "fii_change_qoq_pct": latest_holdings.c.fii_qoq_change,
    }
    sort_column = sort_columns[sort]
    direction = sort_column.desc() if order == "desc" else sort_column.asc()

    if sort in ("score", "fundamental_score", "is_multibagger", "momentum_pass", "is_vcp_setup", "distance_from_52w_high_pct", "analyst_upside_pct", "analyst_recommendation", "day_change_pct", "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "return_1y_pct", "revenue_growth_yoy", "pat_growth_yoy", "ml_forecast_5d_pct", "fii_current", "fii_change_qoq_pct"):
        # Nulls always sort last, in either direction (see docstring above).
        stmt = stmt.order_by(nulls_last(direction), Instrument.symbol.asc())
    else:
        stmt = stmt.order_by(direction, Instrument.symbol.asc())

    result = await session.execute(stmt)
    rows = result.all()
    from packages.market_data.tradingview_signals import get_universe_tradingview_signals
    tv_signals_map = await get_universe_tradingview_signals()

    summaries: list[InstrumentSummary] = []
    for (
        instrument,
        score,
        confidence,
        components,
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
        fii_current,
        fii_change_qoq_pct,
    ) in rows:
        score_value = float(score) if score is not None else None
        fundamental_score = None
        if components and isinstance(components, list):
            for comp in components:
                if comp.get("name") == "fundamentals":
                    f_val = comp.get("score")
                    fundamental_score = round(float(f_val), 1) if f_val is not None else None
                    break
        fundamental_band = score_band(fundamental_score) if fundamental_score is not None else None
        is_mb = (instrument.symbol in multibagger_symbols) if multibagger_symbols is not None else False
        tv_info = tv_signals_map.get(instrument.symbol.upper(), {})
        analyst_rec = analyst_recommendation or tv_info.get("tv_analyst_rating")
        if analyst_rec:
            analyst_rec = analyst_rec.upper()
        sym_upper = instrument.symbol.upper()
        is_bo = sym_upper in breakout_map
        dist_high_val = breakout_map[sym_upper] if is_bo else (float(distance_from_high) if distance_from_high is not None else None)
        summaries.append(
            InstrumentSummary(
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                company_name=instrument.company_name,
                logo_url=instrument.logo_url,
                sector=instrument.sector,
                instrument_type=instrument.instrument_type,
                active=instrument.active,
                score=score_value,
                confidence=float(confidence) if confidence is not None else None,
                band=score_band(score_value) if score_value is not None else None,
                fundamental_score=fundamental_score,
                fundamental_band=fundamental_band,
                is_multibagger=is_mb,
                momentum_pass=bool(passed) if passed is not None else None,
                is_vcp_setup=bool(is_vcp_setup) if is_vcp_setup is not None else None,
                is_52w_breakout=is_bo,
                distance_from_52w_high_pct=dist_high_val,
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
                analyst_recommendation=analyst_rec,
                tv_signal_1d=tv_info.get("tv_signal_1d"),
                tv_signal_1w=tv_info.get("tv_signal_1w"),
                tv_momentum_flag=tv_info.get("tv_momentum_flag"),
                fii_current=float(fii_current) if fii_current is not None else None,
                fii_change_qoq_pct=float(fii_change_qoq_pct) if fii_change_qoq_pct is not None else None,
            )
        )

    if sort == "tv_momentum_flag":
        rank_order = {
            "STRONG_BUY_BOTH": 6,
            "STRONG_BUY_1D": 5,
            "STRONG_BUY_1W": 4,
            "STRONG_SELL_1W": -4,
            "STRONG_SELL_1D": -5,
            "STRONG_SELL_BOTH": -6,
        }
        summaries.sort(
            key=lambda x: (
                x.tv_momentum_flag is None or rank_order.get(x.tv_momentum_flag, 0) == 0,
                -rank_order.get(x.tv_momentum_flag, 0) if order == "desc" else rank_order.get(x.tv_momentum_flag, 0),
                x.symbol,
            ),
        )
    elif sort == "analyst_recommendation":
        rec_rank = {
            "STRONG_BUY": 4,
            "BUY": 3,
            "SELL": 2,
            "STRONG_SELL": 1,
        }
        summaries.sort(
            key=lambda x: (
                x.analyst_recommendation is None,
                -rec_rank.get(x.analyst_recommendation, 0) if order == "desc" else rec_rank.get(x.analyst_recommendation, 0),
                x.symbol,
            ),
        )
    elif sort == "distance_from_52w_high_pct":
        summaries.sort(
            key=lambda x: (
                x.distance_from_52w_high_pct is None,
                -x.distance_from_52w_high_pct if order == "desc" else x.distance_from_52w_high_pct,
                x.symbol,
            ),
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

    from packages.market_data.tradingview_signals import get_universe_tradingview_signals
    tv_signals_map = await get_universe_tradingview_signals()
    tv_info = tv_signals_map.get(instrument.symbol, {})

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
        tv_signal_1d=tv_info.get("tv_signal_1d"),
        tv_signal_1w=tv_info.get("tv_signal_1w"),
        tv_momentum_flag=tv_info.get("tv_momentum_flag"),
    )
