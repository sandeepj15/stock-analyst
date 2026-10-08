"""Stage 2 Momentum Scanner: the pure 8-condition evaluator.

Hand-constructed numbers throughout (no DB, no market data) - every
assertion below is independently hand-verifiable from the numbers in
the test itself, per SPEC.md section 81 rule 4 ("every financial
calculation must have tests").
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from packages.analytics.trend import sma
from packages.momentum.scanner import (
    DEFAULT_SMA200_TREND_LOOKBACK_DAYS,
    MIN_TRADING_DAYS_REQUIRED,
    evaluate_stage2_momentum,
)

# A baseline input set engineered so all 8 conditions pass:
#   close=150 > sma150=120, sma200=110                         (1)
#   sma150=120 > sma200=110                                    (2)
#   sma200=110 > sma200_22d_ago=100                            (3)
#   sma50=140 > sma150=120, sma200=110                         (4)
#   close=150 > sma50=140                                      (5)
#   close=150 >= 1.30 * 52w_low(100) = 130                     (6)
#   close=150 >= 0.75 * 52w_high(160) = 120                    (7)
#   rs_rank=80 >= 70                                           (8)
BASELINE = dict(
    close=150.0,
    sma_50=140.0,
    sma_150=120.0,
    sma_200=110.0,
    sma_200_n_days_ago=100.0,
    fifty_two_week_high=160.0,
    fifty_two_week_low=100.0,
    rs_rank=80.0,
    history_length=MIN_TRADING_DAYS_REQUIRED,
)

CONDITION_NAMES = [
    "close_above_sma150_and_sma200",
    "sma150_above_sma200",
    "sma200_trending_up",
    "sma50_above_sma150_and_sma200",
    "close_above_sma50",
    "close_at_least_130pct_of_52w_low",
    "close_within_25pct_of_52w_high",
    "rs_rank_at_least_70",
]


def _by_name(result, name):
    return next(c for c in result.conditions if c.name == name)


def test_all_8_conditions_pass():
    result = evaluate_stage2_momentum(**BASELINE)
    assert result.evaluable is True
    assert result.passed is True
    assert len(result.conditions) == 8
    assert [c.name for c in result.conditions] == CONDITION_NAMES
    assert all(c.passed for c in result.conditions)
    # distance_from_52w_high_pct = (150-160)/160*100 = -6.25
    assert result.distance_from_52w_high_pct == pytest.approx(-6.25)
    assert result.rs_rank == 80.0
    assert result.sma200_trend_lookback_days == DEFAULT_SMA200_TREND_LOOKBACK_DAYS


def test_fails_only_condition_3_sma200_not_trending_up():
    inputs = {**BASELINE, "sma_200_n_days_ago": 120.0}  # sma200(110) is NOT > 120
    result = evaluate_stage2_momentum(**inputs)
    assert result.evaluable is True
    assert result.passed is False
    failed = [c.name for c in result.conditions if not c.passed]
    assert failed == ["sma200_trending_up"]
    assert _by_name(result, "sma200_trending_up").value == 110.0
    assert _by_name(result, "sma200_trending_up").threshold == 120.0


def test_fails_only_condition_8_rs_rank_below_70():
    inputs = {**BASELINE, "rs_rank": 69.9}
    result = evaluate_stage2_momentum(**inputs)
    assert result.evaluable is True
    assert result.passed is False
    failed = [c.name for c in result.conditions if not c.passed]
    assert failed == ["rs_rank_at_least_70"]


@pytest.mark.parametrize(
    "rs_rank, expected",
    [(70.0, True), (69.999, False)],
)
def test_rs_rank_70_boundary_is_inclusive(rs_rank, expected):
    inputs = {**BASELINE, "rs_rank": rs_rank}
    result = evaluate_stage2_momentum(**inputs)
    assert _by_name(result, "rs_rank_at_least_70").passed is expected


def test_boundary_close_exactly_130pct_of_52w_low_passes():
    # 52w_low=100 -> threshold=130.0 exactly; close==130.0 must PASS (>=, not >).
    inputs = {**BASELINE, "close": 130.0, "sma_50": 125.0}  # keep close > sma_50 (condition 5) satisfied
    result = evaluate_stage2_momentum(**inputs)
    cond = _by_name(result, "close_at_least_130pct_of_52w_low")
    assert cond.passed is True
    assert cond.value == 130.0
    assert cond.threshold == 130.0


def test_just_below_130pct_of_52w_low_fails():
    inputs = {**BASELINE, "close": 129.99, "sma_50": 125.0}
    result = evaluate_stage2_momentum(**inputs)
    assert _by_name(result, "close_at_least_130pct_of_52w_low").passed is False


def test_boundary_close_exactly_75pct_of_52w_high_passes():
    # 52w_high=160 -> threshold=120.0 exactly; close==120.0 must PASS (>=, not >).
    inputs = {
        **BASELINE,
        "close": 120.0,
        "sma_50": 115.0,
        "sma_150": 100.0,
        "sma_200": 90.0,
        "sma_200_n_days_ago": 80.0,
        "fifty_two_week_low": 90.0,  # 1.30*90=117 <= 120, keeps condition 6 satisfied too
    }
    result = evaluate_stage2_momentum(**inputs)
    cond = _by_name(result, "close_within_25pct_of_52w_high")
    assert cond.passed is True
    assert cond.value == 120.0
    assert cond.threshold == 120.0
    # Every other condition still passes - this is a genuine boundary PASS, not a side effect.
    assert result.passed is True


def test_just_below_75pct_of_52w_high_fails():
    inputs = {
        **BASELINE,
        "close": 119.99,
        "sma_50": 115.0,
        "sma_150": 100.0,
        "sma_200": 90.0,
        "sma_200_n_days_ago": 80.0,
        "fifty_two_week_low": 90.0,
    }
    result = evaluate_stage2_momentum(**inputs)
    assert _by_name(result, "close_within_25pct_of_52w_high").passed is False
    assert result.passed is False


def test_insufficient_history_is_not_evaluable_never_a_fabricated_result():
    inputs = {**BASELINE, "history_length": MIN_TRADING_DAYS_REQUIRED - 1}
    result = evaluate_stage2_momentum(**inputs)
    assert result.evaluable is False
    assert result.passed is None  # never a fabricated True/False
    assert result.conditions == []
    assert result.reason == "insufficient_price_history"


@pytest.mark.parametrize(
    "missing_field",
    ["sma_50", "sma_150", "sma_200", "sma_200_n_days_ago", "fifty_two_week_high", "fifty_two_week_low", "rs_rank"],
)
def test_missing_any_required_input_is_not_evaluable(missing_field):
    inputs = {**BASELINE, missing_field: None}
    result = evaluate_stage2_momentum(**inputs)
    assert result.evaluable is False
    assert result.passed is None
    assert result.reason == "insufficient_price_history"


def test_configurable_lookback_changes_condition_3_result():
    """A real SMA200 series engineered to pass condition 3 at N=22 but fail at N=100.

    Construction (see packages/momentum/scanner.py's docstring on
    `sma200_trend_lookback_days` being a real parameter, not a hardcoded
    constant): a flat 200-level plateau, then a 100-bar linear decline
    from 300 down to 100, then a flat 150-level plateau, then a final
    flat low plateau - engineered so SMA200's trailing average dips
    over the *medium* term (today vs. 100 trading days ago is a net
    decline) while ticking up over just the *most recent* month (today
    vs. 22 trading days ago is a net rise) - a realistic "still below
    its longer trend but recently stabilizing" shape.
    """
    plateau_a = np.full(100, 200.0)
    decline_b = np.linspace(300.0, 100.0, 100, endpoint=False)
    plateau_c = np.full(100, 150.0)
    plateau_d = np.full(100, 133.0)
    prices = pd.Series(np.concatenate([plateau_a, decline_b, plateau_c, plateau_d]))

    sma200_series = sma(prices, 200)
    today = float(sma200_series.iloc[-1])
    sma200_22d_ago = float(sma200_series.iloc[-1 - 22])
    sma200_100d_ago = float(sma200_series.iloc[-1 - 100])

    # Sanity-check the engineered shape before using it - these are the
    # premise of the test, not its conclusion.
    assert today > sma200_22d_ago, "fixture must show SMA200 rising over the last 22 trading days"
    assert today < sma200_100d_ago, "fixture must show SMA200 net-declining over the last 100 trading days"

    # Every other condition is independently hand-set to PASS regardless
    # of lookback, so only condition 3 (and therefore the overall
    # pass/fail gate) can possibly flip between the two calls below.
    shared = dict(
        close=200.0,
        sma_50=180.0,
        sma_150=160.0,
        sma_200=today,
        fifty_two_week_high=210.0,  # 0.75*210=157.5 <= close
        fifty_two_week_low=150.0,  # 1.30*150=195 <= close
        rs_rank=80.0,
        history_length=len(prices),
    )

    at_22 = evaluate_stage2_momentum(sma_200_n_days_ago=sma200_22d_ago, sma200_trend_lookback_days=22, **shared)
    at_100 = evaluate_stage2_momentum(sma_200_n_days_ago=sma200_100d_ago, sma200_trend_lookback_days=100, **shared)

    assert _by_name(at_22, "sma200_trending_up").passed is True
    assert _by_name(at_100, "sma200_trending_up").passed is False

    # Every other condition is identical and passing in both calls, so
    # the overall gate flips purely because of the lookback parameter.
    assert at_22.passed is True
    assert at_100.passed is False
