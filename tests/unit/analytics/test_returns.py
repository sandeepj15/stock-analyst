"""Tests for packages/analytics/returns.py against hand-computable reference values."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from packages.analytics.returns import (
    cagr,
    drawdown_series,
    log_returns,
    max_drawdown,
    simple_returns,
)


def test_simple_returns_matches_definition():
    close = pd.Series([100.0, 110.0, 99.0])
    result = simple_returns(close)
    assert result.iloc[0] != result.iloc[0]  # NaN
    assert result.iloc[1] == pytest.approx(0.10)
    assert result.iloc[2] == pytest.approx(99.0 / 110.0 - 1.0)


def test_log_returns_matches_definition():
    close = pd.Series([100.0, 110.0, 121.0])
    result = log_returns(close)
    assert result.iloc[1] == pytest.approx(math.log(1.10))
    assert result.iloc[2] == pytest.approx(math.log(1.10))


def test_cagr_known_doubling_in_one_year():
    """A series that exactly doubles over 252 trading days has CAGR == 1.0 (100%)."""
    close = pd.Series([100.0 * (2.0 ** (i / 252)) for i in range(253)])
    result = cagr(close, periods_per_year=252)
    assert result == pytest.approx(1.0, rel=1e-6)


def test_cagr_flat_series_is_zero():
    close = pd.Series([100.0] * 10)
    assert cagr(close) == pytest.approx(0.0)


def test_drawdown_series_is_always_non_positive():
    close = pd.Series([100, 110, 90, 95, 120, 80, 130], dtype=float)
    dd = drawdown_series(close)
    assert (dd <= 1e-9).all()


def test_drawdown_series_known_values():
    close = pd.Series([100.0, 120.0, 90.0, 110.0])
    dd = drawdown_series(close)
    assert dd.iloc[0] == pytest.approx(0.0)
    assert dd.iloc[1] == pytest.approx(0.0)  # new high
    assert dd.iloc[2] == pytest.approx(90.0 / 120.0 - 1.0)
    assert dd.iloc[3] == pytest.approx(110.0 / 120.0 - 1.0)


def test_max_drawdown_known_value():
    close = pd.Series([100.0, 120.0, 90.0, 110.0, 60.0, 200.0])
    # worst drawdown: peak 120 -> trough 60 = 60/120 - 1 = -0.5
    assert max_drawdown(close) == pytest.approx(-0.5)


def test_max_drawdown_is_always_non_positive():
    close = pd.Series([100, 90, 80, 70, 60, 120, 50, 200, 10], dtype=float)
    assert max_drawdown(close) <= 0


def test_max_drawdown_zero_for_non_decreasing_series():
    close = pd.Series([100.0, 101.0, 105.0, 110.0, 110.0, 115.0])
    assert max_drawdown(close) == pytest.approx(0.0)
