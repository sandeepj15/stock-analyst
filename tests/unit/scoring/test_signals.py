"""Hand-value tests for packages/scoring/signals.py (SPEC.md section 81 rule 4)."""
from __future__ import annotations

from packages.scoring.signals import (
    classify_strength,
    compute_fundamental_score,
    score_efficiency_points,
    score_growth_points,
    score_leverage_points,
    score_momentum_points,
    score_profitability_points,
    score_risk_quality_points,
    score_sector_relative_strength_points,
    score_technical_structure_points,
    score_valuation_points,
)


class TestTechnicalStructure:
    def test_all_bullish_signals_clamped_at_100(self):
        score, signals = score_technical_structure_points(
            close=120.0, sma_50=100.0, sma_200=90.0, ema_20=25.0, ema_50=20.0,
            adx_14=30.0, breakout_20d=True, breakdown_20d=False,
        )
        # deltas: +10 (close>sma50) +10 (close>sma200) +10 (sma50>sma200) +5 (ema20>ema50) +10 (adx>=25) +10 (breakout) = +55 -> 105 clamped to 100
        assert score == 100.0
        assert len(signals) == 6

    def test_all_bearish_signals_clamped_at_0(self):
        score, signals = score_technical_structure_points(
            close=80.0, sma_50=100.0, sma_200=110.0, ema_20=18.0, ema_50=22.0,
            adx_14=10.0, breakout_20d=False, breakdown_20d=True,
        )
        # deltas: -10 -10 -10 -5 -5 -10 = -50 -> 0
        assert score == 0.0

    def test_missing_submetrics_only_use_available_signals(self):
        score, signals = score_technical_structure_points(
            close=110.0, sma_50=100.0, sma_200=None, ema_20=None, ema_50=None,
            adx_14=None, breakout_20d=False, breakdown_20d=False,
        )
        assert len(signals) == 1
        assert score == 60.0  # 50 + 10


class TestMomentum:
    def test_hand_computed_bullish(self):
        score, _ = score_momentum_points(rsi_14=75.0, macd_histogram=0.5, roc_12=8.0, stochastic_k=85.0)
        # +15 (rsi>70) +10 (macd>0) +10 (roc>5) +5 (stoch>80) = +40 -> 90
        assert score == 90.0

    def test_rsi_increase_increases_score_other_inputs_fixed(self):
        low, _ = score_momentum_points(rsi_14=40.0, macd_histogram=0.0, roc_12=0.0, stochastic_k=50.0)
        high, _ = score_momentum_points(rsi_14=80.0, macd_histogram=0.0, roc_12=0.0, stochastic_k=50.0)
        assert high > low
        # rsi 30-45 band -> -10; macd<=0 -> -10; roc_12=0.0 is in the (-5, 0] band -> -5; stochastic 20-80 -> 0.
        assert low == 50.0 - 10.0 - 10.0 - 5.0

    def test_neutral_inputs_score_50(self):
        score, signals = score_momentum_points(rsi_14=50.0, macd_histogram=0.0, roc_12=None, stochastic_k=50.0)
        # rsi 45-55 -> 0; macd<=0 -> -10 (macd_histogram==0 is not >0); stochastic 20-80 -> 0
        assert score == 40.0


class TestClassifyStrength:
    """Boundary tests for the strong/moderate/mild tiers (SCORING.md "Bull case / Bear case").

    Thresholds: `abs(delta) >= 15.0` -> "strong"; `>= 8.0` -> "moderate"; else "mild".
    """

    def test_strong_boundary_inclusive(self):
        assert classify_strength(15.0) == "strong"
        assert classify_strength(-15.0) == "strong"
        assert classify_strength(40.0) == "strong"

    def test_just_below_strong_boundary_is_moderate(self):
        assert classify_strength(14.999) == "moderate"

    def test_moderate_boundary_inclusive(self):
        assert classify_strength(8.0) == "moderate"
        assert classify_strength(-8.0) == "moderate"

    def test_just_below_moderate_boundary_is_mild(self):
        assert classify_strength(7.999) == "mild"

    def test_zero_is_mild(self):
        assert classify_strength(0.0) == "mild"


class TestGrowthSubScore:
    def test_strong_growth_scores_high_and_signals_carry_strong_strength(self):
        score, signals = score_growth_points(revenue_growth_yoy=0.20, pat_growth_yoy=0.20, eps_growth_yoy=0.20)
        # +15 (revenue) +15 (pat) +10 (eps, half-weight) = +40 -> 90
        assert score == 90.0
        assert len(signals) == 3
        assert all(s.strength == "strong" for s in signals if s.metric_name != "eps_growth_yoy")

    def test_no_growth_data_returns_none_not_fifty(self):
        score, signals = score_growth_points(revenue_growth_yoy=None, pat_growth_yoy=None, eps_growth_yoy=None)
        assert score is None
        assert signals == []


class TestProfitabilitySubScore:
    def test_hand_computed_with_new_roa_and_margin_signals(self):
        score, signals = score_profitability_points(roe=0.20, roce=0.20, roa=0.10, net_profit_margin=0.20)
        # +10 (roe) +10 (roce) +10 (roa>=8%) +10 (margin>=15%) = +40 -> 90
        assert score == 90.0
        assert len(signals) == 4

    def test_degrades_gracefully_when_only_roe_available(self):
        score, signals = score_profitability_points(roe=0.20, roce=None, roa=None, net_profit_margin=None)
        assert len(signals) == 1
        assert score == 60.0  # 50 + 10

    def test_none_when_nothing_available(self):
        score, signals = score_profitability_points(roe=None, roce=None, roa=None, net_profit_margin=None)
        assert score is None
        assert signals == []


class TestLeverageSubScore:
    def test_healthy_balance_sheet_scores_high(self):
        score, signals = score_leverage_points(
            debt_to_equity=0.2, net_debt_to_ebitda=0.5, interest_coverage=10.0, current_ratio=2.5
        )
        # +15 (de<0.3) +15 (ndebitda<1.0) +15 (coverage>=8) +10 (current>=2.0) = +55 -> 100 clamped
        assert score == 100.0
        assert len(signals) == 4

    def test_degrades_gracefully_when_interest_expense_and_current_ratio_unavailable(self):
        """Simulates both providers lacking interest_expense/current_assets/current_liabilities
        (current_assets/current_liabilities in particular are structurally unavailable for
        banks, see DATA_SOURCES.md) - the leverage sub-score still computes from whatever is
        available, never erroring and never fabricating the missing pieces."""
        score, signals = score_leverage_points(
            debt_to_equity=0.2, net_debt_to_ebitda=0.5, interest_coverage=None, current_ratio=None
        )
        assert len(signals) == 2
        assert score == 80.0  # 50 + 15 + 15

    def test_none_when_nothing_available(self):
        score, signals = score_leverage_points(
            debt_to_equity=None, net_debt_to_ebitda=None, interest_coverage=None, current_ratio=None
        )
        assert score is None
        assert signals == []


class TestEfficiencySubScore:
    def test_high_asset_turnover_scores_high(self):
        score, signals = score_efficiency_points(asset_turnover=1.5)
        assert score == 65.0  # 50 + 15
        assert len(signals) == 1

    def test_none_when_unavailable(self):
        score, signals = score_efficiency_points(asset_turnover=None)
        assert score is None
        assert signals == []


class TestComputeFundamentalScore:
    def test_hand_computed_weighted_blend_of_all_four_subscores(self):
        result = compute_fundamental_score(
            revenue_growth_yoy=0.20, pat_growth_yoy=0.20, eps_growth_yoy=0.20,  # growth -> 90
            roe=0.20, roce=0.20, roa=0.10, net_profit_margin=0.20,  # profitability -> 90
            debt_to_equity=0.2, net_debt_to_ebitda=0.5, interest_coverage=10.0, current_ratio=2.5,  # leverage -> 100
            asset_turnover=1.5,  # efficiency -> 65
        )
        assert result.growth == 90.0
        assert result.profitability == 90.0
        assert result.leverage == 100.0
        assert result.efficiency == 65.0
        # weights: growth 0.35, profitability 0.35, leverage 0.20, efficiency 0.10 (all available)
        expected = 90.0 * 0.35 + 90.0 * 0.35 + 100.0 * 0.20 + 65.0 * 0.10
        assert result.overall == expected
        assert len(result.signals) == 3 + 4 + 4 + 1

    def test_renormalizes_when_leverage_and_efficiency_are_entirely_unavailable(self):
        """Both the leverage inputs (debt_to_equity etc.) and the efficiency input
        (asset_turnover) are None - overall must renormalize over just growth+profitability,
        never silently treat the missing sub-scores as 0 or 50."""
        result = compute_fundamental_score(
            revenue_growth_yoy=0.20, pat_growth_yoy=0.20, eps_growth_yoy=0.20,  # growth -> 90
            roe=0.20, roce=0.20, roa=None, net_profit_margin=None,  # profitability -> uses roe/roce only
            debt_to_equity=None, net_debt_to_ebitda=None, interest_coverage=None, current_ratio=None,
            asset_turnover=None,
        )
        assert result.leverage is None
        assert result.efficiency is None
        # profitability: +10 (roe) +10 (roce) = +60; growth as above = 90
        assert result.profitability == 70.0
        expected = 90.0 * (0.35 / 0.70) + 70.0 * (0.35 / 0.70)
        assert abs(result.overall - expected) < 1e-9

    def test_everything_unavailable_is_none_not_fabricated(self):
        result = compute_fundamental_score(
            revenue_growth_yoy=None, pat_growth_yoy=None, eps_growth_yoy=None,
            roe=None, roce=None, roa=None, net_profit_margin=None,
            debt_to_equity=None, net_debt_to_ebitda=None, interest_coverage=None, current_ratio=None,
            asset_turnover=None,
        )
        assert result.overall is None
        assert result.growth is None
        assert result.profitability is None
        assert result.leverage is None
        assert result.efficiency is None
        assert result.signals == ()


class TestRiskQuality:
    def test_low_risk_scores_high(self):
        score, _ = score_risk_quality_points(atr_pct=1.0, rolling_volatility_pct=15.0, max_drawdown_pct=-5.0)
        assert score == 90.0  # 50+15+15+10

    def test_high_risk_scores_low(self):
        score, _ = score_risk_quality_points(atr_pct=6.0, rolling_volatility_pct=60.0, max_drawdown_pct=-60.0)
        assert score == 0.0  # 50-15-20-20 = -5 clamped to 0


class TestSectorRelativeStrength:
    def test_positive_relative_strength(self):
        score, signal = score_sector_relative_strength_points(9.0)
        assert score == 59.0
        assert signal.direction == 1

    def test_clamped_at_extremes(self):
        score, _ = score_sector_relative_strength_points(100.0)
        assert score == 90.0  # delta capped at +40


class TestValuation:
    def test_cheap_valuation_scores_above_50(self):
        score, signals = score_valuation_points({"pe_percentile": 90.0, "pb_percentile": 80.0})
        assert len(signals) == 2
        assert score > 50.0

    def test_no_percentiles_available_is_neutral_50(self):
        score, signals = score_valuation_points({})
        assert signals == []
        assert score == 50.0
