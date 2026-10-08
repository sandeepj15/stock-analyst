"""Pure, deterministic per-metric signal/point functions (SPEC.md sections 17-18, 86).

No I/O, no DB, no LLM calls - every function here takes plain numeric
inputs and returns a `Signal` (metric name, raw value, point delta,
templated interpretation sentence, direction, strength). `packages/scoring/components.py`
wraps these with DB access + `EvidenceBuilder` calls to produce
`ComponentResult`s; keeping the point math here means it is directly
hand-value-testable (see `tests/unit/scoring/test_signals.py`) without a
database.

## Scoring convention (documented once, applies to every component)

Each component starts from a neutral baseline of 50 and accumulates a
point delta per available sub-signal, then clamps to `[0, 100]`. A
missing sub-signal contributes **nothing** (not a penalty, not a reward)
- it is simply skipped, which is why a component with only 1 of 5
sub-signals available still produces a score, just a less-informed one
(SPEC.md section 21: missing evidence is surfaced via the component's
`available`/`reason` fields and the confidence calculation, never by
silently treating a gap as neutral *inside* the point math - the "skip"
here is about an individual sub-signal within an otherwise-available
component, not about pretending missing data is itself a 0-delta
signal). See SCORING.md for the full table of bands transcribed from
this module.

`direction` is `+1` (bullish), `-1` (bearish) or `0` (neutral) and is
used only for the deterministic bull/bear case bucketing
(`packages/scoring/bull_bear.py`) - it is never averaged into the score.

## Strength classification (SCORING.md section 8.1, bull/bear "strength" field)

Every `Signal` also carries a `strength` of `"strong"` / `"moderate"` /
`"mild"`, computed by `classify_strength` purely from `abs(delta)` - the
exact point value this module already assigns during scoring, not a
second, independently-invented scale. The two break points
(`STRENGTH_STRONG_THRESHOLD=15.0`, `STRENGTH_MODERATE_THRESHOLD=8.0`)
are the two natural clusters that already recur throughout this file's
hardcoded delta vocabulary (5/10 "secondary" steps vs. 15/20/30-40
"primary" steps) - see SCORING.md for the full worked table showing how
every sub-signal in this module lands in strong/moderate/mild under
these two thresholds. This same `strength` tier also drives the
magnitude-qualifier clause appended to every interpretation sentence
below (`_qualifier`) - the explanatory text and the bull/bear "Strong"/
"Moderate"/"Mild" badge are therefore always consistent with each other
and with the real score contribution, by construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

STRENGTH_STRONG_THRESHOLD = 15.0
STRENGTH_MODERATE_THRESHOLD = 8.0


def classify_strength(delta: float) -> str:
    """`"strong"` / `"moderate"` / `"mild"` from `abs(delta)` - see module docstring.

    Boundaries are inclusive on the strong/moderate side (`>=`), i.e.
    `abs(delta) == 15.0` is `"strong"` and `abs(delta) == 8.0` is
    `"moderate"` - tested explicitly in
    `tests/unit/scoring/test_signals.py::TestClassifyStrength`.
    """
    magnitude = abs(delta)
    if magnitude >= STRENGTH_STRONG_THRESHOLD:
        return "strong"
    if magnitude >= STRENGTH_MODERATE_THRESHOLD:
        return "moderate"
    return "mild"


_QUALIFIER_ADJECTIVE: dict[str, str] = {
    "strong": "a significant",
    "moderate": "a moderate",
    "mild": "a mild",
}


def _qualifier(strength: str, noun: str) -> str:
    """Render the shared magnitude-qualifier clause for an interpretation sentence.

    `noun` is metric-family-specific ("deviation from trend", "momentum
    reading", "leverage reading", ...) so the same strong/moderate/mild
    adjective reads naturally across every evidence type. This is the
    single place every interpretation string below gets its magnitude
    language from - see the module docstring for why `strength` (hence
    this phrase) is derived from `delta`, never a new ad hoc scale.
    """
    return f"{_QUALIFIER_ADJECTIVE[strength]} {noun}"


_PCT_DEVIATION_MILD = 3.0
_PCT_DEVIATION_STRONG = 10.0


def _pct_deviation_label(pct_abs: float) -> str:
    """Magnitude label for a %-distance-from-level metric (price vs. a moving average).

    Reuses the same order-of-magnitude breakpoints this module already
    uses elsewhere for percentage-based bands (ROC's 5% breakpoint,
    ATR%'s 1.5/3/5% bands) rather than inventing a new scale: `<3%` is
    "a mild deviation", `3-10%` is "a moderate deviation", `>=10%` is "a
    significant extension" - these two breakpoints bracket the existing
    1.5-5% vocabulary already used for ATR/ROC in this file.
    """
    if pct_abs >= _PCT_DEVIATION_STRONG:
        return "a significant extension"
    if pct_abs >= _PCT_DEVIATION_MILD:
        return "a moderate deviation from trend"
    return "a mild deviation from trend"


@dataclass(frozen=True)
class Signal:
    metric_name: str
    value: float
    delta: float
    interpretation: str
    direction: int  # +1 bullish, -1 bearish, 0 neutral
    unit: str | None = None
    strength: str = field(init=False)

    def __post_init__(self) -> None:
        # `strength` is derived, never passed in directly - computed from
        # `delta` (the exact value this signal already contributes to the
        # score) so it can never drift out of sync with the real scoring
        # math. `object.__setattr__` is required because the dataclass is
        # frozen.
        object.__setattr__(self, "strength", classify_strength(self.delta))


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


# --- Technical Structure (20%) ---------------------------------------------


def close_vs_ma_signal(metric_name: str, label: str, close: float, ma: float, bullish_delta: float, bearish_delta: float) -> Signal:
    pct = (close / ma - 1.0) * 100.0
    magnitude = _pct_deviation_label(abs(pct))
    if close > ma:
        return Signal(
            metric_name,
            pct,
            bullish_delta,
            f"Price is {pct:.1f}% above the {label}, an uptrend-consistent posture relative to this trend line "
            f"({magnitude}).",
            +1,
            "pct",
        )
    return Signal(
        metric_name,
        pct,
        bearish_delta,
        f"Price is {abs(pct):.1f}% below the {label}, a downtrend-consistent posture relative to this trend line "
        f"({magnitude}).",
        -1,
        "pct",
    )


def ma_cross_signal(metric_name: str, fast_label: str, slow_label: str, fast: float, slow: float, bullish_delta: float, bearish_delta: float) -> Signal:
    pct = (fast / slow - 1.0) * 100.0
    magnitude = _pct_deviation_label(abs(pct))
    if fast > slow:
        return Signal(
            metric_name,
            pct,
            bullish_delta,
            f"{fast_label} is above the {slow_label} ({pct:+.1f}%, golden-cross-style state) - this ordering of "
            f"moving averages is historically associated with sustained upward momentum ({magnitude} between "
            f"the two averages).",
            +1,
            "pct",
        )
    return Signal(
        metric_name,
        pct,
        bearish_delta,
        f"{fast_label} is below the {slow_label} ({pct:+.1f}%, death-cross-style state) - this ordering of "
        f"moving averages is historically associated with sustained downward pressure ({magnitude} between "
        f"the two averages).",
        -1,
        "pct",
    )


def adx_signal(adx_14: float) -> Signal:
    if adx_14 >= 25:
        s = Signal(
            "adx_14",
            adx_14,
            10.0,
            f"ADX(14) is {adx_14:.1f}, indicating a strong trend - ADX measures trend strength regardless of "
            f"direction, and readings at or above 25 typically mark a tradable, momentum-friendly trend.",
            +1,
        )
    elif adx_14 < 15:
        s = Signal(
            "adx_14",
            adx_14,
            -5.0,
            f"ADX(14) is {adx_14:.1f}, indicating a weak or absent trend - below 15, price action is typically "
            f"choppy and directionless, which raises the risk of false breakouts.",
            -1,
        )
    else:
        s = Signal(
            "adx_14",
            adx_14,
            0.0,
            f"ADX(14) is {adx_14:.1f}, a moderate trend strength - neither strongly trending nor clearly "
            f"range-bound.",
            0,
        )
    return s


def breakout_breakdown_signal(breakout_20d: bool, breakdown_20d: bool) -> Signal | None:
    if breakout_20d:
        return Signal(
            "breakout_20d",
            1.0,
            10.0,
            "Price made a new 20-day high (breakout) - fresh highs often attract momentum buying as the stock "
            "clears recent resistance.",
            +1,
        )
    if breakdown_20d:
        return Signal(
            "breakdown_20d",
            -1.0,
            -10.0,
            "Price made a new 20-day low (breakdown) - fresh lows often attract momentum selling as the stock "
            "breaches recent support.",
            -1,
        )
    return None


def score_technical_structure_points(
    *,
    close: float,
    sma_50: float | None,
    sma_200: float | None,
    ema_20: float | None,
    ema_50: float | None,
    adx_14: float | None,
    breakout_20d: bool,
    breakdown_20d: bool,
) -> tuple[float, list[Signal]]:
    signals: list[Signal] = []
    if sma_50 is not None:
        signals.append(close_vs_ma_signal("close_vs_sma_50", "50 DMA", close, sma_50, 10.0, -10.0))
    if sma_200 is not None:
        signals.append(close_vs_ma_signal("close_vs_sma_200", "200 DMA", close, sma_200, 10.0, -10.0))
    if sma_50 is not None and sma_200 is not None:
        signals.append(ma_cross_signal("sma_50_vs_sma_200", "50 DMA", "200 DMA", sma_50, sma_200, 10.0, -10.0))
    if ema_20 is not None and ema_50 is not None:
        signals.append(ma_cross_signal("ema_20_vs_ema_50", "20 EMA", "50 EMA", ema_20, ema_50, 5.0, -5.0))
    if adx_14 is not None:
        signals.append(adx_signal(adx_14))
    bo = breakout_breakdown_signal(breakout_20d, breakdown_20d)
    if bo is not None:
        signals.append(bo)

    score = clamp_score(50.0 + sum(s.delta for s in signals))
    return score, signals


# --- Momentum (15%) ---------------------------------------------------------


def rsi_signal(rsi_14: float) -> Signal:
    if rsi_14 > 70:
        return Signal(
            "rsi_14",
            rsi_14,
            15.0,
            f"RSI(14) is {rsi_14:.1f} - strong bullish momentum (overbought). RSI above 70 shows buying pressure "
            f"has dominated the last 14 periods, though it also raises the odds of a near-term pullback.",
            +1,
        )
    if rsi_14 >= 55:
        return Signal(
            "rsi_14",
            rsi_14,
            10.0,
            f"RSI(14) is {rsi_14:.1f} - bullish momentum. Buying pressure has had the upper hand over the last 14 "
            f"periods without yet reaching an overbought extreme.",
            +1,
        )
    if rsi_14 >= 45:
        return Signal(
            "rsi_14",
            rsi_14,
            0.0,
            f"RSI(14) is {rsi_14:.1f} - neutral momentum. Buying and selling pressure have been roughly balanced "
            f"over the last 14 periods.",
            0,
        )
    if rsi_14 >= 30:
        return Signal(
            "rsi_14",
            rsi_14,
            -10.0,
            f"RSI(14) is {rsi_14:.1f} - bearish momentum. Selling pressure has had the upper hand over the last "
            f"14 periods without yet reaching an oversold extreme.",
            -1,
        )
    return Signal(
        "rsi_14",
        rsi_14,
        -15.0,
        f"RSI(14) is {rsi_14:.1f} - strong bearish momentum (oversold). RSI below 30 shows selling pressure has "
        f"dominated the last 14 periods, which also raises the odds of a near-term bounce.",
        -1,
    )


def macd_histogram_signal(macd_histogram: float) -> Signal:
    if macd_histogram > 0:
        return Signal(
            "macd_histogram",
            macd_histogram,
            10.0,
            f"MACD histogram is positive ({macd_histogram:.3f}) - bullish state. The MACD line sits above its "
            f"signal line, a classic trend-following bullish configuration.",
            +1,
        )
    return Signal(
        "macd_histogram",
        macd_histogram,
        -10.0,
        f"MACD histogram is negative ({macd_histogram:.3f}) - bearish state. The MACD line sits below its "
        f"signal line, a classic trend-following bearish configuration.",
        -1,
    )


def roc_signal(roc_12: float) -> Signal:
    if roc_12 > 5:
        delta = 10.0
    elif roc_12 > 0:
        delta = 5.0
    elif roc_12 > -5:
        delta = -5.0
    else:
        delta = -10.0
    direction = 1 if roc_12 > 0 else (-1 if roc_12 < 0 else 0)
    return Signal(
        "roc_12",
        roc_12,
        delta,
        f"12-period rate of change is {roc_12:+.1f}% - price is {abs(roc_12):.1f}% "
        f"{'higher' if roc_12 >= 0 else 'lower'} than it was 12 periods ago, a direct read on price momentum "
        f"independent of any oscillator smoothing.",
        direction,
    )


def stochastic_signal(stochastic_k: float) -> Signal:
    if stochastic_k > 80:
        return Signal(
            "stochastic_k",
            stochastic_k,
            5.0,
            f"Stochastic %K is {stochastic_k:.1f} - strong momentum. The close sits near the top of its recent "
            f"trading range, a classic overbought-momentum reading.",
            +1,
        )
    if stochastic_k < 20:
        return Signal(
            "stochastic_k",
            stochastic_k,
            -5.0,
            f"Stochastic %K is {stochastic_k:.1f} - weak momentum. The close sits near the bottom of its recent "
            f"trading range, a classic oversold-momentum reading.",
            -1,
        )
    return Signal(
        "stochastic_k",
        stochastic_k,
        0.0,
        f"Stochastic %K is {stochastic_k:.1f} - neutral. The close sits in the middle of its recent trading "
        f"range.",
        0,
    )


def score_momentum_points(
    *,
    rsi_14: float | None,
    macd_histogram: float | None,
    roc_12: float | None,
    stochastic_k: float | None,
) -> tuple[float, list[Signal]]:
    signals: list[Signal] = []
    if rsi_14 is not None:
        signals.append(rsi_signal(rsi_14))
    if macd_histogram is not None:
        signals.append(macd_histogram_signal(macd_histogram))
    if roc_12 is not None:
        signals.append(roc_signal(roc_12))
    if stochastic_k is not None:
        signals.append(stochastic_signal(stochastic_k))

    score = clamp_score(50.0 + sum(s.delta for s in signals))
    return score, signals


# --- Fundamentals (20%) -----------------------------------------------------
#
# Refactored (SCORING.md "Fundamental Score" section, methodology
# research_score_v2): the flat "growth + ROE + ROCE" delta sum this
# component used to compute directly is now assembled from four named
# sub-scores (Growth / Profitability / Leverage / Efficiency, see
# `compute_fundamental_score` below) that are *also* the exact function
# backing the standalone `fundamental_score` block on
# `GET /api/v1/stocks/{symbol}/fundamentals`
# (`apps/api/routes/fundamentals.py`) - one function, two callers, so the
# Research Score's "fundamentals" component and the standalone
# Fundamental Score can never silently disagree (see
# `tests/unit/scoring/test_fundamental_score.py::test_single_source_of_truth_*`).


def growth_signal(metric_name: str, label: str, growth: float, full_weight: bool = True) -> Signal:
    """`growth` is a fraction (0.14 = +14%). `full_weight` bands are +-15/+-8/0, else +-10/+-5/0."""
    pct = growth * 100.0
    if full_weight:
        if growth >= 0.15:
            delta = 15.0
        elif growth >= 0.05:
            delta = 8.0
        elif growth >= 0.0:
            delta = 0.0
        elif growth >= -0.05:
            delta = -8.0
        else:
            delta = -15.0
    else:
        if growth >= 0.15:
            delta = 10.0
        elif growth >= 0.05:
            delta = 5.0
        elif growth >= 0.0:
            delta = 0.0
        elif growth >= -0.05:
            delta = -5.0
        else:
            delta = -10.0
    direction = 1 if growth > 0 else (-1 if growth < 0 else 0)
    strength = classify_strength(delta)
    verb = "grew" if growth >= 0 else "declined"
    return Signal(
        metric_name,
        pct,
        delta,
        f"{label} {verb} {pct:+.1f}% year-over-year - sustained top/bottom-line growth is one of the clearest "
        f"signs a business is expanding its competitive position ({_qualifier(strength, 'growth reading')}).",
        direction,
        "pct",
    )


def profitability_signal(metric_name: str, label: str, ratio: float, capital_base: str = "equity") -> Signal:
    """`ratio` is a fraction (0.15 = 15%). Used for ROE and simplified ROCE."""
    pct = ratio * 100.0
    if ratio >= 0.15:
        delta = 10.0
    elif ratio >= 0.08:
        delta = 5.0
    elif ratio >= 0.0:
        delta = 0.0
    else:
        delta = -10.0
    direction = 1 if ratio > 0.08 else (-1 if ratio < 0 else 0)
    strength = classify_strength(delta)
    return Signal(
        metric_name,
        pct,
        delta,
        f"{label} is {pct:.1f}% - this measures how efficiently the company turns {capital_base} into profit "
        f"({_qualifier(strength, 'profitability reading')}).",
        direction,
        "pct",
    )


def roa_signal(roa: float) -> Signal:
    """Return on Assets. Bands are lower than ROE's (total assets > equity for a levered company), a
    documented product choice - see SCORING.md."""
    pct = roa * 100.0
    if roa >= 0.08:
        delta = 10.0
    elif roa >= 0.03:
        delta = 5.0
    elif roa >= 0.0:
        delta = 0.0
    else:
        delta = -10.0
    direction = 1 if roa > 0.03 else (-1 if roa < 0 else 0)
    strength = classify_strength(delta)
    return Signal(
        "roa",
        pct,
        delta,
        f"ROA is {pct:.1f}% - this measures how efficiently the company turns its total asset base into profit, "
        f"independent of how that base is financed ({_qualifier(strength, 'profitability reading')}).",
        direction,
        "pct",
    )


def net_margin_signal(margin: float) -> Signal:
    pct = margin * 100.0
    if margin >= 0.15:
        delta = 10.0
    elif margin >= 0.05:
        delta = 5.0
    elif margin >= 0.0:
        delta = 0.0
    else:
        delta = -10.0
    direction = 1 if margin > 0.05 else (-1 if margin < 0 else 0)
    strength = classify_strength(delta)
    return Signal(
        "net_profit_margin",
        pct,
        delta,
        f"Net profit margin is {pct:.1f}% - the share of every rupee of revenue that converts to bottom-line "
        f"profit after all costs ({_qualifier(strength, 'margin reading')}).",
        direction,
        "pct",
    )


def score_growth_points(
    *,
    revenue_growth_yoy: float | None,
    pat_growth_yoy: float | None,
    eps_growth_yoy: float | None,
) -> tuple[float | None, list[Signal]]:
    signals: list[Signal] = []
    if revenue_growth_yoy is not None:
        signals.append(growth_signal("revenue_growth_yoy", "Revenue", revenue_growth_yoy, full_weight=True))
    if pat_growth_yoy is not None:
        signals.append(growth_signal("pat_growth_yoy", "PAT", pat_growth_yoy, full_weight=True))
    if eps_growth_yoy is not None:
        signals.append(growth_signal("eps_growth_yoy", "EPS", eps_growth_yoy, full_weight=False))
    if not signals:
        return None, []
    return clamp_score(50.0 + sum(s.delta for s in signals)), signals


def score_profitability_points(
    *,
    roe: float | None,
    roce: float | None,
    roa: float | None = None,
    net_profit_margin: float | None = None,
) -> tuple[float | None, list[Signal]]:
    signals: list[Signal] = []
    if roe is not None:
        signals.append(profitability_signal("roe", "ROE", roe, capital_base="shareholder equity"))
    if roce is not None:
        signals.append(profitability_signal("roce_simplified", "Simplified ROCE", roce, capital_base="capital employed"))
    if roa is not None:
        signals.append(roa_signal(roa))
    if net_profit_margin is not None:
        signals.append(net_margin_signal(net_profit_margin))
    if not signals:
        return None, []
    return clamp_score(50.0 + sum(s.delta for s in signals)), signals


def debt_to_equity_signal(de: float) -> Signal:
    """Lower is better (a risk/quality signal, not a reward-for-leverage one)."""
    if de < 0.3:
        delta = 15.0
    elif de < 0.6:
        delta = 5.0
    elif de < 1.0:
        delta = -5.0
    else:
        delta = -15.0
    direction = 1 if de < 0.6 else (-1 if de >= 1.0 else 0)
    strength = classify_strength(delta)
    return Signal(
        "debt_to_equity",
        de,
        delta,
        f"Debt/Equity is {de:.2f}x - a lower ratio means the company relies less on borrowed capital relative "
        f"to shareholder funds, which typically means more resilience in a downturn ({_qualifier(strength, 'leverage reading')}).",
        direction,
    )


def net_debt_to_ebitda_signal(ratio: float) -> Signal:
    """Lower is better. Bands follow the common analyst convention: <1x conservative, >3.5x high leverage concern."""
    if ratio < 1.0:
        delta = 15.0
    elif ratio < 2.0:
        delta = 5.0
    elif ratio < 3.5:
        delta = -5.0
    else:
        delta = -15.0
    direction = 1 if ratio < 2.0 else (-1 if ratio >= 3.5 else 0)
    strength = classify_strength(delta)
    return Signal(
        "net_debt_to_ebitda",
        ratio,
        delta,
        f"Net Debt/EBITDA is {ratio:.2f}x - this measures how many years of current EBITDA it would take to pay "
        f"off net debt; lower is safer ({_qualifier(strength, 'leverage reading')}).",
        direction,
        "x",
    )


def interest_coverage_signal(coverage: float) -> Signal:
    """Higher is better. Bands follow the common analyst convention: >=8x very safe, <1.5x borderline/at risk."""
    if coverage >= 8.0:
        delta = 15.0
    elif coverage >= 4.0:
        delta = 5.0
    elif coverage >= 1.5:
        delta = -5.0
    else:
        delta = -15.0
    direction = 1 if coverage >= 4.0 else (-1 if coverage < 1.5 else 0)
    strength = classify_strength(delta)
    return Signal(
        "interest_coverage",
        coverage,
        delta,
        f"Interest coverage is {coverage:.1f}x - this measures how many times over EBIT covers the interest "
        f"bill; a higher multiple means much more cushion before debt payments become a strain "
        f"({_qualifier(strength, 'leverage reading')}).",
        direction,
        "x",
    )


def current_ratio_signal(ratio: float) -> Signal:
    """Higher is better (liquidity). Bands follow the common convention: >=2.0 healthy, <1.0 liquidity risk."""
    if ratio >= 2.0:
        delta = 10.0
    elif ratio >= 1.2:
        delta = 5.0
    elif ratio >= 1.0:
        delta = -5.0
    else:
        delta = -10.0
    direction = 1 if ratio >= 1.2 else (-1 if ratio < 1.0 else 0)
    strength = classify_strength(delta)
    return Signal(
        "current_ratio",
        ratio,
        delta,
        f"Current ratio is {ratio:.2f}x - current assets cover current liabilities by this multiple; below 1.0x "
        f"means short-term obligations exceed short-term resources ({_qualifier(strength, 'liquidity reading')}).",
        direction,
        "x",
    )


def score_leverage_points(
    *,
    debt_to_equity: float | None,
    net_debt_to_ebitda: float | None,
    interest_coverage: float | None = None,
    current_ratio: float | None = None,
) -> tuple[float | None, list[Signal]]:
    signals: list[Signal] = []
    if debt_to_equity is not None:
        signals.append(debt_to_equity_signal(debt_to_equity))
    if net_debt_to_ebitda is not None:
        signals.append(net_debt_to_ebitda_signal(net_debt_to_ebitda))
    if interest_coverage is not None:
        signals.append(interest_coverage_signal(interest_coverage))
    if current_ratio is not None:
        signals.append(current_ratio_signal(current_ratio))
    if not signals:
        return None, []
    return clamp_score(50.0 + sum(s.delta for s in signals)), signals


def asset_turnover_signal(turnover: float) -> Signal:
    """Higher is better (more revenue generated per unit of assets). Sector-agnostic bands - a documented
    simplification (see SCORING.md): capital-light businesses (e.g. IT services) will naturally score higher
    here than capital-intensive ones, independent of either being a "better" business."""
    if turnover >= 1.0:
        delta = 15.0
    elif turnover >= 0.5:
        delta = 5.0
    elif turnover >= 0.2:
        delta = -5.0
    else:
        delta = -15.0
    direction = 1 if turnover >= 0.5 else (-1 if turnover < 0.2 else 0)
    strength = classify_strength(delta)
    return Signal(
        "asset_turnover",
        turnover,
        delta,
        f"Asset turnover is {turnover:.2f}x - the company generates {turnover:.2f} rupees of revenue per rupee "
        f"of total assets each period; higher means more efficient use of its asset base, though this varies "
        f"a lot by sector ({_qualifier(strength, 'efficiency reading')}).",
        direction,
        "x",
    )


def score_efficiency_points(*, asset_turnover: float | None) -> tuple[float | None, list[Signal]]:
    signals: list[Signal] = []
    if asset_turnover is not None:
        signals.append(asset_turnover_signal(asset_turnover))
    if not signals:
        return None, []
    return clamp_score(50.0 + sum(s.delta for s in signals)), signals


# Combination weights for the standalone Fundamental Score (SCORING.md
# "Fundamental Score" section) - single source of truth for both
# `packages/scoring/components.py::score_fundamentals` (the Research
# Score's "fundamentals" component) and
# `apps/api/routes/fundamentals.py::get_fundamentals` (the standalone
# `fundamental_score` block) - both call `compute_fundamental_score`
# below, never a duplicated calculation.
FUNDAMENTAL_SUBSCORE_WEIGHTS: dict[str, float] = {
    "growth": 0.35,
    "profitability": 0.35,
    "leverage": 0.20,
    "efficiency": 0.10,
}
assert abs(sum(FUNDAMENTAL_SUBSCORE_WEIGHTS.values()) - 1.0) < 1e-9, "FUNDAMENTAL_SUBSCORE_WEIGHTS must sum to 1.0"


@dataclass(frozen=True)
class FundamentalSubScores:
    """Output of `compute_fundamental_score` - every sub-score is `None` (never 0/50) when none of its
    inputs were available, exactly like a `ComponentResult` with `available=False` (SCORING.md section 4's
    missing-component renormalization, applied one level down)."""

    growth: float | None
    profitability: float | None
    leverage: float | None
    efficiency: float | None
    overall: float | None
    signals: tuple[Signal, ...]


def compute_fundamental_score(
    *,
    revenue_growth_yoy: float | None,
    pat_growth_yoy: float | None,
    eps_growth_yoy: float | None,
    roe: float | None,
    roce: float | None,
    roa: float | None = None,
    net_profit_margin: float | None = None,
    debt_to_equity: float | None = None,
    net_debt_to_ebitda: float | None = None,
    interest_coverage: float | None = None,
    current_ratio: float | None = None,
    asset_turnover: float | None = None,
) -> FundamentalSubScores:
    """The one Fundamental Score computation - see module comment above `FUNDAMENTAL_SUBSCORE_WEIGHTS`.

    Renormalizes over only the sub-scores that produced a real number
    (identical convention to `packages/scoring/aggregate.py::aggregate_components`,
    just applied to 4 sub-scores instead of 8 components): if a
    sub-score is `None` (e.g. "leverage" because neither provider had
    `interest_expense`/`current_assets` for this instrument), its weight
    is excluded from both the numerator and denominator - never treated
    as 0 or as a neutral 50. If every sub-score is `None`, `overall` is
    `None`.
    """
    growth_score, growth_signals = score_growth_points(
        revenue_growth_yoy=revenue_growth_yoy, pat_growth_yoy=pat_growth_yoy, eps_growth_yoy=eps_growth_yoy
    )
    profitability_score, profitability_signals = score_profitability_points(
        roe=roe, roce=roce, roa=roa, net_profit_margin=net_profit_margin
    )
    leverage_score, leverage_signals = score_leverage_points(
        debt_to_equity=debt_to_equity,
        net_debt_to_ebitda=net_debt_to_ebitda,
        interest_coverage=interest_coverage,
        current_ratio=current_ratio,
    )
    efficiency_score, efficiency_signals = score_efficiency_points(asset_turnover=asset_turnover)

    sub_scores = {
        "growth": growth_score,
        "profitability": profitability_score,
        "leverage": leverage_score,
        "efficiency": efficiency_score,
    }
    available_weight = sum(
        FUNDAMENTAL_SUBSCORE_WEIGHTS[name] for name, value in sub_scores.items() if value is not None
    )
    overall: float | None = None
    if available_weight > 0:
        overall = (
            sum(
                (value if value is not None else 0.0) * FUNDAMENTAL_SUBSCORE_WEIGHTS[name]
                for name, value in sub_scores.items()
                if value is not None
            )
            / available_weight
        )

    all_signals = (*growth_signals, *profitability_signals, *leverage_signals, *efficiency_signals)
    return FundamentalSubScores(
        growth=growth_score,
        profitability=profitability_score,
        leverage=leverage_score,
        efficiency=efficiency_score,
        overall=overall,
        signals=all_signals,
    )


# --- Risk Quality (10%) -----------------------------------------------------


def atr_pct_signal(atr_pct: float) -> Signal:
    if atr_pct < 1.5:
        s = Signal(
            "atr_pct",
            atr_pct,
            15.0,
            f"ATR is {atr_pct:.1f}% of price - low volatility. Average True Range measures typical daily price "
            f"swings; a tight range like this means more predictable, easier-to-size price moves.",
            +1,
            "pct",
        )
    elif atr_pct < 3.0:
        s = Signal(
            "atr_pct",
            atr_pct,
            5.0,
            f"ATR is {atr_pct:.1f}% of price - moderate volatility. Typical daily price swings are in a normal, "
            f"unremarkable range for an actively traded stock.",
            0,
            "pct",
        )
    elif atr_pct < 5.0:
        s = Signal(
            "atr_pct",
            atr_pct,
            -5.0,
            f"ATR is {atr_pct:.1f}% of price - elevated volatility. Typical daily price swings are wider than "
            f"usual, which raises the risk of being stopped out by noise rather than a real trend change.",
            -1,
            "pct",
        )
    else:
        s = Signal(
            "atr_pct",
            atr_pct,
            -15.0,
            f"ATR is {atr_pct:.1f}% of price - high volatility. Typical daily price swings are large relative "
            f"to price, which makes position sizing and risk management materially harder.",
            -1,
            "pct",
        )
    return s


def rolling_volatility_signal(vol_pct: float) -> Signal:
    if vol_pct < 20.0:
        s = Signal(
            "rolling_volatility_20d_pct",
            vol_pct,
            15.0,
            f"20-day annualized volatility is {vol_pct:.1f}% - low. The stock has traded in an unusually calm "
            f"range over the last month relative to typical equity volatility.",
            +1,
            "pct",
        )
    elif vol_pct < 35.0:
        s = Signal(
            "rolling_volatility_20d_pct",
            vol_pct,
            0.0,
            f"20-day annualized volatility is {vol_pct:.1f}% - moderate. In line with typical equity volatility "
            f"over the last month.",
            0,
            "pct",
        )
    elif vol_pct < 50.0:
        s = Signal(
            "rolling_volatility_20d_pct",
            vol_pct,
            -10.0,
            f"20-day annualized volatility is {vol_pct:.1f}% - elevated. The stock has been noticeably more "
            f"turbulent than typical over the last month.",
            -1,
            "pct",
        )
    else:
        s = Signal(
            "rolling_volatility_20d_pct",
            vol_pct,
            -20.0,
            f"20-day annualized volatility is {vol_pct:.1f}% - high. The stock has been exceptionally turbulent "
            f"over the last month, well outside a typical range.",
            -1,
            "pct",
        )
    return s


def max_drawdown_signal(max_drawdown_pct: float) -> Signal:
    """`max_drawdown_pct` is <= 0 (e.g. -35.0 means a 35% drawdown)."""
    dd = abs(max_drawdown_pct)
    if dd < 15.0:
        s = Signal(
            "max_drawdown_pct",
            max_drawdown_pct,
            10.0,
            f"Max drawdown over available history is {max_drawdown_pct:.1f}% - shallow. A smaller worst-case "
            f"peak-to-trough decline has historically made this stock easier to hold through downturns.",
            +1,
            "pct",
        )
    elif dd < 30.0:
        s = Signal(
            "max_drawdown_pct",
            max_drawdown_pct,
            0.0,
            f"Max drawdown over available history is {max_drawdown_pct:.1f}% - moderate. A typical worst-case "
            f"decline for an actively traded equity.",
            0,
            "pct",
        )
    elif dd < 50.0:
        s = Signal(
            "max_drawdown_pct",
            max_drawdown_pct,
            -10.0,
            f"Max drawdown over available history is {max_drawdown_pct:.1f}% - deep. A sizeable worst-case "
            f"decline that would have tested most holders' conviction.",
            -1,
            "pct",
        )
    else:
        s = Signal(
            "max_drawdown_pct",
            max_drawdown_pct,
            -20.0,
            f"Max drawdown over available history is {max_drawdown_pct:.1f}% - severe. A very large worst-case "
            f"decline, historically a difficult stock to hold through its worst stretch.",
            -1,
            "pct",
        )
    return s


def score_risk_quality_points(
    *,
    atr_pct: float | None,
    rolling_volatility_pct: float | None,
    max_drawdown_pct: float | None,
) -> tuple[float, list[Signal]]:
    signals: list[Signal] = []
    if atr_pct is not None:
        signals.append(atr_pct_signal(atr_pct))
    if rolling_volatility_pct is not None:
        signals.append(rolling_volatility_signal(rolling_volatility_pct))
    if max_drawdown_pct is not None:
        signals.append(max_drawdown_signal(max_drawdown_pct))

    score = clamp_score(50.0 + sum(s.delta for s in signals))
    return score, signals


# --- Sector Relative Strength (10%) -----------------------------------------


def sector_relative_strength_signal(relative_strength_pct: float) -> Signal:
    delta = max(-40.0, min(40.0, relative_strength_pct))
    direction = 1 if relative_strength_pct > 0 else (-1 if relative_strength_pct < 0 else 0)
    strength = classify_strength(delta)
    verb = "outperforming" if relative_strength_pct >= 0 else "underperforming"
    return Signal(
        "sector_relative_strength_3m_pct",
        relative_strength_pct,
        delta,
        f"3-month return is {relative_strength_pct:+.1f} percentage points vs sector peers - the stock is "
        f"{verb} its sector peer group, often a sign of changing competitive dynamics or capital rotation "
        f"({_qualifier(strength, 'relative-strength gap')}).",
        direction,
        "pp",
    )


def score_sector_relative_strength_points(relative_strength_pct: float) -> tuple[float, Signal]:
    signal = sector_relative_strength_signal(relative_strength_pct)
    return clamp_score(50.0 + signal.delta), signal


# --- Valuation (10%) --------------------------------------------------------


def valuation_percentile_signal(metric_name: str, label: str, percentile_cheaper: float) -> Signal:
    """`percentile_cheaper` in [0, 100]: % of the seeded universe this stock is cheaper than."""
    delta = (percentile_cheaper - 50.0) * 0.6  # scaled to +-30
    direction = 1 if percentile_cheaper > 50.0 else (-1 if percentile_cheaper < 50.0 else 0)
    strength = classify_strength(delta)
    descriptor = "a discount to" if percentile_cheaper > 50.0 else ("a premium to" if percentile_cheaper < 50.0 else "in line with")
    return Signal(
        metric_name,
        percentile_cheaper,
        delta,
        f"{label} is cheaper than {percentile_cheaper:.0f}% of the seeded universe - the market is pricing this "
        f"stock at {descriptor} its peers on this metric, which can reflect genuine undervaluation or a "
        f"legitimate quality/growth gap ({_qualifier(strength, 'valuation gap')}).",
        direction,
        "percentile",
    )


def score_valuation_points(percentiles: dict[str, float]) -> tuple[float, list[Signal]]:
    """`percentiles`: metric_name -> percentile_cheaper (0-100), only for computable metrics."""
    labels = {"pe_percentile": "P/E", "pb_percentile": "P/B", "ev_ebitda_percentile": "EV/EBITDA"}
    signals = [valuation_percentile_signal(name, labels[name], pct) for name, pct in percentiles.items() if name in labels]
    score = clamp_score(50.0 + sum(s.delta for s in signals))
    return score, signals


# --- Market Regime (10%) ----------------------------------------------------

REGIME_BASELINE_SCORES: dict[str, float] = {
    "BULLISH_TREND": 85.0,
    "LOW_VOLATILITY": 60.0,
    "SIDEWAYS": 50.0,
    "TRANSITION": 50.0,
    "HIGH_VOLATILITY": 40.0,
    "BEARISH_TREND": 20.0,
}

_REGIME_CONTEXT: dict[str, str] = {
    "BULLISH_TREND": "broad market breadth and trend are both favorable, a backdrop that has historically lifted most stocks regardless of their own fundamentals",
    "LOW_VOLATILITY": "the market is calm and range-bound with a mild upward bias",
    "SIDEWAYS": "the market lacks a clear directional trend",
    "TRANSITION": "the market is shifting between regimes and its near-term direction is unsettled",
    "HIGH_VOLATILITY": "the market is choppy and turbulent, a backdrop that tends to punish most stocks regardless of their own fundamentals",
    "BEARISH_TREND": "broad market breadth and trend are both unfavorable, a backdrop that has historically weighed on most stocks regardless of their own fundamentals",
}


def market_regime_signal(regime_label: str, as_of_date: str) -> Signal:
    score = REGIME_BASELINE_SCORES[regime_label]
    delta = score - 50.0
    direction = 1 if score > 55 else (-1 if score < 45 else 0)
    strength = classify_strength(delta)
    context = _REGIME_CONTEXT.get(regime_label, "")
    return Signal(
        "market_regime",
        score,
        delta,
        f"The broader market regime is {regime_label} as of {as_of_date} - {context} "
        f"({_qualifier(strength, 'market condition')}).",
        direction,
    )
