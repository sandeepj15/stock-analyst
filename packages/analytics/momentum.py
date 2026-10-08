"""Momentum indicators (SPEC.md section 14): RSI, MACD, ROC, Stochastic."""
from __future__ import annotations

import pandas as pd

from packages.analytics.trend import ema, wilder_smooth


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's original smoothing method.

    RSI has more than one common implementation (Wilder's recursive
    smoothing vs. a plain SMA of gains/losses vs. a `2/(n+1)` EMA). This
    implementation uses Wilder's method - the original 1978 definition
    and the one virtually all retail charting platforms (TradingView,
    etc.) default to - because the choice changes the numeric result and
    reproducibility requires picking one and documenting it.

    Always in [0, 100]; NaN while there are fewer than `window` prior
    changes.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = wilder_smooth(gain, window)
    avg_loss = wilder_smooth(loss, window)

    rs = avg_gain / avg_loss
    result = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss == 0 and avg_gain > 0 => RS is inf => RSI should saturate at 100.
    result = result.where(avg_loss != 0, 100.0)
    # Both avg_gain and avg_loss == 0 (flat prices) => no momentum either way; 50 is neutral.
    result = result.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return result.where(avg_gain.notna() & avg_loss.notna())


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Moving Average Convergence/Divergence.

    Returns `(macd_line, signal_line, histogram)` where
    `macd_line = EMA(close, fast) - EMA(close, slow)`,
    `signal_line = EMA(macd_line, signal)`, and
    `histogram = macd_line - signal_line`.
    """
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def roc(close: pd.Series, window: int) -> pd.Series:
    """Rate of change, in percent: `(close[i] / close[i-window] - 1) * 100`."""
    return (close / close.shift(window) - 1.0) * 100.0


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k_window: int = 14, d_window: int = 3
) -> tuple[pd.Series, pd.Series]:
    """Stochastic oscillator. Returns `(%K, %D)`, both in [0, 100].

    `%K = 100 * (close - lowest_low(k_window)) / (highest_high(k_window) - lowest_low(k_window))`.
    `%D` is the `d_window`-period SMA of `%K` (the "slow" %K, the
    conventional default on most charting platforms).
    """
    lowest_low = low.rolling(window=k_window, min_periods=k_window).min()
    highest_high = high.rolling(window=k_window, min_periods=k_window).max()
    denom = (highest_high - lowest_low).replace(0.0, pd.NA)
    percent_k = 100.0 * (close - lowest_low) / denom
    percent_k = percent_k.astype(float)
    percent_d = percent_k.rolling(window=d_window, min_periods=d_window).mean()
    return percent_k, percent_d
