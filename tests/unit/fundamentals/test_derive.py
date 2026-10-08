"""Unit tests for packages/fundamentals/derive.py (SPEC.md sections 12, 13, 64, 86).

Every function is pure, so these are hand-verifiable-value tests, not
"didn't crash" tests (SPEC.md section 81 rule 4).
"""
from __future__ import annotations

from datetime import date

import pytest

from packages.fundamentals.derive import (
    asset_turnover,
    compute_valuation_metrics,
    current_ratio,
    debt_to_equity,
    fcf_margin,
    financial_leverage,
    find_year_ago_period_end,
    fundamentals_freshness_score,
    growth_yoy,
    interest_coverage,
    is_at_all_time_high,
    net_debt_to_ebitda,
    net_profit_margin,
    operating_margin,
    peg_ratio,
    return_on_assets,
    roce_simplified,
    roe,
)


class TestGrowthYoy:
    def test_normal_two_period_case_hand_computed(self):
        # revenue grew from 1,000 to 1,140 => +14% (SPEC.md section 13 example).
        assert growth_yoy(current=1140.0, previous=1000.0) == pytest.approx(0.14)

    def test_single_period_available_is_none_not_zero(self):
        assert growth_yoy(current=1140.0, previous=None) is None
        assert growth_yoy(current=None, previous=1000.0) is None

    def test_zero_previous_period_is_none_not_inf(self):
        assert growth_yoy(current=100.0, previous=0.0) is None

    def test_negative_growth(self):
        assert growth_yoy(current=800.0, previous=1000.0) == pytest.approx(-0.20)


class TestFindYearAgoPeriodEnd:
    def test_exact_year_match(self):
        period_ends = [date(2023, 3, 31), date(2023, 6, 30), date(2024, 3, 31), date(2024, 6, 30)]
        assert find_year_ago_period_end(period_ends, date(2024, 6, 30)) == date(2023, 6, 30)

    def test_within_tolerance_match(self):
        # quarter-end drifted by 5 days in the provider's data - still a match.
        period_ends = [date(2023, 6, 25), date(2024, 6, 30)]
        assert find_year_ago_period_end(period_ends, date(2024, 6, 30), tolerance_days=20) == date(2023, 6, 25)

    def test_out_of_tolerance_is_none(self):
        period_ends = [date(2023, 1, 15), date(2024, 6, 30)]
        assert find_year_ago_period_end(period_ends, date(2024, 6, 30), tolerance_days=20) is None

    def test_missing_quarter_in_sequence_is_none(self):
        # only the latest quarter is available - nothing to match against.
        assert find_year_ago_period_end([date(2024, 6, 30)], date(2024, 6, 30)) is None


class TestIsAtAllTimeHigh:
    def test_new_high(self):
        assert is_at_all_time_high(150.0, [100.0, 120.0, 150.0]) is True

    def test_not_a_high(self):
        assert is_at_all_time_high(100.0, [100.0, 120.0, 150.0]) is False

    def test_current_none_is_none(self):
        assert is_at_all_time_high(None, [100.0, 120.0]) is None

    def test_all_none_history_is_none(self):
        assert is_at_all_time_high(100.0, [None, None]) is None

    def test_single_point_history_is_itself_the_high(self):
        assert is_at_all_time_high(100.0, [100.0]) is True


class TestRoe:
    def test_hand_computed(self):
        assert roe(pat=200.0, equity=1000.0) == pytest.approx(0.20)

    def test_missing_inputs_are_none(self):
        assert roe(pat=None, equity=1000.0) is None
        assert roe(pat=200.0, equity=None) is None

    def test_zero_equity_is_none_not_zerodivisionerror(self):
        assert roe(pat=200.0, equity=0.0) is None


class TestRoceSimplified:
    def test_hand_computed(self):
        # capital_employed = equity(1000) + total_debt(500) = 1500; ebit=300 => 0.2
        assert roce_simplified(ebit=300.0, equity=1000.0, total_debt=500.0) == pytest.approx(0.2)

    def test_missing_inputs_are_none(self):
        assert roce_simplified(ebit=None, equity=1000.0, total_debt=500.0) is None
        assert roce_simplified(ebit=300.0, equity=None, total_debt=500.0) is None
        assert roce_simplified(ebit=300.0, equity=1000.0, total_debt=None) is None

    def test_zero_capital_employed_is_none(self):
        assert roce_simplified(ebit=300.0, equity=-500.0, total_debt=500.0) is None


class TestDebtToEquity:
    def test_hand_computed(self):
        assert debt_to_equity(total_debt=400.0, equity=800.0) == pytest.approx(0.5)

    def test_zero_equity_is_none(self):
        assert debt_to_equity(total_debt=400.0, equity=0.0) is None


class TestNetDebtToEbitda:
    def test_hand_computed(self):
        assert net_debt_to_ebitda(total_debt=1000.0, cash=200.0, ebitda=400.0) == pytest.approx(2.0)

    def test_non_positive_ebitda_is_none_not_fabricated(self):
        assert net_debt_to_ebitda(total_debt=1000.0, cash=200.0, ebitda=0.0) is None
        assert net_debt_to_ebitda(total_debt=1000.0, cash=200.0, ebitda=-50.0) is None

    def test_missing_inputs_are_none(self):
        assert net_debt_to_ebitda(total_debt=None, cash=200.0, ebitda=400.0) is None


class TestOperatingMargin:
    def test_hand_computed(self):
        assert operating_margin(ebit=250.0, revenue=1000.0) == pytest.approx(0.25)

    def test_zero_revenue_is_none(self):
        assert operating_margin(ebit=250.0, revenue=0.0) is None


class TestFcfMargin:
    def test_hand_computed(self):
        assert fcf_margin(free_cash_flow=150.0, revenue=1000.0) == pytest.approx(0.15)

    def test_missing_revenue_is_none(self):
        assert fcf_margin(free_cash_flow=150.0, revenue=None) is None


class TestFundamentalsFreshnessScore:
    def test_fresh_within_window_is_100(self):
        assert fundamentals_freshness_score(0) == 100.0
        assert fundamentals_freshness_score(90) == 100.0

    def test_fully_stale_floor_is_0(self):
        assert fundamentals_freshness_score(720) == 0.0
        assert fundamentals_freshness_score(1000) == 0.0

    def test_linear_decay_midpoint(self):
        # Midpoint of the 90->720 decay window is 405 days -> 50.0.
        midpoint = 90 + (720 - 90) // 2
        assert fundamentals_freshness_score(midpoint) == pytest.approx(50.0, abs=0.1)


class TestComputeValuationMetrics:
    def test_hand_computed_full_inputs(self):
        # close=100, eps=5 => P/E=20. equity=5000, shares=1000 => book/share=5 => P/B=20.
        # market_cap = 100*1000 = 100,000. total_debt=20,000, cash=5,000 =>
        # EV = 100,000+20,000-5,000=115,000. ebitda=11,500 => EV/EBITDA=10.
        # revenue=57,500 => EV/Sales=2.0. fcf=5,000 => fcf_yield=0.05.
        result = compute_valuation_metrics(
            close_price=100.0,
            period_end=date(2025, 3, 31),
            as_of=date(2025, 6, 29),
            eps=5.0,
            equity=5000.0,
            shares_outstanding=1000.0,
            revenue=57500.0,
            ebitda=11500.0,
            total_debt=20000.0,
            cash=5000.0,
            free_cash_flow=5000.0,
            dividend_yield=0.01,
        )
        assert result.pe == pytest.approx(20.0)
        assert result.pb == pytest.approx(20.0)
        assert result.ev_ebitda == pytest.approx(10.0)
        assert result.ev_sales == pytest.approx(2.0)
        assert result.fcf_yield == pytest.approx(0.05)
        assert result.dividend_yield == pytest.approx(0.01)
        assert result.data_age_days == 90
        assert result.stale is False

    def test_no_fundamentals_snapshot_at_all(self):
        result = compute_valuation_metrics(
            close_price=100.0,
            period_end=None,
            as_of=date(2025, 6, 29),
            eps=None,
            equity=None,
            shares_outstanding=None,
            revenue=None,
            ebitda=None,
            total_debt=None,
            cash=None,
            free_cash_flow=None,
            dividend_yield=None,
        )
        assert result.pe is None
        assert result.pb is None
        assert result.ev_ebitda is None
        assert result.ev_sales is None
        assert result.fcf_yield is None
        assert result.data_age_days is None
        assert result.stale is False

    def test_negative_eps_pe_is_none_not_negative_number(self):
        result = compute_valuation_metrics(
            close_price=100.0,
            period_end=date(2025, 1, 1),
            as_of=date(2025, 1, 10),
            eps=-2.0,
            equity=1000.0,
            shares_outstanding=100.0,
            revenue=1000.0,
            ebitda=100.0,
            total_debt=0.0,
            cash=0.0,
            free_cash_flow=0.0,
            dividend_yield=None,
        )
        assert result.pe is None

    def test_stale_flag_set_beyond_threshold(self):
        result = compute_valuation_metrics(
            close_price=100.0,
            period_end=date(2023, 1, 1),
            as_of=date(2025, 1, 1),
            eps=5.0,
            equity=1000.0,
            shares_outstanding=100.0,
            revenue=1000.0,
            ebitda=100.0,
            total_debt=0.0,
            cash=0.0,
            free_cash_flow=0.0,
            dividend_yield=None,
            stale_after_days=365,
        )
        assert result.data_age_days == 731
        assert result.stale is True

    def test_zero_shares_outstanding_is_none_market_cap_not_zerodivisionerror(self):
        result = compute_valuation_metrics(
            close_price=100.0,
            period_end=date(2025, 1, 1),
            as_of=date(2025, 1, 10),
            eps=5.0,
            equity=1000.0,
            shares_outstanding=0.0,
            revenue=1000.0,
            ebitda=100.0,
            total_debt=0.0,
            cash=0.0,
            free_cash_flow=0.0,
            dividend_yield=None,
        )
        assert result.market_cap is None
        assert result.pb is None
        assert result.fcf_yield is None


class TestReturnOnAssets:
    def test_hand_computed(self):
        assert return_on_assets(pat=200.0, total_assets=2000.0) == pytest.approx(0.10)

    def test_missing_input_is_none(self):
        assert return_on_assets(pat=None, total_assets=2000.0) is None
        assert return_on_assets(pat=200.0, total_assets=None) is None

    def test_zero_total_assets_is_none_not_zerodivisionerror(self):
        assert return_on_assets(pat=200.0, total_assets=0.0) is None


class TestNetProfitMargin:
    def test_hand_computed(self):
        assert net_profit_margin(pat=200.0, revenue=1140.0) == pytest.approx(200.0 / 1140.0)

    def test_missing_input_is_none(self):
        assert net_profit_margin(pat=None, revenue=1140.0) is None


class TestAssetTurnover:
    def test_hand_computed(self):
        assert asset_turnover(revenue=1140.0, total_assets=2000.0) == pytest.approx(0.57)

    def test_zero_total_assets_is_none(self):
        assert asset_turnover(revenue=1140.0, total_assets=0.0) is None


class TestFinancialLeverage:
    def test_hand_computed(self):
        assert financial_leverage(total_assets=2000.0, equity=1000.0) == pytest.approx(2.0)

    def test_zero_equity_is_none_not_zerodivisionerror(self):
        assert financial_leverage(total_assets=2000.0, equity=0.0) is None


class TestInterestCoverage:
    def test_hand_computed(self):
        assert interest_coverage(ebit=250.0, interest_expense=25.0) == pytest.approx(10.0)

    def test_missing_interest_expense_is_none(self):
        """Simulates an instrument where neither yfinance nor tradingview_ta had
        `interest_expense` - must degrade to `None`, never a fabricated value."""
        assert interest_coverage(ebit=250.0, interest_expense=None) is None

    def test_zero_or_negative_interest_expense_is_none(self):
        assert interest_coverage(ebit=250.0, interest_expense=0.0) is None
        assert interest_coverage(ebit=250.0, interest_expense=-5.0) is None


class TestCurrentRatio:
    def test_hand_computed(self):
        assert current_ratio(current_assets=600.0, current_liabilities=300.0) == pytest.approx(2.0)

    def test_missing_input_is_none(self):
        assert current_ratio(current_assets=None, current_liabilities=300.0) is None
        assert current_ratio(current_assets=600.0, current_liabilities=None) is None

    def test_zero_current_liabilities_is_none_not_zerodivisionerror(self):
        assert current_ratio(current_assets=600.0, current_liabilities=0.0) is None


class TestPegRatio:
    def test_hand_computed(self):
        # pe=20, eps_growth_yoy=0.25 (25%) -> peg = 20 / 25 = 0.8
        assert peg_ratio(pe=20.0, eps_growth_yoy=0.25) == pytest.approx(0.8)

    def test_missing_pe_is_none(self):
        assert peg_ratio(pe=None, eps_growth_yoy=0.25) is None

    def test_zero_or_negative_growth_is_none_not_fabricated(self):
        """PEG is conventionally undefined for a flat/shrinking-earnings company - same
        rationale as the P/E-null-on-loss-making-company rule."""
        assert peg_ratio(pe=20.0, eps_growth_yoy=0.0) is None
        assert peg_ratio(pe=20.0, eps_growth_yoy=-0.1) is None
