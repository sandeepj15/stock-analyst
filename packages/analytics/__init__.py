"""SignalForge deterministic analytics package (SPEC.md section 14, Phase 2).

Pure functions over `pandas.Series`/`DataFrame` only - no I/O, no DB
access, no LLM calls (SPEC.md sections 2.2, 2.6, 81 rule 3). Every
function is unit-tested against hand-verifiable reference values in
`tests/unit/analytics/`.

`packages/indicators/` is the thin orchestration layer that turns a raw
OHLCV `DataFrame` into an `IndicatorSnapshot` using these functions - it
is the only consumer most application code should need.
"""
from __future__ import annotations

from packages.analytics.momentum import macd, roc, rsi, stochastic
from packages.analytics.price_structure import (
    breakdown,
    breakout,
    distance_from_high_pct,
    distance_from_low_pct,
    fifty_two_week_high,
    fifty_two_week_low,
)
from packages.analytics.returns import (
    cagr,
    drawdown_series,
    log_returns,
    max_drawdown,
    simple_returns,
)
from packages.analytics.trend import adx, ema, sma, true_range, wilder_smooth
from packages.analytics.volatility import atr, bollinger_bands, rolling_volatility
from packages.analytics.volume import obv, relative_volume, volume_sma

__all__ = [
    "adx",
    "atr",
    "bollinger_bands",
    "breakdown",
    "breakout",
    "cagr",
    "distance_from_high_pct",
    "distance_from_low_pct",
    "drawdown_series",
    "ema",
    "fifty_two_week_high",
    "fifty_two_week_low",
    "log_returns",
    "macd",
    "max_drawdown",
    "obv",
    "relative_volume",
    "roc",
    "rolling_volatility",
    "rsi",
    "simple_returns",
    "sma",
    "stochastic",
    "true_range",
    "volume_sma",
    "wilder_smooth",
]
