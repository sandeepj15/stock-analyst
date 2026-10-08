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

from datetime import UTC, date, datetime, timedelta
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import InstrumentNotFoundError, resolve_instrument
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.indicators import IndicatorSnapshot, compute_indicator_series, compute_indicator_snapshot
from packages.market_data.history import load_ohlcv_dataframe
from packages.market_data.relative_strength import compute_relative_strength

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
    range: RangeKey
    start_date: str | None
    end_date: str | None
    bars: list[PriceBar]
    data_freshness: DataFreshness


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


@router.get("/{symbol}/price", response_model=PriceResponse)
async def get_price(
    symbol: str,
    range: RangeKey = Query(default="6M"),
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> PriceResponse:
    """Daily OHLCV series for charting, scoped to the available seeded history.

    404 if the symbol is unknown; 422 if the instrument exists but has
    zero ingested OHLCV rows (a real limitation to surface, not a 500 and
    not a silently empty-but-"successful" response - SPEC.md section 81
    rule 23).
    """
    instrument = await _resolve_or_404(session, symbol, exchange)
    full_df = await _load_history_or_422(session, instrument)
    windowed = _slice_to_range(full_df, range)

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

    return PriceResponse(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        range=range,
        start_date=windowed["trading_date"].iloc[0].isoformat() if not windowed.empty else None,
        end_date=windowed["trading_date"].iloc[-1].isoformat() if not windowed.empty else None,
        bars=bars,
        data_freshness=_data_freshness(full_df),
    )


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

    return TechnicalsResponse(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        range=range,
        as_of_date=snapshot.as_of_date.isoformat(),
        snapshot=snapshot,
        series=series_out,
        data_freshness=_data_freshness(full_df),
    )


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
