"""Tests for packages/scoring/bull_bear.py (SCORING.md "Bull case / Bear case").

Covers: direction-based bucketing, magnitude-descending sort, and that
`strength` on each `BullBearEntry` is copied straight from the
originating `Signal.strength` (never recomputed independently).
"""
from __future__ import annotations

import uuid

from packages.scoring.bull_bear import build_bull_bear_case
from packages.scoring.signals import (
    adx_signal,
    close_vs_ma_signal,
    rsi_signal,
)


def _pair(signal):
    return (signal, uuid.uuid4())


class TestBucketing:
    def test_bullish_signal_goes_to_bull_case_only(self):
        signal = close_vs_ma_signal("close_vs_sma_50", "50 DMA", 110.0, 100.0, 10.0, -10.0)
        bull, bear = build_bull_bear_case([_pair(signal)])
        assert len(bull) == 1
        assert bear == []

    def test_bearish_signal_goes_to_bear_case_only(self):
        signal = close_vs_ma_signal("close_vs_sma_50", "50 DMA", 90.0, 100.0, 10.0, -10.0)
        bull, bear = build_bull_bear_case([_pair(signal)])
        assert bull == []
        assert len(bear) == 1

    def test_neutral_signal_excluded_from_both(self):
        signal = adx_signal(20.0)  # 15-25 band -> direction 0
        bull, bear = build_bull_bear_case([_pair(signal)])
        assert bull == []
        assert bear == []

    def test_sorted_by_magnitude_descending(self):
        strong_bull = rsi_signal(75.0)  # delta +15
        mild_bull = adx_signal(30.0)  # delta +10
        bull, _ = build_bull_bear_case([_pair(mild_bull), _pair(strong_bull)])
        assert [b.metric_name for b in bull] == ["rsi_14", "adx_14"]
        assert bull[0].magnitude >= bull[1].magnitude


class TestStrengthPropagation:
    def test_strength_matches_signal_strength_exactly(self):
        signal = rsi_signal(75.0)  # delta=+15 -> "strong"
        bull, _ = build_bull_bear_case([_pair(signal)])
        assert bull[0].strength == signal.strength == "strong"

    def test_moderate_strength_entry(self):
        signal = close_vs_ma_signal("close_vs_sma_50", "50 DMA", 110.0, 100.0, 10.0, -10.0)  # delta=10
        bull, _ = build_bull_bear_case([_pair(signal)])
        assert bull[0].strength == "moderate"

    def test_mild_strength_entry(self):
        from packages.scoring.signals import stochastic_signal

        signal = stochastic_signal(85.0)  # delta=+5 -> "mild"
        bull, _ = build_bull_bear_case([_pair(signal)])
        assert bull[0].strength == "mild"
