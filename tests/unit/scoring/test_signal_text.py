"""Exact-string tests for the explanatory interpretation templates (SCORING.md section 7,
"Evidence model" - every word must come from a deterministic template, never an LLM).

Covers one representative metric per evidence type (technical, momentum, fundamentals,
valuation, sector relative strength, market regime, risk quality) plus the
magnitude-qualifier boundary logic (`_pct_deviation_label`, and the shared
strong/moderate/mild `_qualifier` built from `classify_strength`).
"""
from __future__ import annotations

from packages.scoring.signals import (
    _pct_deviation_label,
    adx_signal,
    close_vs_ma_signal,
    growth_signal,
    market_regime_signal,
    max_drawdown_signal,
    rsi_signal,
    sector_relative_strength_signal,
    valuation_percentile_signal,
)


class TestPctDeviationLabel:
    def test_mild_below_three_pct(self):
        assert _pct_deviation_label(2.9) == "a mild deviation from trend"

    def test_moderate_boundary_inclusive(self):
        assert _pct_deviation_label(3.0) == "a moderate deviation from trend"

    def test_strong_boundary_inclusive(self):
        assert _pct_deviation_label(10.0) == "a significant extension"

    def test_just_below_strong_boundary_is_moderate(self):
        assert _pct_deviation_label(9.999) == "a moderate deviation from trend"


class TestTechnicalText:
    def test_close_vs_ma_bullish_mild_deviation(self):
        signal = close_vs_ma_signal("close_vs_sma_50", "50 DMA", 101.0, 100.0, 10.0, -10.0)
        assert signal.interpretation == (
            "Price is 1.0% above the 50 DMA, an uptrend-consistent posture relative to this "
            "trend line (a mild deviation from trend)."
        )

    def test_close_vs_ma_bearish_significant_extension(self):
        signal = close_vs_ma_signal("close_vs_sma_200", "200 DMA", 80.0, 100.0, 10.0, -10.0)
        assert signal.interpretation == (
            "Price is 20.0% below the 200 DMA, a downtrend-consistent posture relative to this "
            "trend line (a significant extension)."
        )

    def test_adx_strong_trend_context(self):
        signal = adx_signal(30.0)
        assert signal.interpretation == (
            "ADX(14) is 30.0, indicating a strong trend - ADX measures trend strength regardless "
            "of direction, and readings at or above 25 typically mark a tradable, "
            "momentum-friendly trend."
        )


class TestMomentumText:
    def test_rsi_strong_bullish_overbought(self):
        signal = rsi_signal(75.0)
        assert signal.interpretation == (
            "RSI(14) is 75.0 - strong bullish momentum (overbought). RSI above 70 shows buying "
            "pressure has dominated the last 14 periods, though it also raises the odds of a "
            "near-term pullback."
        )


class TestFundamentalsText:
    def test_growth_signal_positive_growth_strong(self):
        signal = growth_signal("revenue_growth_yoy", "Revenue", 0.20, full_weight=True)
        assert signal.interpretation == (
            "Revenue grew +20.0% year-over-year - sustained top/bottom-line growth is one of the "
            "clearest signs a business is expanding its competitive position (a significant "
            "growth reading)."
        )

    def test_growth_signal_negative_growth_uses_declined_verb(self):
        signal = growth_signal("revenue_growth_yoy", "Revenue", -0.10, full_weight=True)
        assert "Revenue declined -10.0% year-over-year" in signal.interpretation


class TestRiskQualityText:
    def test_max_drawdown_shallow(self):
        signal = max_drawdown_signal(-10.0)
        assert signal.interpretation == (
            "Max drawdown over available history is -10.0% - shallow. A smaller worst-case "
            "peak-to-trough decline has historically made this stock easier to hold through "
            "downturns."
        )


class TestSectorRelativeStrengthText:
    def test_outperforming_peers(self):
        signal = sector_relative_strength_signal(12.0)
        assert signal.interpretation == (
            "3-month return is +12.0 percentage points vs sector peers - the stock is "
            "outperforming its sector peer group, often a sign of changing competitive dynamics "
            "or capital rotation (a moderate relative-strength gap)."
        )


class TestValuationText:
    def test_cheap_valuation_discount_language(self):
        signal = valuation_percentile_signal("pe_percentile", "P/E", 90.0)
        assert signal.interpretation == (
            "P/E is cheaper than 90% of the seeded universe - the market is pricing this stock at "
            "a discount to its peers on this metric, which can reflect genuine undervaluation or a "
            "legitimate quality/growth gap (a significant valuation gap)."
        )


class TestMarketRegimeText:
    def test_bullish_trend_context(self):
        signal = market_regime_signal("BULLISH_TREND", "2026-10-05")
        assert signal.interpretation == (
            "Market regime is BULLISH_TREND as of 2026-10-05 (breadth_universe=seeded_117) - "
            "broad market breadth and trend are both favorable, a backdrop that has historically "
            "lifted most stocks regardless of their own fundamentals, which every stock trades "
            "within regardless of its own merits (a significant regime reading)."
        )
