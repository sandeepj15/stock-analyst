"""Tests for packages/analytics/price_structure.py against hand-computable reference values."""
from __future__ import annotations

import pandas as pd
import pytest

from packages.analytics.price_structure import (
    breakdown,
    breakout,
    distance_from_high_pct,
    distance_from_low_pct,
    fifty_two_week_high,
    fifty_two_week_low,
)


def test_fifty_two_week_high_low_matches_rolling_extremes():
    close = pd.Series([100.0, 110.0, 90.0, 120.0, 80.0])
    high = fifty_two_week_high(close, window=3)
    low = fifty_two_week_low(close, window=3)

    # index 4: window = [120, 80] + wait window=3 -> rows[2:5] = [90,120,80]
    assert high.iloc[4] == pytest.approx(120.0)
    assert low.iloc[4] == pytest.approx(80.0)
    # index 0: window of 1 -> itself
    assert high.iloc[0] == pytest.approx(100.0)
    assert low.iloc[0] == pytest.approx(100.0)


def test_distance_from_high_and_low_pct():
    close = pd.Series([90.0])
    high = pd.Series([100.0])
    low = pd.Series([80.0])

    assert distance_from_high_pct(close, high).iloc[0] == pytest.approx(-10.0)
    assert distance_from_low_pct(close, low).iloc[0] == pytest.approx(12.5)


def test_distance_from_high_is_never_positive_when_high_is_the_rolling_max():
    close = pd.Series([100, 105, 95, 110, 90, 115], dtype=float)
    high = fifty_two_week_high(close, window=6)
    dist = distance_from_high_pct(close, high)
    assert (dist <= 1e-9).all()


def test_breakout_detects_new_high_vs_prior_window_only():
    close = pd.Series([10.0, 12.0, 11.0, 9.0, 15.0])
    result = breakout(close, window=3)
    # index4: prior window = rows[1:4] = [12,11,9], max=12; close=15 > 12 -> True
    assert bool(result.iloc[4]) is True
    # index1: prior window would need 3 preceding values -> not enough data -> False (NaN comparison)
    assert bool(result.iloc[1]) is False


def test_breakout_excludes_todays_own_bar_from_threshold():
    """A day that is itself the highest value in its own naive N-day window
    must not count as a breakout against *itself* - the comparison window
    must be the prior N days only.
    """
    close = pd.Series([10.0, 10.0, 10.0, 50.0])  # day3 is a huge new high
    result = breakout(close, window=3)
    assert bool(result.iloc[3]) is True  # 50 > max(10,10,10)
    # but a flat run should never flag a breakout against itself
    flat = pd.Series([10.0, 10.0, 10.0, 10.0, 10.0])
    flat_result = breakout(flat, window=3)
    assert not flat_result.iloc[3]


def test_breakdown_matches_definition():
    close = pd.Series([10.0, 9.0, 11.0, 12.0, 2.0])
    result = breakdown(close, window=3)
    # index4: prior window = rows[1:4] = [9,11,12], min=9; close=2 < 9 -> True
    assert bool(result.iloc[4]) is True
