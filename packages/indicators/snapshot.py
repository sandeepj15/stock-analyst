"""Indicator orchestration layer (SPEC.md section 14, Phase 2).

Thin glue between `packages/analytics` (pure math) and application code
(API routes). Takes a full OHLCV history `DataFrame` for one instrument
and returns either:

- `compute_indicator_snapshot`: today's (latest row's) value of every
  indicator, as an `IndicatorSnapshot`.
- `compute_indicator_series`: the full time-aligned indicator history, as
  a `DataFrame` - needed to plot EMA/RSI/MACD over time on the chart,
  not just today's number.

Indicators are computed on `adjusted_close` (not raw `close`) because
splits/dividends would otherwise show up as spurious price jumps in
trend/momentum math (SPEC.md section 2.8) - raw `close`/`high`/`low`
are still used for the ATR/ADX/Bollinger/stochastic range calculations
below since the dev provider's adjustment only touches the close series
(this matches the OHLCVDaily model, which does not adjust the full OHLC
bar, only `adjusted_close`).

The input `DataFrame` must be sorted ascending by `trading_date` and
contain columns: trading_date, open, high, low, close, adjusted_close,
volume. No I/O happens here - callers are responsible for loading rows
from the database.
"""
from __future__ import annotations

import math

import pandas as pd

from packages.analytics import (
    adx,
    atr,
    bollinger_bands,
    breakdown,
    breakout,
    distance_from_high_pct,
    distance_from_low_pct,
    ema,
    fifty_two_week_high,
    fifty_two_week_low,
    macd,
    obv,
    relative_volume,
    roc,
    rolling_volatility,
    rsi,
    sma,
    stochastic,
    volume_sma,
)
from packages.indicators.models import IndicatorSnapshot

REQUIRED_COLUMNS = ("trading_date", "open", "high", "low", "close", "adjusted_close", "volume")

BREAKOUT_WINDOW = 20
STOCHASTIC_K_WINDOW = 14
STOCHASTIC_D_WINDOW = 3


def _nan_to_none(value: float) -> float | None:
    """NaN is not valid JSON - every indicator value crosses this before leaving analytics."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def _require_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV DataFrame is missing required column(s): {missing}")


def compute_indicator_series(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the full time-aligned indicator history for one instrument.

    Always computed over the *entire* input `df` regardless of what date
    range the caller ultimately wants to display - slicing to a display
    window happens after this call, never before, so long-window
    indicators (e.g. SMA200) are never short-changed by a caller that
    only wants to chart the last 6 months (SPEC.md section 2.6: no
    look-ahead, but also no artificial *look-behind* truncation that
    would corrupt otherwise-valid warm-up data).
    """
    _require_columns(df)
    close = df["adjusted_close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    macd_line, macd_signal, macd_hist = macd(close)
    stoch_k, stoch_d = stochastic(high, low, close, STOCHASTIC_K_WINDOW, STOCHASTIC_D_WINDOW)
    bb_upper, bb_mid, bb_lower = bollinger_bands(close)
    high_52w = fifty_two_week_high(close)
    low_52w = fifty_two_week_low(close)

    out = pd.DataFrame(index=df.index)
    out["trading_date"] = df["trading_date"]
    out["close"] = df["close"]
    out["adjusted_close"] = close

    out["sma_20"] = sma(close, 20)
    out["sma_50"] = sma(close, 50)
    out["sma_100"] = sma(close, 100)
    out["sma_150"] = sma(close, 150)
    out["sma_200"] = sma(close, 200)
    out["ema_9"] = ema(close, 9)
    out["ema_20"] = ema(close, 20)
    out["ema_50"] = ema(close, 50)
    out["ema_200"] = ema(close, 200)
    out["adx_14"] = adx(high, low, close, 14)

    out["rsi_14"] = rsi(close, 14)
    out["macd_line"] = macd_line
    out["macd_signal"] = macd_signal
    out["macd_histogram"] = macd_hist
    out["roc_12"] = roc(close, 12)
    out["stochastic_k"] = stoch_k
    out["stochastic_d"] = stoch_d

    out["atr_14"] = atr(high, low, close, 14)
    out["bollinger_upper"] = bb_upper
    out["bollinger_mid"] = bb_mid
    out["bollinger_lower"] = bb_lower
    out["rolling_volatility_20"] = rolling_volatility(close, 20)

    out["volume_sma_20"] = volume_sma(volume, 20)
    out["relative_volume_20"] = relative_volume(volume, 20)
    out["obv"] = obv(close, volume)

    out["fifty_two_week_high"] = high_52w
    out["fifty_two_week_low"] = low_52w
    out["distance_from_52w_high_pct"] = distance_from_high_pct(close, high_52w)
    out["distance_from_52w_low_pct"] = distance_from_low_pct(close, low_52w)
    out["breakout_20d"] = breakout(close, BREAKOUT_WINDOW)
    out["breakdown_20d"] = breakdown(close, BREAKOUT_WINDOW)

    return out


def compute_indicator_snapshot(df: pd.DataFrame) -> IndicatorSnapshot:
    """Return the latest row of `compute_indicator_series` as an `IndicatorSnapshot`.

    Raises `ValueError` if `df` has no rows (callers must check for empty
    history themselves and return a clear API error rather than calling
    this - SPEC.md section 81 rule 23).
    """
    if df.empty:
        raise ValueError("Cannot compute an indicator snapshot from an empty OHLCV history")

    series = compute_indicator_series(df)
    latest = series.iloc[-1]

    return IndicatorSnapshot(
        as_of_date=latest["trading_date"],
        close=float(latest["close"]),
        adjusted_close=float(latest["adjusted_close"]),
        sma_20=_nan_to_none(latest["sma_20"]),
        sma_50=_nan_to_none(latest["sma_50"]),
        sma_100=_nan_to_none(latest["sma_100"]),
        sma_150=_nan_to_none(latest["sma_150"]),
        sma_200=_nan_to_none(latest["sma_200"]),
        ema_9=_nan_to_none(latest["ema_9"]),
        ema_20=_nan_to_none(latest["ema_20"]),
        ema_50=_nan_to_none(latest["ema_50"]),
        ema_200=_nan_to_none(latest["ema_200"]),
        adx_14=_nan_to_none(latest["adx_14"]),
        rsi_14=_nan_to_none(latest["rsi_14"]),
        macd_line=_nan_to_none(latest["macd_line"]),
        macd_signal=_nan_to_none(latest["macd_signal"]),
        macd_histogram=_nan_to_none(latest["macd_histogram"]),
        roc_12=_nan_to_none(latest["roc_12"]),
        stochastic_k=_nan_to_none(latest["stochastic_k"]),
        stochastic_d=_nan_to_none(latest["stochastic_d"]),
        atr_14=_nan_to_none(latest["atr_14"]),
        bollinger_upper=_nan_to_none(latest["bollinger_upper"]),
        bollinger_mid=_nan_to_none(latest["bollinger_mid"]),
        bollinger_lower=_nan_to_none(latest["bollinger_lower"]),
        rolling_volatility_20=_nan_to_none(latest["rolling_volatility_20"]),
        volume_sma_20=_nan_to_none(latest["volume_sma_20"]),
        relative_volume_20=_nan_to_none(latest["relative_volume_20"]),
        obv=_nan_to_none(latest["obv"]),
        fifty_two_week_high=_nan_to_none(latest["fifty_two_week_high"]),
        fifty_two_week_low=_nan_to_none(latest["fifty_two_week_low"]),
        distance_from_52w_high_pct=_nan_to_none(latest["distance_from_52w_high_pct"]),
        distance_from_52w_low_pct=_nan_to_none(latest["distance_from_52w_low_pct"]),
        breakout_20d=bool(latest["breakout_20d"]),
        breakdown_20d=bool(latest["breakdown_20d"]),
    )
