"""Property tests (SPEC.md section 64): invariants that must hold for ANY
reasonable input, not just one hand-picked example.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from packages.analytics.momentum import rsi, stochastic
from packages.analytics.returns import drawdown_series, max_drawdown
from packages.analytics.volatility import bollinger_bands, rolling_volatility

rng = np.random.default_rng(7)


def _random_walk_price(n: int, start: float = 100.0) -> pd.Series:
    steps = rng.normal(0, 1.5, n)
    return pd.Series(start + np.cumsum(steps)).clip(lower=1.0)


@pytest.mark.parametrize("seed", range(5))
def test_max_drawdown_always_non_positive(seed):
    local_rng = np.random.default_rng(seed)
    close = pd.Series(100.0 + np.cumsum(local_rng.normal(0, 2, 150)))
    assert max_drawdown(close) <= 0


@pytest.mark.parametrize("seed", range(5))
def test_drawdown_series_always_non_positive(seed):
    local_rng = np.random.default_rng(seed)
    close = pd.Series(100.0 + np.cumsum(local_rng.normal(0, 2, 150))).clip(lower=1.0)
    dd = drawdown_series(close)
    assert (dd <= 1e-9).all()


@pytest.mark.parametrize("seed", range(5))
def test_rsi_always_in_0_100(seed):
    local_rng = np.random.default_rng(seed)
    close = pd.Series(100.0 + np.cumsum(local_rng.normal(0, 2, 100))).clip(lower=1.0)
    result = rsi(close, window=14).dropna()
    assert (result >= 0).all()
    assert (result <= 100).all()


@pytest.mark.parametrize("seed", range(5))
def test_stochastic_always_in_0_100(seed):
    local_rng = np.random.default_rng(seed)
    close = pd.Series(100.0 + np.cumsum(local_rng.normal(0, 2, 100))).clip(lower=1.0)
    high = close + local_rng.uniform(0.1, 2.0, 100)
    low = close - local_rng.uniform(0.1, 2.0, 100)
    k, d = stochastic(high, low, close)
    assert (k.dropna() >= 0).all() and (k.dropna() <= 100).all()
    assert (d.dropna() >= 0).all() and (d.dropna() <= 100).all()


@pytest.mark.parametrize("seed", range(5))
def test_bollinger_upper_ge_mid_ge_lower(seed):
    local_rng = np.random.default_rng(seed)
    close = pd.Series(100.0 + np.cumsum(local_rng.normal(0, 2, 100))).clip(lower=1.0)
    upper, mid, lower = bollinger_bands(close)
    valid = upper.notna() & mid.notna() & lower.notna()
    assert (upper[valid] >= mid[valid] - 1e-9).all()
    assert (mid[valid] >= lower[valid] - 1e-9).all()


@pytest.mark.parametrize("seed", range(5))
def test_rolling_volatility_never_negative(seed):
    local_rng = np.random.default_rng(seed)
    close = pd.Series(100.0 + np.cumsum(local_rng.normal(0, 2, 100))).clip(lower=1.0)
    vol = rolling_volatility(close, window=20).dropna()
    assert (vol >= 0).all()
