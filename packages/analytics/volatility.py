"""Volatility indicators (SPEC.md section 14): ATR, Bollinger Bands, rolling volatility."""
from __future__ import annotations

import numpy as np
import pandas as pd

from packages.analytics.returns import log_returns
from packages.analytics.trend import true_range, wilder_smooth


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing (see `trend._wilder_smooth`).

    Wilder introduced ATR and defined this exact recursive smoothing for
    it in 1978; using a plain SMA of true range instead would understate
    how most charting platforms compute "ATR(14)".
    """
    tr = true_range(high, low, close)
    return wilder_smooth(tr, window)


def bollinger_bands(
    close: pd.Series, window: int = 20, num_std: int = 2
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands. Returns `(upper, mid, lower)`.

    `mid = SMA(close, window)`, `upper/lower = mid +/- num_std * rolling_std`.
    `rolling_std` uses `ddof=0` (population std, the standard Bollinger
    Band convention) rather than pandas' default `ddof=1` sample std.
    By construction `upper >= mid >= lower` everywhere `mid` is defined.
    """
    mid = close.rolling(window=window, min_periods=window).mean()
    std = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def rolling_volatility(close: pd.Series, window: int) -> pd.Series:
    """Annualized rolling volatility: `std(log_returns, window) * sqrt(252)`.

    252 is the standard trading-day-per-year convention. Always >= 0.
    """
    returns = log_returns(close)
    return returns.rolling(window=window, min_periods=window).std(ddof=0) * np.sqrt(252)
