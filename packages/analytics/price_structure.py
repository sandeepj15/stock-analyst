"""Price-structure indicators (SPEC.md section 14): 52-week high/low,
distance from each, and breakout/breakdown detection.

`dates`/`close` are expected to be aligned (same index, ascending by
date, no gaps assumed - callers pass the instrument's full daily series
as stored).
"""
from __future__ import annotations

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def fifty_two_week_high(close: pd.Series, window: int = TRADING_DAYS_PER_YEAR) -> pd.Series:
    """Trailing 52-week (approximated as `window` trading days) rolling high.

    `min_periods=1` so an instrument with less than a year of history
    still gets a (partial-window) high rather than all-NaN - callers that
    need to know the window was incomplete should check series length
    independently.
    """
    return close.rolling(window=window, min_periods=1).max()


def fifty_two_week_low(close: pd.Series, window: int = TRADING_DAYS_PER_YEAR) -> pd.Series:
    """Trailing 52-week (approximated as `window` trading days) rolling low."""
    return close.rolling(window=window, min_periods=1).min()


def distance_from_high_pct(close: pd.Series, high: pd.Series) -> pd.Series:
    """How far `close` is below `high`, in percent (<= 0 whenever close <= high)."""
    return (close / high - 1.0) * 100.0


def distance_from_low_pct(close: pd.Series, low: pd.Series) -> pd.Series:
    """How far `close` is above `low`, in percent (>= 0 whenever close >= low)."""
    return (close / low - 1.0) * 100.0


def breakout(close: pd.Series, window: int) -> pd.Series:
    """True where `close[i]` is a new high vs. the *prior* `window` bars.

    Compares against `close[i-window : i]` (shifted by 1 so today's own
    bar never contributes to its own breakout threshold) - this is the
    look-ahead-safe way to detect "today closed above the prior N-day
    high".
    """
    prior_high = close.shift(1).rolling(window=window, min_periods=window).max()
    return close > prior_high


def breakdown(close: pd.Series, window: int) -> pd.Series:
    """True where `close[i]` is a new low vs. the *prior* `window` bars.

    See `breakout` for why the comparison window is shifted by 1.
    """
    prior_low = close.shift(1).rolling(window=window, min_periods=window).min()
    return close < prior_low
