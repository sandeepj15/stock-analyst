"""Tests for packages/analytics/momentum.py against hand-computable reference values."""
from __future__ import annotations

import pandas as pd
import pytest

from packages.analytics.momentum import macd, roc, rsi, stochastic


def test_rsi_strictly_increasing_series_is_100():
    """No losses at all over the window => avg_loss == 0 => RSI == 100
    (a provable edge case of the Wilder RSI formula, not an arbitrary number).
    """
    close = pd.Series([100.0 + i for i in range(30)])
    result = rsi(close, window=14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_strictly_decreasing_series_is_0():
    """No gains at all over the window => avg_gain == 0 => RSI == 0."""
    close = pd.Series([200.0 - i for i in range(30)])
    result = rsi(close, window=14)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_rsi_flat_series_is_neutral_50():
    """No price movement at all => both avg_gain and avg_loss are 0; RSI
    is defined as the neutral midpoint (50) rather than NaN/division-by-zero.
    """
    close = pd.Series([100.0] * 30)
    result = rsi(close, window=14)
    assert result.iloc[-1] == pytest.approx(50.0)


def test_rsi_always_in_valid_range_for_mixed_series():
    close = pd.Series([100, 102, 101, 105, 103, 108, 107, 110, 104, 109, 111, 106, 115, 112, 118, 120])
    result = rsi(close, window=14).dropna()
    assert (result >= 0).all()
    assert (result <= 100).all()


def test_rsi_matches_manual_wilder_recursion():
    """Independent plain-python reimplementation of Wilder's RSI recursion."""
    values = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
              45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
    window = 14
    alpha = 1.0 / window

    deltas = [None] + [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0.0) if d is not None else None for d in deltas]
    losses = [max(-d, 0.0) if d is not None else None for d in deltas]

    avg_gain = [None] * len(values)
    avg_loss = [None] * len(values)
    avg_gain[1] = gains[1]
    avg_loss[1] = losses[1]
    for i in range(2, len(values)):
        avg_gain[i] = gains[i] * alpha + avg_gain[i - 1] * (1 - alpha)
        avg_loss[i] = losses[i] * alpha + avg_loss[i - 1] * (1 - alpha)

    manual_rsi = [None] * len(values)
    for i in range(1, len(values)):
        if avg_loss[i] == 0:
            manual_rsi[i] = 100.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            manual_rsi[i] = 100.0 - 100.0 / (1 + rs)

    result = rsi(pd.Series(values), window=window)
    for i in range(window, len(values)):
        assert result.iloc[i] == pytest.approx(manual_rsi[i]), f"mismatch at index {i}"


def test_macd_matches_manual_composition():
    """Use small fast/slow/signal windows so a short series can be hand-verified."""
    values = [10.0, 11.0, 12.0, 11.5, 13.0, 14.0, 13.5, 15.0]
    fast, slow, signal = 2, 3, 2

    def manual_ema(vals, window):
        alpha = 2.0 / (window + 1)
        out = [vals[0]]
        for v in vals[1:]:
            out.append(v * alpha + out[-1] * (1 - alpha))
        return out

    fast_ema = manual_ema(values, fast)
    slow_ema = manual_ema(values, slow)
    manual_macd_line = [f - s for f, s in zip(fast_ema, slow_ema, strict=True)]

    # The real macd_line is NaN until index (slow - 1) (pandas' min_periods
    # masking on the slow EMA). pandas' ewm seeds its recursion at the first
    # non-NaN entry it sees, so the signal line's recursion starts there too
    # - not at index 0 - which is what we replicate below.
    first_valid = slow - 1
    manual_signal = {first_valid: manual_macd_line[first_valid]}
    alpha = 2.0 / (signal + 1)
    for i in range(first_valid + 1, len(values)):
        manual_signal[i] = manual_macd_line[i] * alpha + manual_signal[i - 1] * (1 - alpha)

    macd_line, signal_line, histogram = macd(pd.Series(values), fast=fast, slow=slow, signal=signal)

    for i in range(slow - 1, len(values)):
        assert macd_line.iloc[i] == pytest.approx(manual_macd_line[i]), f"macd mismatch at {i}"
    for i in range(first_valid + signal - 1, len(values)):
        assert signal_line.iloc[i] == pytest.approx(manual_signal[i]), f"signal mismatch at {i}"
        assert histogram.iloc[i] == pytest.approx(manual_macd_line[i] - manual_signal[i]), f"hist mismatch at {i}"


def test_roc_matches_definition():
    close = pd.Series([100.0, 105.0, 110.0, 99.0, 120.0])
    result = roc(close, window=2)
    assert result.iloc[2] == pytest.approx((110.0 / 100.0 - 1.0) * 100.0)
    assert result.iloc[4] == pytest.approx((120.0 / 110.0 - 1.0) * 100.0)
    assert result.iloc[:2].isna().all()


def test_stochastic_matches_definition():
    high = pd.Series([10.0, 11.0, 12.0, 13.0])
    low = pd.Series([8.0, 9.0, 9.0, 10.0])
    close = pd.Series([9.0, 10.0, 11.0, 12.5])

    k, _d = stochastic(high, low, close, k_window=3, d_window=2)
    # index 2: window = rows[0:3], highest_high=12, lowest_low=8, close=11
    expected_k2 = 100.0 * (11.0 - 8.0) / (12.0 - 8.0)
    assert k.iloc[2] == pytest.approx(expected_k2)
    # index 3: window = rows[1:4], highest_high=13, lowest_low=9, close=12.5
    expected_k3 = 100.0 * (12.5 - 9.0) / (13.0 - 9.0)
    assert k.iloc[3] == pytest.approx(expected_k3)


def test_stochastic_bounds_are_0_to_100():
    high = pd.Series([float(x) for x in [10, 12, 11, 15, 14, 18, 16, 20, 19, 22]])
    low = high - 2
    close = (high + low) / 2
    k, d = stochastic(high, low, close, k_window=3, d_window=2)
    assert (k.dropna() >= 0).all() and (k.dropna() <= 100).all()
    assert (d.dropna() >= 0).all() and (d.dropna() <= 100).all()
