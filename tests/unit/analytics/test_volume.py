"""Tests for packages/analytics/volume.py against hand-computable reference values."""
from __future__ import annotations

import pandas as pd
import pytest

from packages.analytics.volume import obv, relative_volume, volume_sma


def test_volume_sma_matches_hand_computed_average():
    volume = pd.Series([100, 200, 300, 400, 500], dtype=float)
    result = volume_sma(volume, window=2)
    assert result.iloc[1] == pytest.approx(150.0)
    assert result.iloc[4] == pytest.approx(450.0)


def test_relative_volume_matches_definition():
    volume = pd.Series([100, 100, 100, 300], dtype=float)
    result = relative_volume(volume, window=3)
    # avg of [100,100,300] trailing window of size 3 ending at index3 is (100+100+300)/3 = 166.67
    assert result.iloc[3] == pytest.approx(300.0 / ((100 + 100 + 300) / 3))


def test_relative_volume_above_one_means_above_average():
    volume = pd.Series([100, 100, 100, 100, 500], dtype=float)
    result = relative_volume(volume, window=4)
    assert result.iloc[4] > 1.0


def test_obv_matches_manual_cumulative_sum():
    close = pd.Series([10.0, 11.0, 10.5, 10.5, 12.0])
    volume = pd.Series([1000, 1500, 1200, 800, 2000], dtype=float)

    # day0: base (0), day1: up -> +1500, day2: down -> -1200, day3: flat -> +0, day4: up -> +2000
    expected = [0.0, 1500.0, 300.0, 300.0, 2300.0]
    result = obv(close, volume)
    for i, exp in enumerate(expected):
        assert result.iloc[i] == pytest.approx(exp), f"mismatch at {i}"
