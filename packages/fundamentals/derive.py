"""Derived fundamental & valuation metrics (SPEC.md sections 12, 13).

Every function here is pure (no I/O, no DB, no provider calls) and takes
plain `float | None` inputs so each is independently unit-testable with
synthetic numbers - see `tests/unit/fundamentals/test_derive.py`.

Rules enforced throughout (SPEC.md section 81 rule 8, section 2.3):
- A missing input always produces `None` output, never 0 and never a
  fabricated default.
- A zero/invalid denominator always produces `None`, never raises
  `ZeroDivisionError` and never returns `inf`/`nan`.
- Growth metrics need >= 2 periods; with only one period available they
  are `None`, never 0 (0 would wrongly imply "no growth" rather than
  "unknown").

## Documented simplifications

- **ROCE** conventionally divides EBIT by `total assets - current
  liabilities`. yfinance's standardized financials do not expose
  current-vs-non-current liability granularity for most NSE tickers, so
  this module uses the common analyst proxy
  `capital_employed = equity + total_debt` instead. This is a documented
  simplification (SPEC.md section 12), not a different metric - see
  `roce_simplified`.
- **Operating margin** uses EBIT (not EBITDA) as the numerator -
  `operating_margin = ebit / revenue` - documented here as the single
  choice used consistently across this codebase.
- **P/E** and **EV/EBITDA** are defined as `None` (not a negative or
  near-infinite number) when the denominator (EPS, EBITDA) is <= 0: a
  loss-making company's P/E/EV-EBITDA is not a meaningful valuation
  signal, and returning a nonsensical number would violate the
  "never fabricate" rule just as much as returning 0 would.
- **Interest coverage** (`ebit / interest_expense`) and **current ratio**
  (`current_assets / current_liabilities`) use the raw
  `fundamental_snapshots.interest_expense` /
  `.current_assets` / `.current_liabilities` columns (migration
  `b7a1c9d4e821`), empirically confirmed available from yfinance's
  `income_stmt`/`balance_sheet`. `interest_expense` is present for every
  NSE company tested (Oct 2026), including banks (HDFCBANK). `current_assets`/
  `current_liabilities` are present for non-financial companies
  (RELIANCE, TCS, ITC, INFY) but **genuinely absent for banks**
  (HDFCBANK's balance sheet has no current/non-current split at all - a
  real structural difference, not a coverage gap) - see
  DATA_SOURCES.md. Missing stays `None`, never fabricated.
- **Quick ratio is not implemented**: it needs an inventory figure, which
  neither yfinance's nor tradingview_ta's exposed fields for NSE tickers
  reliably provide - a documented, honest gap (SCORING.md "Known
  limitations"), not a silently-wrong approximation.
- **ROA**, **net profit margin**, **asset turnover** and **financial
  leverage** all reuse raw fields this schema already had before this
  refactor (`pat`, `revenue`, `total_assets`, `equity`) - no new raw
  columns were needed for these four.
- **PEG ratio** (`pe / (eps_growth_yoy * 100)`) is `None` whenever EPS
  growth is `<= 0`: PEG is conventionally undefined/not meaningful for a
  shrinking-or-flat-earnings company, same rationale as the P/E-null-on-
  loss-making-company rule above. This codebase only has trailing EPS
  growth (not a forward estimate), which is a documented approximation,
  not the analyst-consensus-forward-estimate PEG some data vendors
  compute.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Fundamentals staleness decay window (SPEC.md section 12: "do not
# calculate valuation using stale fundamentals without marking the data
# age"). Below FRESH_DAYS, data is considered fully fresh (score 100).
# At or beyond STALE_FLOOR_DAYS, freshness bottoms out at 0. Linear decay
# in between. These thresholds are a documented product choice (annual
# reports are expected roughly once a year; two years with no update is
# treated as fully stale), not an empirically derived constant.
FUNDAMENTALS_FRESH_DAYS = 90
FUNDAMENTALS_STALE_FLOOR_DAYS = 720


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """`numerator / denominator`, or `None` if either input is missing or `denominator == 0`."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def find_year_ago_period_end(period_ends: list[date], latest_period_end: date, tolerance_days: int = 20) -> date | None:
    """Find the entry in `period_ends` closest to one year before `latest_period_end`.

    Used for quarterly YoY: the "same quarter last year" is not reliably
    "4 rows back" if a quarter is missing from the provider's history, so
    this matches by date proximity instead of position. `None` if nothing
    in `period_ends` falls within `tolerance_days` of the target date -
    never guesses a wrong quarter. The tolerance (rather than an exact
    match) accommodates quarter-end dates drifting a few days across
    providers/years.
    """
    target = date(latest_period_end.year - 1, latest_period_end.month, latest_period_end.day)
    candidates = [d for d in period_ends if d != latest_period_end]
    if not candidates:
        return None
    closest = min(candidates, key=lambda d: abs((d - target).days))
    if abs((closest - target).days) > tolerance_days:
        return None
    return closest


def is_at_all_time_high(current: float | None, history: list[float | None]) -> bool | None:
    """Whether `current` is the highest value in `history` (which must include `current` itself).

    `None` if `current` is missing or `history` has no comparable
    (non-`None`) values - never `False` for "we don't know". The
    "all-time" label is only as good as what `history` actually covers -
    callers must surface how many periods that is (e.g.
    `apps/api/routes/fundamentals.py`'s `quarters_available`) rather than
    implying true since-listing history when the series is short.
    """
    if current is None:
        return None
    values = [v for v in history if v is not None]
    if not values:
        return None
    return current >= max(values)


def growth_yoy(current: float | None, previous: float | None) -> float | None:
    """Year-over-year growth rate: `(current - previous) / abs(previous)`.

    `None` (not 0) if either period is missing or `previous == 0` (percent
    growth off a zero base is undefined, not "infinite growth" or "no
    growth"). Using `abs(previous)` ensures correct directional growth when
    a company goes from a loss to a profit. Downside is capped at -1.0 (-100%)
    to prevent confusing numbers like -300% when profits cross into steep losses.
    """
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def roe(pat: float | None, equity: float | None) -> float | None:
    """Return on Equity: `pat / equity`."""
    return _safe_div(pat, equity)


def roce_simplified(ebit: float | None, equity: float | None, total_debt: float | None) -> float | None:
    """Simplified ROCE: `ebit / (equity + total_debt)`.

    See module docstring "Documented simplifications" - this substitutes
    `equity + total_debt` for the conventional `total assets - current
    liabilities` because current-liability granularity isn't available.
    """
    if equity is None or total_debt is None:
        return None
    capital_employed = equity + total_debt
    return _safe_div(ebit, capital_employed)


def debt_to_equity(total_debt: float | None, equity: float | None) -> float | None:
    return _safe_div(total_debt, equity)


def net_debt_to_ebitda(total_debt: float | None, cash: float | None, ebitda: float | None) -> float | None:
    """`(total_debt - cash) / ebitda`. `None` if ebitda is missing or <= 0."""
    if total_debt is None or cash is None or ebitda is None or ebitda <= 0:
        return None
    return (total_debt - cash) / ebitda


def operating_margin(ebit: float | None, revenue: float | None) -> float | None:
    """`ebit / revenue` - see module docstring for why EBIT (not EBITDA) is used."""
    return _safe_div(ebit, revenue)


def fcf_margin(free_cash_flow: float | None, revenue: float | None) -> float | None:
    return _safe_div(free_cash_flow, revenue)


def return_on_assets(pat: float | None, total_assets: float | None) -> float | None:
    """ROA: `pat / total_assets`. Lower-magnitude bands than ROE, since total assets >= equity - see
    `packages/scoring/signals.py::roa_signal`."""
    return _safe_div(pat, total_assets)


def net_profit_margin(pat: float | None, revenue: float | None) -> float | None:
    """`pat / revenue` - the share of revenue that reaches the bottom line."""
    return _safe_div(pat, revenue)


def asset_turnover(revenue: float | None, total_assets: float | None) -> float | None:
    """`revenue / total_assets` - revenue generated per unit of total assets. Sector-agnostic, a
    documented simplification (see `packages/scoring/signals.py::asset_turnover_signal`)."""
    return _safe_div(revenue, total_assets)


def financial_leverage(total_assets: float | None, equity: float | None) -> float | None:
    """`total_assets / equity`. Exposed for transparency only - not part of the Fundamental Score
    (Debt/Equity and Net Debt/EBITDA already capture leverage risk; this would double-count it),
    same pattern as `ebitda_growth_yoy` (SCORING.md section 3.3)."""
    return _safe_div(total_assets, equity)


def interest_coverage(ebit: float | None, interest_expense: float | None) -> float | None:
    """`ebit / interest_expense`. `None` if `interest_expense` is missing or <= 0 (a non-positive
    interest expense isn't a meaningful denominator for this ratio)."""
    if ebit is None or interest_expense is None or interest_expense <= 0:
        return None
    return ebit / interest_expense


def current_ratio(current_assets: float | None, current_liabilities: float | None) -> float | None:
    """`current_assets / current_liabilities`. `None` if `current_liabilities` is missing or <= 0."""
    if current_assets is None or current_liabilities is None or current_liabilities <= 0:
        return None
    return current_assets / current_liabilities


def peg_ratio(pe: float | None, eps_growth_yoy: float | None) -> float | None:
    """`pe / (eps_growth_yoy * 100)`. `None` if `pe` is missing or `eps_growth_yoy` is missing/<=0 -
    see module docstring "Documented simplifications" for why a non-positive growth rate makes PEG
    undefined here, same rationale as the P/E-null-on-loss-making-company rule."""
    if pe is None or eps_growth_yoy is None or eps_growth_yoy <= 0:
        return None
    return pe / (eps_growth_yoy * 100.0)


def fundamentals_data_age_days(period_end: date, as_of: date) -> int:
    """Calendar days between a fundamentals period end and `as_of`. Always >= 0 for sane inputs."""
    return (as_of - period_end).days


def fundamentals_freshness_score(data_age_days: int) -> float:
    """0-100 freshness score from fundamentals data age, per the decay window above.

    100 while `data_age_days <= FUNDAMENTALS_FRESH_DAYS`, linearly decaying
    to 0 at `FUNDAMENTALS_STALE_FLOOR_DAYS`, floored at 0 beyond that.
    Used by the scoring engine's confidence calculation (SCORING.md).
    """
    if data_age_days <= FUNDAMENTALS_FRESH_DAYS:
        return 100.0
    if data_age_days >= FUNDAMENTALS_STALE_FLOOR_DAYS:
        return 0.0
    span = FUNDAMENTALS_STALE_FLOOR_DAYS - FUNDAMENTALS_FRESH_DAYS
    return 100.0 * (1.0 - (data_age_days - FUNDAMENTALS_FRESH_DAYS) / span)


@dataclass(frozen=True)
class ValuationMetrics:
    """P/E, P/B, EV/EBITDA, EV/Sales, dividend yield, FCF yield - all `None`-safe.

    `data_age_days`/`stale` describe the age of the *fundamentals* input
    used (price is always the latest available close) - SPEC.md section
    12: "do not calculate valuation using stale fundamentals without
    marking the data age."
    """

    pe: float | None
    pb: float | None
    ev_ebitda: float | None
    ev_sales: float | None
    dividend_yield: float | None
    fcf_yield: float | None
    market_cap: float | None
    enterprise_value: float | None
    data_age_days: int | None
    stale: bool


def compute_valuation_metrics(
    *,
    close_price: float,
    period_end: date | None,
    as_of: date,
    eps: float | None,
    equity: float | None,
    shares_outstanding: float | None,
    revenue: float | None,
    ebitda: float | None,
    total_debt: float | None,
    cash: float | None,
    free_cash_flow: float | None,
    dividend_yield: float | None,
    stale_after_days: int = 365,
) -> ValuationMetrics:
    """Combine the latest close price with the latest fundamentals snapshot.

    `period_end=None` (no fundamentals snapshot at all) produces every
    price*fundamentals-derived field as `None` - the dividend yield field
    is still passed through if the caller has it from elsewhere, though
    in practice it travels with the snapshot too.
    """
    data_age_days = fundamentals_data_age_days(period_end, as_of) if period_end is not None else None
    stale = data_age_days is not None and data_age_days > stale_after_days

    market_cap = close_price * shares_outstanding if shares_outstanding else None

    pe = None
    if eps is not None and eps > 0:
        pe = close_price / eps

    book_value_per_share = _safe_div(equity, shares_outstanding)
    pb = _safe_div(close_price, book_value_per_share)

    enterprise_value = None
    if market_cap is not None and total_debt is not None and cash is not None:
        enterprise_value = market_cap + total_debt - cash

    ev_ebitda = None
    if enterprise_value is not None and ebitda is not None and ebitda > 0:
        ev_ebitda = enterprise_value / ebitda

    ev_sales = _safe_div(enterprise_value, revenue)
    fcf_yield = _safe_div(free_cash_flow, market_cap)

    return ValuationMetrics(
        pe=pe,
        pb=pb,
        ev_ebitda=ev_ebitda,
        ev_sales=ev_sales,
        dividend_yield=dividend_yield,
        fcf_yield=fcf_yield,
        market_cap=market_cap,
        enterprise_value=enterprise_value,
        data_age_days=data_age_days,
        stale=stale,
    )
