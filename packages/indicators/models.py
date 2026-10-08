"""Pydantic response models for the indicator snapshot (SPEC.md section 14).

`IndicatorSnapshot` is deliberately flat (no nesting) so it serializes
directly into the API response and is trivially diffable/testable. Every
field is `float | None` (never NaN - NaN is not valid JSON) because early
in an instrument's history some windows (e.g. SMA200) are not yet
defined; `None` plus the surrounding `as_of_date`/`close` makes that
explicit instead of silently emitting `0.0` or a fabricated value
(SPEC.md section 81 rule 23).
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class IndicatorSnapshot(BaseModel):
    """Latest (as of `as_of_date`) value of every indicator in SPEC.md section 14."""

    as_of_date: date
    close: float
    adjusted_close: float

    # Trend
    sma_20: float | None
    sma_50: float | None
    sma_100: float | None
    # SMA150 (added for the Stage 2 Momentum Scanner, packages/momentum/ -
    # the "Minervini Trend Template" needs SMA150 specifically, not just
    # the 20/50/100/200 windows the rest of the app already used). Reuses
    # the same generic `sma()` function as every other window - no
    # duplicated moving-average math.
    sma_150: float | None
    sma_200: float | None
    ema_9: float | None
    ema_20: float | None
    ema_50: float | None
    ema_200: float | None
    adx_14: float | None

    # Momentum
    rsi_14: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    roc_12: float | None
    stochastic_k: float | None
    stochastic_d: float | None

    # Volatility
    atr_14: float | None
    bollinger_upper: float | None
    bollinger_mid: float | None
    bollinger_lower: float | None
    rolling_volatility_20: float | None

    # Volume
    volume_sma_20: float | None
    relative_volume_20: float | None
    obv: float | None

    # Price structure
    fifty_two_week_high: float | None
    fifty_two_week_low: float | None
    distance_from_52w_high_pct: float | None
    distance_from_52w_low_pct: float | None
    breakout_20d: bool
    breakdown_20d: bool
