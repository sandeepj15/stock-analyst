"""Tests for packages/indicators/snapshot.py (the orchestration layer)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from packages.analytics.trend import sma
from packages.indicators.models import IndicatorSnapshot
from packages.indicators.snapshot import compute_indicator_series, compute_indicator_snapshot


def _make_df(n: int = 260, start_price: float = 100.0, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = pd.Series(start_price + np.cumsum(rng.normal(0, 1, n))).clip(lower=1.0)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {
            "trading_date": dates,
            "open": close,
            "high": close + rng.uniform(0.1, 2.0, n),
            "low": close - rng.uniform(0.1, 2.0, n),
            "close": close,
            "adjusted_close": close,
            "volume": rng.integers(1_000, 50_000, n).astype(float),
        }
    )


def test_compute_indicator_snapshot_returns_pydantic_model_with_matching_latest_values():
    df = _make_df()
    snapshot = compute_indicator_snapshot(df)

    assert isinstance(snapshot, IndicatorSnapshot)
    assert snapshot.as_of_date == df["trading_date"].iloc[-1]
    assert snapshot.close == pytest.approx(float(df["close"].iloc[-1]))

    expected_sma20 = sma(df["adjusted_close"], 20).iloc[-1]
    assert snapshot.sma_20 == pytest.approx(float(expected_sma20))


def test_compute_indicator_snapshot_raises_on_empty_dataframe():
    df = _make_df()
    with pytest.raises(ValueError):
        compute_indicator_snapshot(df.iloc[:0])


def test_compute_indicator_snapshot_short_history_has_none_for_long_windows():
    """With fewer than 200 rows, SMA200/EMA200 must be None (not fabricated),
    while short-window indicators (e.g. SMA20) should already be populated.
    """
    df = _make_df(n=50)
    snapshot = compute_indicator_snapshot(df)

    assert snapshot.sma_200 is None
    assert snapshot.ema_200 is None
    assert snapshot.sma_20 is not None


def test_compute_indicator_series_matches_snapshot_latest_row():
    df = _make_df()
    series = compute_indicator_series(df)
    snapshot = compute_indicator_snapshot(df)

    assert series["sma_20"].iloc[-1] == pytest.approx(snapshot.sma_20)
    assert series["rsi_14"].iloc[-1] == pytest.approx(snapshot.rsi_14)
    assert series["macd_line"].iloc[-1] == pytest.approx(snapshot.macd_line)


def test_compute_indicator_series_requires_expected_columns():
    with pytest.raises(ValueError):
        compute_indicator_series(pd.DataFrame({"close": [1, 2, 3]}))


def test_rsi_in_bounds_and_breakout_flags_are_bool_in_snapshot():
    df = _make_df()
    snapshot = compute_indicator_snapshot(df)
    if snapshot.rsi_14 is not None:
        assert 0 <= snapshot.rsi_14 <= 100
    assert isinstance(snapshot.breakout_20d, bool)
    assert isinstance(snapshot.breakdown_20d, bool)
