"""Tests for packages/analytics/volatility.py against hand-computable reference values."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from packages.analytics.volatility import atr, bollinger_bands, rolling_volatility


def test_atr_matches_manual_wilder_recursion():
    high = pd.Series([10.0, 12.0, 11.0, 13.0, 14.0, 12.0])
    low = pd.Series([8.0, 9.0, 7.0, 10.0, 11.0, 9.0])
    close = pd.Series([9.0, 11.5, 7.5, 12.0, 13.0, 10.0])
    window = 3
    alpha = 1.0 / window

    prev_close = [None, 9.0, 11.5, 7.5, 12.0, 13.0]
    tr = []
    for i in range(len(high)):
        if prev_close[i] is None:
            tr.append(high.iloc[i] - low.iloc[i])
        else:
            tr.append(
                max(
                    high.iloc[i] - low.iloc[i],
                    abs(high.iloc[i] - prev_close[i]),
                    abs(low.iloc[i] - prev_close[i]),
                )
            )

    manual_atr = [tr[0]]
    for v in tr[1:]:
        manual_atr.append(v * alpha + manual_atr[-1] * (1 - alpha))

    result = atr(high, low, close, window=window)
    for i in range(window - 1, len(high)):
        assert result.iloc[i] == pytest.approx(manual_atr[i]), f"mismatch at {i}"
    assert result.iloc[: window - 1].isna().all()


def test_bollinger_bands_known_values():
    """20 identical values except a trailing +/- spread: mid == that value,
    std == population std of the window, upper/lower follow directly.
    """
    close = pd.Series([100.0] * 19 + [120.0])  # window=20, population std is hand-computable
    upper, mid, lower = bollinger_bands(close, window=20, num_std=2)

    mean = (100.0 * 19 + 120.0) / 20
    variance = (19 * (100.0 - mean) ** 2 + (120.0 - mean) ** 2) / 20  # ddof=0
    std = math.sqrt(variance)

    assert mid.iloc[-1] == pytest.approx(mean)
    assert upper.iloc[-1] == pytest.approx(mean + 2 * std)
    assert lower.iloc[-1] == pytest.approx(mean - 2 * std)


def test_bollinger_band_ordering_property():
    close = pd.Series([100, 102, 99, 105, 97, 110, 95, 108, 101, 103, 96, 112, 94, 115, 90,
                        120, 85, 125, 80, 130, 75, 135], dtype=float)
    upper, mid, lower = bollinger_bands(close, window=10, num_std=2)
    valid = upper.notna() & mid.notna() & lower.notna()
    assert (upper[valid] >= mid[valid]).all()
    assert (mid[valid] >= lower[valid]).all()


def test_rolling_volatility_is_never_negative():
    close = pd.Series([100, 102, 99, 105, 97, 110, 95, 108, 101, 103, 96, 112, 94, 115, 90], dtype=float)
    vol = rolling_volatility(close, window=5).dropna()
    assert (vol >= 0).all()


def test_rolling_volatility_zero_for_constant_growth_rate():
    """A series with a constant per-period log-return has zero rolling
    std of log returns, hence zero annualized volatility.
    """
    close = pd.Series([100.0 * (1.01**i) for i in range(30)])
    vol = rolling_volatility(close, window=10)
    assert vol.dropna().abs().max() < 1e-8
