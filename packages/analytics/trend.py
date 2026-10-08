"""Trend indicators (SPEC.md section 14): SMA, EMA, ADX.

No look-ahead (SPEC.md section 2.6): all rolling/exponential windows are
right-aligned (`center=False`, the pandas default) - the value at index i
is a function only of `series[: i+1]`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average over a trailing `window` of observations."""
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    """Exponential moving average with the standard `alpha = 2 / (window + 1)`.

    `adjust=False` is used so each value is the classic recursive
    `EMA[i] = price[i] * alpha + EMA[i-1] * (1 - alpha)` form (matching
    every textbook/TradingView definition) rather than pandas' default
    weighted-average-of-all-history form, which would differ for short
    series. The first `window - 1` values are backed by fewer than
    `window` observations (pandas starts the recursion from the first
    data point); callers that need a stricter warm-up can mask the first
    `window - 1` values themselves.
    """
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True range: `max(high-low, |high-prev_close|, |low-prev_close|)`.

    Shared by ATR and ADX (both volatility/trend indicators built on it) -
    exported (not module-private) so `volatility.py` can reuse it instead
    of duplicating the formula.
    """
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def wilder_smooth(series: pd.Series, window: int) -> pd.Series:
    """Wilder's smoothing: an EMA with `alpha = 1/window`, `adjust=False`.

    This is the recursive smoothing method J. Welles Wilder defined for
    ATR/ADX/RSI in "New Concepts in Technical Trading Systems" (1978) -
    not a plain SMA and not a standard `alpha = 2/(n+1)` EMA. The choice
    matters: using a different smoothing method produces materially
    different values for the same nominal "14-period" indicator.
    """
    return series.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average Directional Index (Wilder's smoothing, see `_wilder_smooth`).

    Measures trend *strength* (not direction) on a 0-100 scale.
    """
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = true_range(high, low, close)
    smoothed_tr = wilder_smooth(tr, window)
    smoothed_plus_dm = wilder_smooth(plus_dm, window)
    smoothed_minus_dm = wilder_smooth(minus_dm, window)

    plus_di = 100.0 * (smoothed_plus_dm / smoothed_tr)
    minus_di = 100.0 * (smoothed_minus_dm / smoothed_tr)

    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.replace(0.0, np.nan)

    return wilder_smooth(dx, window)
