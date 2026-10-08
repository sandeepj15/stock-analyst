"""Tests for packages/analytics/trend.py against hand-computable reference values."""
from __future__ import annotations

import pandas as pd
import pytest

from packages.analytics.trend import adx, ema, sma, true_range, wilder_smooth


def test_sma_matches_hand_computed_average():
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    result = sma(series, window=3)

    assert result.iloc[:2].isna().all()  # not enough data yet
    assert result.iloc[2] == pytest.approx((1 + 2 + 3) / 3)
    assert result.iloc[3] == pytest.approx((2 + 3 + 4) / 3)
    assert result.iloc[4] == pytest.approx((3 + 4 + 5) / 3)
    assert result.iloc[5] == pytest.approx((4 + 5 + 6) / 3)


def test_ema_matches_manual_recursive_formula():
    """`ema()` uses `ewm(adjust=False)`: EMA[0] = price[0], then the
    classic recursive update. Reimplement that recursion in plain python
    (independent of pandas internals) and assert they agree exactly.
    """
    values = [10.0, 20.0, 30.0, 25.0, 40.0, 35.0, 50.0]
    window = 3
    alpha = 2.0 / (window + 1)

    manual = [values[0]]
    for v in values[1:]:
        manual.append(v * alpha + manual[-1] * (1 - alpha))

    result = ema(pd.Series(values), window=window)
    # min_periods=window masks the first (window - 1) outputs.
    for i in range(window - 1, len(values)):
        assert result.iloc[i] == pytest.approx(manual[i]), f"mismatch at index {i}"
    assert result.iloc[: window - 1].isna().all()


def test_ema_known_textbook_values():
    """3-period EMA (alpha=0.5) of [10, 20, 30]: 10 -> 15 -> 22.5 (hand-computed)."""
    result = ema(pd.Series([10.0, 20.0, 30.0]), window=3)
    assert result.iloc[2] == pytest.approx(22.5)


def test_true_range_matches_definition():
    high = pd.Series([10.0, 12.0, 11.0])
    low = pd.Series([8.0, 9.0, 7.0])
    close = pd.Series([9.0, 11.5, 7.5])

    tr = true_range(high, low, close)
    # index 0: no prior close -> just high-low
    assert tr.iloc[0] == pytest.approx(2.0)
    # index 1: max(12-9, |12-9|, |9-9|) = max(3, 3, 0) = 3
    assert tr.iloc[1] == pytest.approx(3.0)
    # index 2: max(11-7, |11-11.5|, |7-11.5|) = max(4, 0.5, 4.5) = 4.5
    assert tr.iloc[2] == pytest.approx(4.5)


def test_wilder_smooth_matches_manual_recursion():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0]
    window = 3
    alpha = 1.0 / window

    manual = [values[0]]
    for v in values[1:]:
        manual.append(v * alpha + manual[-1] * (1 - alpha))

    result = wilder_smooth(pd.Series(values), window=window)
    for i in range(window - 1, len(values)):
        assert result.iloc[i] == pytest.approx(manual[i])


def test_adx_strong_uptrend_is_high():
    """A clean, consistent uptrend (no down days at all) should produce a
    high ADX (strong trend) once the smoothing window has warmed up.
    """
    n = 40
    close = pd.Series([100.0 + i * 2 for i in range(n)])
    high = close + 1.0
    low = close - 1.0

    result = adx(high, low, close, window=14)
    assert result.iloc[-1] > 50  # strong, consistent trend
    assert result.iloc[: 14 * 2 - 2].isna().all() or result.iloc[14 - 1 :].notna().any()


def test_adx_sideways_is_low():
    """A flat/oscillating-but-no-net-progress series should have a low ADX."""
    n = 60
    close = pd.Series([100.0 + (1 if i % 2 == 0 else -1) for i in range(n)])
    high = close + 0.5
    low = close - 0.5

    result = adx(high, low, close, window=14)
    assert result.iloc[-1] < 30
