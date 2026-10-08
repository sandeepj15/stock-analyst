"""No-look-ahead regression tests (SPEC.md section 2.6, 81 rule 9/10).

For every indicator, computing it over the full series and computing it
over a truncated prefix must agree at every index covered by the prefix.
If a function used `shift(-1)`, `center=True`, or any other
future-peeking construct, truncating the series would change the value
at index i - this test proves that doesn't happen.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from packages.analytics.momentum import macd, roc, rsi, stochastic
from packages.analytics.price_structure import (
    breakdown,
    breakout,
    distance_from_high_pct,
    fifty_two_week_high,
)
from packages.analytics.trend import adx, ema, sma
from packages.analytics.volatility import atr, bollinger_bands, rolling_volatility
from packages.analytics.volume import obv, relative_volume, volume_sma
from packages.indicators.snapshot import compute_indicator_series

rng = np.random.default_rng(42)
N = 120
_close = pd.Series(100.0 + np.cumsum(rng.normal(0, 1, N)))
_high = _close + rng.uniform(0.1, 2.0, N)
_low = _close - rng.uniform(0.1, 2.0, N)
_volume = pd.Series(rng.integers(1_000, 10_000, N).astype(float))

TRUNCATE_AT = 80  # prove index TRUNCATE_AT - 1 is identical whether or not later rows exist


def _assert_prefix_matches(full: pd.Series, truncated: pd.Series) -> None:
    full_prefix = full.iloc[:TRUNCATE_AT]
    pd.testing.assert_series_equal(full_prefix.reset_index(drop=True), truncated.reset_index(drop=True))


@pytest.mark.parametrize("window", [5, 20])
def test_sma_no_lookahead(window):
    full = sma(_close, window)
    truncated = sma(_close.iloc[:TRUNCATE_AT], window)
    _assert_prefix_matches(full, truncated)


@pytest.mark.parametrize("window", [9, 20])
def test_ema_no_lookahead(window):
    full = ema(_close, window)
    truncated = ema(_close.iloc[:TRUNCATE_AT], window)
    _assert_prefix_matches(full, truncated)


def test_rsi_no_lookahead():
    full = rsi(_close)
    truncated = rsi(_close.iloc[:TRUNCATE_AT])
    _assert_prefix_matches(full, truncated)


def test_macd_no_lookahead():
    full_line, full_sig, full_hist = macd(_close)
    trunc_line, trunc_sig, trunc_hist = macd(_close.iloc[:TRUNCATE_AT])
    _assert_prefix_matches(full_line, trunc_line)
    _assert_prefix_matches(full_sig, trunc_sig)
    _assert_prefix_matches(full_hist, trunc_hist)


def test_roc_no_lookahead():
    full = roc(_close, 10)
    truncated = roc(_close.iloc[:TRUNCATE_AT], 10)
    _assert_prefix_matches(full, truncated)


def test_stochastic_no_lookahead():
    full_k, full_d = stochastic(_high, _low, _close)
    trunc_k, trunc_d = stochastic(_high.iloc[:TRUNCATE_AT], _low.iloc[:TRUNCATE_AT], _close.iloc[:TRUNCATE_AT])
    _assert_prefix_matches(full_k, trunc_k)
    _assert_prefix_matches(full_d, trunc_d)


def test_atr_no_lookahead():
    full = atr(_high, _low, _close)
    truncated = atr(_high.iloc[:TRUNCATE_AT], _low.iloc[:TRUNCATE_AT], _close.iloc[:TRUNCATE_AT])
    _assert_prefix_matches(full, truncated)


def test_adx_no_lookahead():
    full = adx(_high, _low, _close)
    truncated = adx(_high.iloc[:TRUNCATE_AT], _low.iloc[:TRUNCATE_AT], _close.iloc[:TRUNCATE_AT])
    _assert_prefix_matches(full, truncated)


def test_bollinger_bands_no_lookahead():
    full_u, full_m, full_l = bollinger_bands(_close)
    trunc_u, trunc_m, trunc_l = bollinger_bands(_close.iloc[:TRUNCATE_AT])
    _assert_prefix_matches(full_u, trunc_u)
    _assert_prefix_matches(full_m, trunc_m)
    _assert_prefix_matches(full_l, trunc_l)


def test_rolling_volatility_no_lookahead():
    full = rolling_volatility(_close, 20)
    truncated = rolling_volatility(_close.iloc[:TRUNCATE_AT], 20)
    _assert_prefix_matches(full, truncated)


def test_volume_sma_and_relative_volume_no_lookahead():
    full_sma = volume_sma(_volume, 20)
    trunc_sma = volume_sma(_volume.iloc[:TRUNCATE_AT], 20)
    _assert_prefix_matches(full_sma, trunc_sma)

    full_rel = relative_volume(_volume, 20)
    trunc_rel = relative_volume(_volume.iloc[:TRUNCATE_AT], 20)
    _assert_prefix_matches(full_rel, trunc_rel)


def test_obv_no_lookahead():
    full = obv(_close, _volume)
    truncated = obv(_close.iloc[:TRUNCATE_AT], _volume.iloc[:TRUNCATE_AT])
    _assert_prefix_matches(full, truncated)


def test_fifty_two_week_high_and_distance_no_lookahead():
    full_high = fifty_two_week_high(_close, window=50)
    trunc_high = fifty_two_week_high(_close.iloc[:TRUNCATE_AT], window=50)
    _assert_prefix_matches(full_high, trunc_high)

    full_dist = distance_from_high_pct(_close, full_high)
    trunc_dist = distance_from_high_pct(_close.iloc[:TRUNCATE_AT], trunc_high)
    _assert_prefix_matches(full_dist, trunc_dist)


def test_breakout_breakdown_no_lookahead():
    full_bo = breakout(_close, 20)
    trunc_bo = breakout(_close.iloc[:TRUNCATE_AT], 20)
    _assert_prefix_matches(full_bo, trunc_bo)

    full_bd = breakdown(_close, 20)
    trunc_bd = breakdown(_close.iloc[:TRUNCATE_AT], 20)
    _assert_prefix_matches(full_bd, trunc_bd)


def test_full_indicator_snapshot_series_no_lookahead():
    """End-to-end: the orchestration layer's full series must also satisfy
    no-look-ahead, not just the underlying analytics functions in isolation.
    """
    dates = pd.date_range("2024-01-01", periods=N, freq="B")
    df = pd.DataFrame(
        {
            "trading_date": dates,
            "open": _close,
            "high": _high,
            "low": _low,
            "close": _close,
            "adjusted_close": _close,
            "volume": _volume,
        }
    )

    full = compute_indicator_series(df)
    truncated = compute_indicator_series(df.iloc[:TRUNCATE_AT])

    numeric_cols = [c for c in full.columns if c not in ("trading_date",)]
    for col in numeric_cols:
        full_prefix = full[col].iloc[:TRUNCATE_AT].reset_index(drop=True)
        trunc_col = truncated[col].reset_index(drop=True)
        pd.testing.assert_series_equal(full_prefix, trunc_col, check_names=False)
