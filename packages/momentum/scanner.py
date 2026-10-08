"""Stage 2 Momentum Scanner: the "Minervini Trend Template" (see
MOMENTUM_SCANNER.md for the full methodology write-up).

`evaluate_stage2_momentum` is a pure function over already-computed
scalar inputs (today's close/SMA values, the 52-week high/low, SMA200
from `sma200_trend_lookback_days` trading days ago, and the
instrument's RS Rank) - it does no DataFrame or DB work itself, so it
is directly unit-testable against hand-constructed numbers. DataFrame
plumbing (pulling those scalars out of an indicator series) and
persistence live in `apps/worker/jobs.py::compute_all_momentum_scans_job`
and `apps/api/routes/momentum.py`.

Deterministic, binary pass/fail (SPEC.md sections 2.2, 81 rule 1): a
stock passes only when ALL 8 conditions below are true. Every
condition's individual boolean is still returned (never hidden) even
though the overall gate is strictly binary - this app's evidence-first
philosophy of never hiding *why* (SPEC.md section 2.1) applies just as
much to a scanner as to the Research Score engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_SMA200_TREND_LOOKBACK_DAYS = 22  # ~1 trading month (this codebase's 22-trading-days convention)
METHODOLOGY_VERSION = "stage2_momentum_v1"

# "Insufficient history" per the task spec: a stock with less than ~252
# trading days (~1 year, this codebase's existing 52-week convention)
# must scan as not-evaluable, never a fabricated PASS or FAIL.
MIN_TRADING_DAYS_REQUIRED = 252

RS_RANK_MIN_PASS = 70.0
LOW_MULTIPLE_MIN_PASS = 1.30
HIGH_MULTIPLE_MIN_PASS = 0.75


@dataclass(frozen=True)
class ConditionResult:
    """One of the 8 Trend Template conditions, individually inspectable.

    `value`/`threshold` are both populated even for the two-SMA
    conditions (1 and 4) - `threshold` there is `max(sma_a, sma_b)`,
    i.e. the binding (harder-to-clear) constraint, so a single
    value/threshold pair is still meaningful without losing information
    (the `description` always spells out the full condition in words).
    """

    name: str
    passed: bool
    value: float
    threshold: float
    description: str


@dataclass(frozen=True)
class MomentumScanResult:
    evaluable: bool
    passed: bool | None  # None only when evaluable=False - never a fabricated pass/fail
    conditions: list[ConditionResult] = field(default_factory=list)
    distance_from_52w_high_pct: float | None = None
    rs_rank: float | None = None
    sma200_trend_lookback_days: int = DEFAULT_SMA200_TREND_LOOKBACK_DAYS
    reason: str | None = None  # populated only when evaluable=False


def evaluate_stage2_momentum(
    *,
    close: float,
    sma_50: float | None,
    sma_150: float | None,
    sma_200: float | None,
    sma_200_n_days_ago: float | None,
    fifty_two_week_high: float | None,
    fifty_two_week_low: float | None,
    rs_rank: float | None,
    history_length: int,
    sma200_trend_lookback_days: int = DEFAULT_SMA200_TREND_LOOKBACK_DAYS,
) -> MomentumScanResult:
    """Evaluate all 8 Stage 2 Trend Template conditions for one instrument on one date.

    `sma200_trend_lookback_days` (`N` in the task spec, default 22 -
    "confirms the long-term trend has been rising" over roughly the
    last month) is a parameter, not a hardcoded constant, specifically
    so a stricter 4-5 month window (N≈90-110) can be configured later
    without a code change.

    Returns `evaluable=False` (reason `"insufficient_price_history"`)
    rather than a fabricated PASS or FAIL when `history_length` is below
    `MIN_TRADING_DAYS_REQUIRED` or any required input is `None`.
    """
    if history_length < MIN_TRADING_DAYS_REQUIRED or any(
        v is None
        for v in (sma_50, sma_150, sma_200, sma_200_n_days_ago, fifty_two_week_high, fifty_two_week_low, rs_rank)
    ):
        return MomentumScanResult(
            evaluable=False,
            passed=None,
            sma200_trend_lookback_days=sma200_trend_lookback_days,
            reason="insufficient_price_history",
        )

    # Narrowed to `float` for mypy/readability - the `any(... is None ...)` guard above already ruled out None.
    assert sma_50 is not None
    assert sma_150 is not None
    assert sma_200 is not None
    assert sma_200_n_days_ago is not None
    assert fifty_two_week_high is not None
    assert fifty_two_week_low is not None
    assert rs_rank is not None

    conditions: list[ConditionResult] = []

    binding_150_200 = max(sma_150, sma_200)
    conditions.append(
        ConditionResult(
            name="close_above_sma150_and_sma200",
            passed=close > sma_150 and close > sma_200,
            value=close,
            threshold=binding_150_200,
            description="Close must be above both SMA150 and SMA200.",
        )
    )

    conditions.append(
        ConditionResult(
            name="sma150_above_sma200",
            passed=sma_150 > sma_200,
            value=sma_150,
            threshold=sma_200,
            description="SMA150 must be above SMA200.",
        )
    )

    conditions.append(
        ConditionResult(
            name="sma200_trending_up",
            passed=sma_200 > sma_200_n_days_ago,
            value=sma_200,
            threshold=sma_200_n_days_ago,
            description=(
                f"SMA200 today must be above SMA200 {sma200_trend_lookback_days} trading days ago "
                "(confirms the long-term trend has been rising)."
            ),
        )
    )

    binding_50 = max(sma_150, sma_200)
    conditions.append(
        ConditionResult(
            name="sma50_above_sma150_and_sma200",
            passed=sma_50 > sma_150 and sma_50 > sma_200,
            value=sma_50,
            threshold=binding_50,
            description="SMA50 must be above both SMA150 and SMA200.",
        )
    )

    conditions.append(
        ConditionResult(
            name="close_above_sma50",
            passed=close > sma_50,
            value=close,
            threshold=sma_50,
            description="Close must be above SMA50.",
        )
    )

    low_threshold = LOW_MULTIPLE_MIN_PASS * fifty_two_week_low
    conditions.append(
        ConditionResult(
            name="close_at_least_130pct_of_52w_low",
            passed=close >= low_threshold,
            value=close,
            threshold=low_threshold,
            description="Close must be at least 30% above the 52-week low.",
        )
    )

    high_threshold = HIGH_MULTIPLE_MIN_PASS * fifty_two_week_high
    conditions.append(
        ConditionResult(
            name="close_within_25pct_of_52w_high",
            passed=close >= high_threshold,
            value=close,
            threshold=high_threshold,
            description="Close must be at least 75% of the 52-week high (within 25% of it).",
        )
    )

    conditions.append(
        ConditionResult(
            name="rs_rank_at_least_70",
            passed=rs_rank >= RS_RANK_MIN_PASS,
            value=rs_rank,
            threshold=RS_RANK_MIN_PASS,
            description="RS Rank must be at least 70 (relative to the seeded universe).",
        )
    )

    overall_pass = all(c.passed for c in conditions)
    distance_from_high_pct = (close - fifty_two_week_high) / fifty_two_week_high * 100.0

    return MomentumScanResult(
        evaluable=True,
        passed=overall_pass,
        conditions=conditions,
        distance_from_52w_high_pct=distance_from_high_pct,
        rs_rank=rs_rank,
        sma200_trend_lookback_days=sma200_trend_lookback_days,
        reason=None,
    )
