"""Returns, drawdown and risk-adjusted-return helpers (SPEC.md section 14).

These are pure functions over `pandas.Series` of prices (typically the
adjusted close). They are deliberately simple and reused by the
indicator engine today, and will be reused by scoring/backtesting in
later phases (SPEC.md sections 17-18, 29-33) - do not duplicate this
logic elsewhere.

No look-ahead (SPEC.md section 2.6): every function here only uses
`series[: i]` to produce `result[i]` - no `shift(-1)`, no `center=True`,
no forward fill from future rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def simple_returns(close: pd.Series) -> pd.Series:
    """Period-over-period simple return: `close[i] / close[i-1] - 1`.

    The first element is always NaN (no prior observation to compare to).
    """
    return close.pct_change()


def log_returns(close: pd.Series) -> pd.Series:
    """Period-over-period log return: `ln(close[i] / close[i-1])`.

    Log returns (not simple returns) are used for `rolling_volatility`
    because they are time-additive, which is the standard convention for
    annualizing volatility.
    """
    return np.log(close / close.shift(1))


def cagr(close: pd.Series, periods_per_year: int = 252) -> float:
    """Compound annual growth rate over the full span of `close`.

    `periods_per_year=252` is the standard trading-day convention for
    daily equity series. Returns NaN if there are fewer than 2 valid
    observations or the first value is not positive.
    """
    valid = close.dropna()
    if len(valid) < 2 or valid.iloc[0] <= 0:
        return float("nan")
    total_periods = len(valid) - 1
    if total_periods <= 0:
        return float("nan")
    growth = valid.iloc[-1] / valid.iloc[0]
    years = total_periods / periods_per_year
    if years <= 0 or growth <= 0:
        return float("nan")
    return float(growth ** (1.0 / years) - 1.0)


def drawdown_series(close: pd.Series) -> pd.Series:
    """Drawdown at each point: `close[i] / running_max(close[:i+1]) - 1`.

    Always <= 0 by construction. Uses `expanding().max()` (never
    `center=True`) so each value only reflects the running peak up to and
    including index i - no look-ahead.
    """
    running_max = close.expanding(min_periods=1).max()
    return close / running_max - 1.0


def max_drawdown(close: pd.Series) -> float:
    """The single worst (most negative) drawdown over the full series.

    Always <= 0 (0 for a strictly non-decreasing series).
    """
    dd = drawdown_series(close)
    if dd.dropna().empty:
        return float("nan")
    return float(dd.min())
