"""Stock research endpoints: price series, technicals, relative strength.

SPEC.md sections 14 (indicator engine), 16 (sector relative strength -
simplified, see `_SectorPeers` below), 48/49 (API design/response
contract). This is new API surface defined by this build phase - the
response shapes are documented inline on each route and in
`docs/data_dictionary/technicals_api.md`.

No authentication/tenant isolation here, same rationale as
`apps/api/routes/instruments.py`: this only exposes public reference
data (OHLCV + deterministic calculations over it), never user-owned data.
"""
from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import InstrumentNotFoundError, resolve_instrument
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.indicators import IndicatorSnapshot, compute_indicator_series, compute_indicator_snapshot
from packages.market_data.history import load_ohlcv_dataframe
from packages.market_data.relative_strength import compute_relative_strength
from packages.fundamentals.health import FinancialHealthResult
from packages.fundamentals.shareholding_flow import ShareholdingFlowResult
from packages.market_data.technicals_health import TechnicalHealthResult

router = APIRouter(prefix="/api/v1/stocks", tags=["stocks"])

RangeKey = Literal["1M", "3M", "6M", "1Y", "2Y", "ALL"]

# Calendar days to look back from the *latest available bar* (not "today" -
# the seeded dataset is a frozen ~2 year window, so anchoring to wall-clock
# "today" would make every range selector silently clip to nothing once the
# data goes stale). ALL = no lower bound.
RANGE_CALENDAR_DAYS: dict[str, int | None] = {
    "1M": 30,
    "3M": 90,
    "6M": 182,
    "1Y": 365,
    "2Y": 730,
    "ALL": None,
}

STALE_AFTER_DAYS = 5  # see DataFreshness.stale docstring


class DataFreshness(BaseModel):
    """How current the underlying OHLCV data is, as of the time of the request.

    `stale` is a simple heuristic (`data_age_days > 5`, i.e. more than a
    long weekend has passed with no new bar) - it does not know the NSE
    holiday calendar, so it may occasionally flag freshly-ingested data
    around a multi-day holiday as stale. That is a conservative failure
    mode (never silently claims fresher data than it has - SPEC.md
    section 81 rule 8).
    """

    latest_trading_date: str | None
    as_of: str
    data_age_days: int | None
    stale: bool


class PriceBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int


class PriceResponse(BaseModel):
    symbol: str
    exchange: str
    company_name: str | None = None
    logo_url: str | None = None
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    ai_summary: str | None = None
    key_points: str | None = None
    website_url: str | None = None
    range: RangeKey
    start_date: str | None
    end_date: str | None
    bars: list[PriceBar]
    data_freshness: DataFreshness
    high_52w: float | None = None
    low_52w: float | None = None
    is_52w_breakout: bool = False
    breakout_pct: float | None = None


class IndicatorSeriesOut(BaseModel):
    """Time-aligned indicator series for chart overlays (SPEC.md section 52).

    Only the series a chart actually overlays (price-chart EMAs, RSI
    sub-panel, MACD sub-panel). Every other indicator's *current* value
    is in `TechnicalsResponse.snapshot` - re-sending every series as a
    full time series would bloat the payload for values the UI only
    ever shows "as of today" (e.g. ADX, Bollinger, 52w high).
    """

    dates: list[str]
    close: list[float]
    volume: list[int]
    ema_20: list[float | None]
    ema_50: list[float | None]
    ema_200: list[float | None]
    rsi_14: list[float | None]
    macd_line: list[float | None]
    macd_signal: list[float | None]
    macd_histogram: list[float | None]


class TechnicalsResponse(BaseModel):
    symbol: str
    exchange: str
    range: RangeKey
    as_of_date: str
    snapshot: IndicatorSnapshot
    series: IndicatorSeriesOut
    data_freshness: DataFreshness
    tv_signal_1d: str | None = None
    tv_signal_1w: str | None = None
    tv_momentum_flag: str | None = None


class RelativeStrengthHorizon(BaseModel):
    stock_return_pct: float | None
    peer_avg_return_pct: float | None
    relative_strength_pct: float | None
    reason: str | None


class RelativeStrengthResponse(BaseModel):
    symbol: str
    exchange: str
    sector: str | None
    peer_universe: Literal["seeded_sector_peers"]
    peer_count: int
    peer_symbols: list[str]
    as_of_date: str | None
    metrics: dict[str, RelativeStrengthHorizon]
    data_freshness: DataFreshness


def _data_freshness(df: pd.DataFrame) -> DataFreshness:
    now = datetime.now(UTC)
    if df.empty:
        return DataFreshness(latest_trading_date=None, as_of=now.isoformat(), data_age_days=None, stale=True)

    latest: date = df["trading_date"].iloc[-1]
    age_days = (now.date() - latest).days
    return DataFreshness(
        latest_trading_date=latest.isoformat(),
        as_of=now.isoformat(),
        data_age_days=age_days,
        stale=age_days > STALE_AFTER_DAYS,
    )


def _slice_to_range(df: pd.DataFrame, range_key: str) -> pd.DataFrame:
    """Filter to the trailing window, preserving the original index.

    The index is deliberately *not* reset: `get_technicals` cross-references
    a sliced indicator-series row back into `full_df` by index (to pull
    the matching `volume`), which only works if the index is preserved.
    """
    calendar_days = RANGE_CALENDAR_DAYS[range_key]
    if calendar_days is None or df.empty:
        return df
    latest: date = df["trading_date"].iloc[-1]
    start = latest - timedelta(days=calendar_days)
    return df[df["trading_date"] >= start]


def _none_if_nan(value: float) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


async def _load_history_or_422(session: AsyncSession, instrument: Instrument) -> pd.DataFrame:
    df = await load_ohlcv_dataframe(session, instrument.id)
    if df.empty:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Instrument {instrument.exchange}:{instrument.symbol} exists but has no "
                "OHLCV data ingested yet."
            ),
        )
    return df


async def _resolve_or_404(session: AsyncSession, symbol: str, exchange: str) -> Instrument:
    try:
        return await resolve_instrument(session, symbol, exchange)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# Fast in-process L1 cache for sub-millisecond price responses
_PRICE_L1_CACHE: dict[str, tuple[float, PriceResponse]] = {}
_PRICE_L1_TTL = 120.0


@router.get("/{symbol}/price", response_model=PriceResponse)
async def get_price(
    symbol: str,
    range: RangeKey = Query(default="6M"),
    exchange: str = Query(default="NSE"),
    response: Response = None,
    session: AsyncSession = Depends(get_db_session),
) -> PriceResponse:
    """Daily OHLCV series for charting, scoped to the available seeded history.

    Multi-tier cached: L1 in-process RAM (sub-ms) -> L2 Redis (1 hr) -> OHLCV DataFrame load.
    404 if the symbol is unknown; 422 if the instrument exists but has
    zero ingested OHLCV rows (a real limitation to surface, not a 500 and
    not a silently empty-but-"successful" response - SPEC.md section 81
    rule 23).
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"

    instrument = await _resolve_or_404(session, symbol, exchange)
    l1_key = f"{instrument.id}:{range}"
    now_ts = time.time()
    if l1_key in _PRICE_L1_CACHE:
        cached_time, cached_price = _PRICE_L1_CACHE[l1_key]
        if now_ts - cached_time < _PRICE_L1_TTL:
            return cached_price

    from packages.common import cache
    cache_key = f"stock_price:v2:{instrument.id}:{range}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        try:
            res = PriceResponse.model_validate(cached)
            _PRICE_L1_CACHE[l1_key] = (now_ts, res)
            return res
        except Exception:
            pass

    full_df = await _load_history_or_422(session, instrument)
    windowed = _slice_to_range(full_df, range)

    trailing_252 = full_df.tail(252) if not full_df.empty else None
    high_52w = round(float(trailing_252["high"].max()), 2) if trailing_252 is not None and not trailing_252.empty else None
    low_52w = round(float(trailing_252["low"].min()), 2) if trailing_252 is not None and not trailing_252.empty else None

    # Calculate 52-week closing breakout strictly:
    # Latest close must be strictly greater than the maximum high of the prior trailing 52 weeks (excluding latest day)
    is_52w_breakout = False
    breakout_pct = None
    if len(full_df) >= 2:
        latest_close = float(full_df.iloc[-1]["close"])
        prior_252 = full_df.iloc[:-1].tail(252)
        if not prior_252.empty:
            prior_high = float(prior_252["high"].max())
            if latest_close > prior_high and prior_high > 0:
                is_52w_breakout = True
                breakout_pct = round(((latest_close - prior_high) / prior_high) * 100.0, 2)

    bars = [
        PriceBar(
            date=row.trading_date.isoformat(),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            adjusted_close=row.adjusted_close,
            volume=int(row.volume),
        )
        for row in windowed.itertuples()
    ]

    resp = PriceResponse(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        company_name=instrument.company_name,
        logo_url=instrument.logo_url,
        sector=instrument.sector,
        industry=instrument.industry,
        description=instrument.description,
        ai_summary=instrument.ai_summary,
        key_points=instrument.key_points,
        website_url=instrument.website_url,
        range=range,
        start_date=windowed["trading_date"].iloc[0].isoformat() if not windowed.empty else None,
        end_date=windowed["trading_date"].iloc[-1].isoformat() if not windowed.empty else None,
        bars=bars,
        data_freshness=_data_freshness(full_df),
        high_52w=high_52w,
        low_52w=low_52w,
        is_52w_breakout=is_52w_breakout,
        breakout_pct=breakout_pct,
    )
    _PRICE_L1_CACHE[l1_key] = (now_ts, resp)
    await cache.set_json(cache_key, resp.model_dump(mode="json"), ttl_seconds=3600)
    return resp


@router.get("/{symbol}/technicals", response_model=TechnicalsResponse)
async def get_technicals(
    symbol: str,
    range: RangeKey = Query(default="6M"),
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> TechnicalsResponse:
    """Latest indicator snapshot + time-aligned indicator series for charting.

    Indicators are always computed over the instrument's *full* history
    (so e.g. SMA200 is never short-changed by a 1M chart range), and only
    the resulting series is sliced to `range` afterwards - see
    `packages.indicators.snapshot.compute_indicator_series`.
    """
    instrument = await _resolve_or_404(session, symbol, exchange)
    from packages.common import cache
    cache_key = f"stock_technicals:v2:{instrument.id}:{range}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        try:
            return TechnicalsResponse.model_validate(cached)
        except Exception:
            pass

    full_df = await _load_history_or_422(session, instrument)

    snapshot = compute_indicator_snapshot(full_df)
    full_series = compute_indicator_series(full_df)
    windowed = _slice_to_range(full_series, range)

    series_out = IndicatorSeriesOut(
        dates=[d.isoformat() for d in windowed["trading_date"]],
        close=[float(v) for v in windowed["close"]],
        volume=[int(v) for v in full_df.loc[windowed.index, "volume"]],
        ema_20=[_none_if_nan(v) for v in windowed["ema_20"]],
        ema_50=[_none_if_nan(v) for v in windowed["ema_50"]],
        ema_200=[_none_if_nan(v) for v in windowed["ema_200"]],
        rsi_14=[_none_if_nan(v) for v in windowed["rsi_14"]],
        macd_line=[_none_if_nan(v) for v in windowed["macd_line"]],
        macd_signal=[_none_if_nan(v) for v in windowed["macd_signal"]],
        macd_histogram=[_none_if_nan(v) for v in windowed["macd_histogram"]],
    )

    from packages.market_data.tradingview_signals import get_single_tradingview_signal
    tv_info = await get_single_tradingview_signal(instrument.symbol)

    resp = TechnicalsResponse(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        range=range,
        as_of_date=snapshot.as_of_date.isoformat(),
        snapshot=snapshot,
        series=series_out,
        data_freshness=_data_freshness(full_df),
        tv_signal_1d=tv_info.get("tv_signal_1d"),
        tv_signal_1w=tv_info.get("tv_signal_1w"),
        tv_momentum_flag=tv_info.get("tv_momentum_flag"),
    )
    await cache.set_json(cache_key, resp.model_dump(mode="json"), ttl_seconds=300)
    return resp


@router.get("/{symbol}/relative-strength", response_model=RelativeStrengthResponse)
async def get_relative_strength(
    symbol: str,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> RelativeStrengthResponse:
    """Simplified sector relative strength (SPEC.md section 16, scoped down).

    This is **not** a real sector index - the "sector return" here is the
    simple average return of other seeded instruments sharing the same
    `Instrument.sector`, which is only the ~117-instrument dev universe,
    not the real market. `peer_universe: "seeded_sector_peers"` is always
    present in the response so this is never mistaken for a licensed
    sector benchmark. If the sector has fewer than 2 other members in the
    seeded set, every horizon's comparison fields are `null` with
    `reason: "insufficient_peer_universe"` - never a fabricated
    comparison (SPEC.md sections 2.3, 21, 81 rule 23).

    The computation itself lives in
    `packages.market_data.relative_strength.compute_relative_strength` -
    this route is a thin adapter so the Research Score engine
    (`packages/scoring`) can reuse the exact same logic (SPEC.md Phase 3).
    """
    instrument = await _resolve_or_404(session, symbol, exchange)
    await _load_history_or_422(session, instrument)
    result = await compute_relative_strength(session, instrument)

    metrics = {
        horizon: RelativeStrengthHorizon(
            stock_return_pct=m.stock_return_pct,
            peer_avg_return_pct=m.peer_avg_return_pct,
            relative_strength_pct=m.relative_strength_pct,
            reason=m.reason,
        )
        for horizon, m in result.metrics.items()
    }

    return RelativeStrengthResponse(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        sector=result.sector,
        peer_universe="seeded_sector_peers",
        peer_count=result.peer_count,
        peer_symbols=result.peer_symbols,
        as_of_date=result.as_of_date,
        metrics=metrics,
        data_freshness=_data_freshness(result.stock_df),
    )

class ForecastPoint(BaseModel):
    date: str
    close: float
    volume: float

class ForecastResponse(BaseModel):
    symbol: str
    model_name: str
    as_of_date: str
    horizon_days: int
    trajectory: list[ForecastPoint]
    mape: float | None
    directional_accuracy: bool | None

@router.get("/{symbol}/forecast", response_model=ForecastResponse)
async def get_forecast(
    symbol: str,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> ForecastResponse:
    """Retrieve the latest ML projection for this instrument."""
    from sqlalchemy import select
    from packages.common.models import MLForecast
    
    instrument = await _resolve_or_404(session, symbol, exchange)
    
    query = select(MLForecast).where(MLForecast.instrument_id == instrument.id).order_by(MLForecast.created_at.desc()).limit(1)
    result = await session.execute(query)
    forecast = result.scalar_one_or_none()
    
    if not forecast:
        raise HTTPException(status_code=404, detail="No ML forecast available for this instrument.")
        
    # The dictionary trajectory has 'date', 'close', 'volume'
    # Wait, in jobs.py: it inserted timestamps, not date. 
    # Let me check what jobs.py inserted.
    return ForecastResponse(
        symbol=instrument.symbol,
        model_name=forecast.model_name,
        as_of_date=forecast.as_of_date.isoformat(),
        horizon_days=forecast.horizon_days,
        trajectory=[
            ForecastPoint(
                date=pt.get("timestamps", pt.get("date", str(pt.get("timestamps")))),
                close=pt["close"],
                volume=pt["volume"]
            ) 
            for pt in forecast.trajectory
        ],
        mape=forecast.mape,
        directional_accuracy=forecast.directional_accuracy,
    )


class StockDiagnosticResponse(BaseModel):
    symbol: str
    company_name: str
    financial_health: FinancialHealthResult
    shareholding_flow: ShareholdingFlowResult
    technical_health: TechnicalHealthResult


@router.get("/{symbol}/diagnostic", response_model=StockDiagnosticResponse)
async def get_stock_diagnostic(
    symbol: str,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> StockDiagnosticResponse:
    """Consolidated institutional diagnostic suite: Financial Health, Forensics, Smart Money, Technicals."""
    from packages.common import cache
    from packages.fundamentals.health import compute_financial_health_diagnostic
    from packages.fundamentals.shareholding_flow import compute_shareholding_flow
    from packages.market_data.technicals_health import compute_technical_health

    instrument = await _resolve_or_404(session, symbol, exchange)
    cache_key = f"signalforge:stock_diagnostic:{instrument.id}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        try:
            return StockDiagnosticResponse.model_validate(cached)
        except Exception:
            pass

    fin_health = await compute_financial_health_diagnostic(session, instrument.id)
    sh_flow = await compute_shareholding_flow(session, instrument.id)
    tech_health = await compute_technical_health(session, instrument.id)

    response = StockDiagnosticResponse(
        symbol=instrument.symbol,
        company_name=instrument.company_name,
        financial_health=fin_health,
        shareholding_flow=sh_flow,
        technical_health=tech_health,
    )
    await cache.set_json(cache_key, response.model_dump(mode="json"), ttl_seconds=120)
    return response


@router.get("/{symbol}/checklist")
async def get_stock_checklist(
    symbol: str,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
):
    """Detailed 6-point fundamental quality checklist for a specific instrument."""
    from packages.common import cache
    from packages.fundamentals.checklist import evaluate_single_instrument
    from sqlalchemy import text

    instrument = await _resolve_or_404(session, symbol, exchange)
    cache_key = f"signalforge:stock_checklist:{instrument.id}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        return cached

    query = text("""
        WITH latest_prices AS (
            SELECT close as latest_close
            FROM ohlcv_daily 
            WHERE instrument_id = :iid
            ORDER BY trading_date DESC
            LIMIT 1
        ),
        latest_ratios AS (
            SELECT 
                MAX(CASE WHEN metric_name = 'roce_simplified' THEN value_numeric END) as roce,
                MAX(CASE WHEN metric_name = 'roe' THEN value_numeric END) as roe,
                MAX(CASE WHEN metric_name = 'debt_to_equity' THEN value_numeric END) as debt_to_equity,
                MAX(CASE WHEN metric_name = 'revenue_growth_yoy' THEN value_numeric END) as rev_growth,
                MAX(CASE WHEN metric_name = 'pat_growth_yoy' THEN value_numeric END) as pat_growth,
                MAX(CASE WHEN metric_name = 'pe_percentile' THEN value_numeric END) as pe_percentile
            FROM (
                SELECT metric_name, value_numeric,
                       ROW_NUMBER() OVER (PARTITION BY metric_name ORDER BY observed_at DESC) as rn
                FROM evidence_items
                WHERE instrument_id = :iid AND metric_name IN ('roce_simplified', 'roe', 'debt_to_equity', 'revenue_growth_yoy', 'pat_growth_yoy', 'pe_percentile')
            ) t
            WHERE rn = 1
        ),
        latest_estimates AS (
            SELECT target_mean_price, recommendation_key
            FROM analyst_estimates
            WHERE instrument_id = :iid
            LIMIT 1
        ),
        latest_structured AS (
            SELECT data
            FROM structured_provider_data
            WHERE instrument_id = :iid
            ORDER BY parsed_at DESC
            LIMIT 1
        ),
        latest_momentum AS (
            SELECT passed as momentum_pass
            FROM momentum_scans
            WHERE instrument_id = :iid
            ORDER BY computed_at DESC
            LIMIT 1
        )
        SELECT 
            i.id,
            i.symbol,
            i.company_name,
            i.sector,
            p.latest_close,
            r.roce,
            r.roe,
            r.debt_to_equity,
            r.rev_growth,
            r.pat_growth,
            r.pe_percentile,
            e.target_mean_price,
            e.recommendation_key,
            s.data as structured_data,
            m.momentum_pass
        FROM instruments i
        LEFT JOIN latest_prices p ON TRUE
        LEFT JOIN latest_ratios r ON TRUE
        LEFT JOIN latest_estimates e ON TRUE
        LEFT JOIN latest_structured s ON TRUE
        LEFT JOIN latest_momentum m ON TRUE
        WHERE i.id = :iid;
    """)
    res = await session.execute(query, {"iid": instrument.id})
    row = res.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Instrument data not found.")

    result = evaluate_single_instrument(dict(row))
    await cache.set_json(cache_key, result.model_dump(), 60)
    return result

