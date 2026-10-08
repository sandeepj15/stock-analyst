"""Fundamentals endpoint (SPEC.md sections 12, 13, 48/49, Phase 3).

`GET /api/v1/stocks/{symbol}/fundamentals` - raw latest reported snapshot
+ every derived/valuation metric from `packages/fundamentals/derive.py`,
each tagged with its own data age. Every field is `null` (never 0, never
"N/A" treated as a number) when the provider didn't have it - SPEC.md
section 81 rule 8. This is expected to happen often for Indian/NSE
tickers on yfinance (see DATA_SOURCES.md) and must be a visible,
explicit state, not a silent gap.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import resolve_instrument_or_404
from packages.common.db import get_db_session
from packages.fundamentals.derive import (
    asset_turnover,
    compute_valuation_metrics,
    current_ratio,
    debt_to_equity,
    fcf_margin,
    financial_leverage,
    find_year_ago_period_end,
    fundamentals_data_age_days,
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
from packages.fundamentals.models import FundamentalSnapshot
from packages.market_data.history import load_ohlcv_dataframe
from packages.scoring.bands import score_band
from packages.scoring.constants import FUNDAMENTAL_SCORE_METHODOLOGY_VERSION
from packages.scoring.signals import compute_fundamental_score

router = APIRouter(prefix="/api/v1/stocks", tags=["fundamentals"])

STALE_FUNDAMENTALS_AFTER_DAYS = 365


def _f(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


class RawFundamentalsOut(BaseModel):
    period_end: str | None
    period_type: str | None
    revenue: float | None
    ebitda: float | None
    ebit: float | None
    pat: float | None
    eps: float | None
    operating_cash_flow: float | None
    free_cash_flow: float | None
    total_assets: float | None
    total_liabilities: float | None
    total_debt: float | None
    cash: float | None
    equity: float | None
    shares_outstanding: float | None
    dividend_yield: float | None
    # Added for the Fundamental Score's Leverage sub-score (SCORING.md).
    # `interest_expense` is available for most companies, including
    # banks. `current_assets`/`current_liabilities` are genuinely `null`
    # for banks specifically (no current/non-current balance-sheet
    # split) and for any other instrument where neither provider had the
    # field (a real data gap, see DATA_SOURCES.md), never a fabricated 0.
    interest_expense: float | None
    current_assets: float | None
    current_liabilities: float | None
    source: str | None
    source_timestamp: str | None
    data_age_days: int | None


class DerivedMetricsOut(BaseModel):
    revenue_growth_yoy: float | None
    ebitda_growth_yoy: float | None
    pat_growth_yoy: float | None
    eps_growth_yoy: float | None
    roe: float | None
    roce_simplified: float | None
    debt_to_equity: float | None
    net_debt_to_ebitda: float | None
    operating_margin: float | None
    fcf_margin: float | None
    # New derived metrics (SCORING.md "Fundamental Score"). `roa`,
    # `net_profit_margin`, `asset_turnover` and `financial_leverage` reuse
    # raw fields this schema already had (pat/revenue/total_assets/
    # equity) - no new raw columns needed for these four.
    # `interest_coverage`/`current_ratio` need the new raw fields above
    # and are `null` wherever those are unavailable - `current_ratio` in
    # particular is structurally unavailable for banks (see DATA_SOURCES.md).
    # `financial_leverage` and `peg_ratio` are exposed for transparency
    # only - neither is part of the Fundamental Score (see derive.py).
    roa: float | None
    net_profit_margin: float | None
    asset_turnover: float | None
    financial_leverage: float | None
    interest_coverage: float | None
    current_ratio: float | None
    peg_ratio: float | None


class ValuationMetricsOut(BaseModel):
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


class FundamentalSubScoresOut(BaseModel):
    growth: float | None
    profitability: float | None
    leverage: float | None
    efficiency: float | None


class FundamentalScoreOut(BaseModel):
    """SCORING.md "Fundamental Score" - computed by the exact same
    `packages.scoring.signals.compute_fundamental_score` call used by
    `packages/scoring/components.py::score_fundamentals` (the Research
    Score's "fundamentals" component), from the exact same derived
    inputs - guaranteed to equal that component's score for the same
    instrument/snapshot (single source of truth, see
    `tests/unit/scoring/test_fundamental_score.py`)."""

    overall: float | None
    band: str | None
    sub_scores: FundamentalSubScoresOut
    methodology_version: str


class QuarterlyPointOut(BaseModel):
    period_end: str
    revenue: float | None
    pat: float | None
    revenue_growth_yoy: float | None
    pat_growth_yoy: float | None


class QuarterlyFundamentalsOut(BaseModel):
    """Quarterly Revenue/PAT trend + all-time-high flags (`period_type="Q"`, yfinance).

    `quarters_available` is the honest scope of `*_at_all_time_high`:
    yfinance's quarterly statements typically expose only the trailing
    ~4-6 quarters for NSE tickers (see
    `YFinanceQuarterlyFundamentalProvider`'s docstring), so a `True` flag
    here means "highest of the `quarters_available` quarters we have",
    never a claim of true since-listing history.
    """

    points: list[QuarterlyPointOut]
    quarters_available: int
    revenue_at_all_time_high: bool | None
    pat_at_all_time_high: bool | None
    latest_period_end: str | None
    source: str | None
    data_age_days: int | None


class FundamentalsResponse(BaseModel):
    symbol: str
    exchange: str
    as_of: str
    has_fundamental_data: bool
    message: str | None
    raw: RawFundamentalsOut
    derived: DerivedMetricsOut
    valuation: ValuationMetricsOut
    fundamental_score: FundamentalScoreOut
    quarterly: QuarterlyFundamentalsOut | None


async def _latest_two_snapshots(session: AsyncSession, instrument_id: object) -> list[FundamentalSnapshot]:
    """Latest two FY/TTM snapshots - this is the Raw/Derived/Valuation section's data, never quarterly.

    Must exclude `period_type="Q"` explicitly: a quarter's `period_end`
    (e.g. 2026-06-30) can be more recent than the latest annual
    `period_end` (e.g. 2026-03-31), so without this filter the newest
    quarterly row would be picked up here and mislabeled as the annual
    snapshot - corrupting both the headline numbers and "YoY" (which
    would silently become quarter-over-quarter). Quarterly data has its
    own independent query (`_all_quarterly_snapshots`) and response
    section (`quarterly`).
    """
    stmt = (
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.instrument_id == instrument_id, FundamentalSnapshot.period_type != "Q")
        .order_by(FundamentalSnapshot.period_end.desc())
        .limit(2)
    )
    return list((await session.execute(stmt)).scalars().all())


# Preference order when more than one quarterly source has a row for the
# same period_end. `source` is part of the DB's unique key (see
# packages/fundamentals/models.py), so screener.in and yfinance rows for
# an overlapping quarter are never the same row - both get persisted.
# screener.in wins (it's the configured quarterly primary, see
# packages/fundamentals/factory.py::get_quarterly_fundamental_provider) -
# yfinance is only used here for quarters screener.in didn't report.
QUARTERLY_SOURCE_PRIORITY: tuple[str, ...] = ("screener_in", "yfinance")


def _dedupe_quarterly_by_period(rows: list[FundamentalSnapshot]) -> list[FundamentalSnapshot]:
    """Collapse multiple sources' rows for the same quarter to one, per `QUARTERLY_SOURCE_PRIORITY`."""

    def _rank(source: str | None) -> int:
        return QUARTERLY_SOURCE_PRIORITY.index(source) if source in QUARTERLY_SOURCE_PRIORITY else len(QUARTERLY_SOURCE_PRIORITY)

    by_period: dict[date, FundamentalSnapshot] = {}
    for row in rows:
        existing = by_period.get(row.period_end)
        if existing is None or _rank(row.source) < _rank(existing.source):
            by_period[row.period_end] = row
    return sorted(by_period.values(), key=lambda r: r.period_end, reverse=True)


async def _all_quarterly_snapshots(session: AsyncSession, instrument_id: object) -> list[FundamentalSnapshot]:
    """Every stored `period_type="Q"` snapshot for this instrument, deduped to one row per quarter, most recent first.

    Unlike `_latest_two_snapshots`, this is unbounded - the all-time-high
    flags need every quarter we have, not just the latest two.
    """
    stmt = (
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.instrument_id == instrument_id, FundamentalSnapshot.period_type == "Q")
        .order_by(FundamentalSnapshot.period_end.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return _dedupe_quarterly_by_period(rows)


def _build_quarterly_response(quarterly_snapshots: list[FundamentalSnapshot], now: datetime) -> QuarterlyFundamentalsOut | None:
    if not quarterly_snapshots:
        return None

    ascending = list(reversed(quarterly_snapshots))  # oldest -> newest, for trend display and YoY lookups
    period_ends = [snap.period_end for snap in ascending]
    revenues = [_f(snap.revenue) for snap in ascending]
    pats = [_f(snap.pat) for snap in ascending]

    points: list[QuarterlyPointOut] = []
    for i, snap in enumerate(ascending):
        year_ago_end = find_year_ago_period_end(period_ends, snap.period_end)
        year_ago_idx = period_ends.index(year_ago_end) if year_ago_end is not None else None
        points.append(
            QuarterlyPointOut(
                period_end=snap.period_end.isoformat(),
                revenue=revenues[i],
                pat=pats[i],
                revenue_growth_yoy=growth_yoy(revenues[i], revenues[year_ago_idx]) if year_ago_idx is not None else None,
                pat_growth_yoy=growth_yoy(pats[i], pats[year_ago_idx]) if year_ago_idx is not None else None,
            )
        )

    latest = ascending[-1]
    return QuarterlyFundamentalsOut(
        points=points,
        quarters_available=len(ascending),
        revenue_at_all_time_high=is_at_all_time_high(revenues[-1], revenues),
        pat_at_all_time_high=is_at_all_time_high(pats[-1], pats),
        latest_period_end=latest.period_end.isoformat(),
        source=latest.source,
        data_age_days=fundamentals_data_age_days(latest.period_end, now.date()),
    )


def _empty_response(symbol: str, exchange: str, now: datetime) -> FundamentalsResponse:
    return FundamentalsResponse(
        symbol=symbol,
        exchange=exchange,
        as_of=now.isoformat(),
        has_fundamental_data=False,
        message=(
            "No fundamentals data available for this instrument. yfinance's coverage of "
            "NSE-listed fundamentals is inconsistent - this is a known data-source gap, "
            "not an application error. See DATA_SOURCES.md."
        ),
        raw=RawFundamentalsOut(
            period_end=None, period_type=None, revenue=None, ebitda=None, ebit=None, pat=None, eps=None,
            operating_cash_flow=None, free_cash_flow=None, total_assets=None, total_liabilities=None,
            total_debt=None, cash=None, equity=None, shares_outstanding=None, dividend_yield=None,
            interest_expense=None, current_assets=None, current_liabilities=None,
            source=None, source_timestamp=None, data_age_days=None,
        ),
        derived=DerivedMetricsOut(
            revenue_growth_yoy=None, ebitda_growth_yoy=None, pat_growth_yoy=None, eps_growth_yoy=None,
            roe=None, roce_simplified=None, debt_to_equity=None, net_debt_to_ebitda=None,
            operating_margin=None, fcf_margin=None, roa=None, net_profit_margin=None, asset_turnover=None,
            financial_leverage=None, interest_coverage=None, current_ratio=None, peg_ratio=None,
        ),
        valuation=ValuationMetricsOut(
            pe=None, pb=None, ev_ebitda=None, ev_sales=None, dividend_yield=None, fcf_yield=None,
            market_cap=None, enterprise_value=None, data_age_days=None, stale=False,
        ),
        fundamental_score=FundamentalScoreOut(
            overall=None,
            band=None,
            sub_scores=FundamentalSubScoresOut(growth=None, profitability=None, leverage=None, efficiency=None),
            methodology_version=FUNDAMENTAL_SCORE_METHODOLOGY_VERSION,
        ),
        quarterly=None,
    )


@router.get("/{symbol}/fundamentals", response_model=FundamentalsResponse)
async def get_fundamentals(
    symbol: str,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> FundamentalsResponse:
    instrument = await resolve_instrument_or_404(session, symbol, exchange)
    now = datetime.now(UTC)

    snapshots = await _latest_two_snapshots(session, instrument.id)
    if not snapshots:
        return _empty_response(instrument.symbol, instrument.exchange, now)

    latest = snapshots[0]
    previous = snapshots[1] if len(snapshots) > 1 else None
    age_days = fundamentals_data_age_days(latest.period_end, now.date())

    raw = RawFundamentalsOut(
        period_end=latest.period_end.isoformat(),
        period_type=latest.period_type,
        revenue=_f(latest.revenue),
        ebitda=_f(latest.ebitda),
        ebit=_f(latest.ebit),
        pat=_f(latest.pat),
        eps=_f(latest.eps),
        operating_cash_flow=_f(latest.operating_cash_flow),
        free_cash_flow=_f(latest.free_cash_flow),
        total_assets=_f(latest.total_assets),
        total_liabilities=_f(latest.total_liabilities),
        total_debt=_f(latest.total_debt),
        cash=_f(latest.cash),
        equity=_f(latest.equity),
        shares_outstanding=_f(latest.shares_outstanding),
        dividend_yield=_f(latest.dividend_yield),
        interest_expense=_f(latest.interest_expense),
        current_assets=_f(latest.current_assets),
        current_liabilities=_f(latest.current_liabilities),
        source=latest.source,
        source_timestamp=latest.source_timestamp.isoformat(),
        data_age_days=age_days,
    )

    previous_revenue = _f(previous.revenue) if previous else None
    previous_ebitda = _f(previous.ebitda) if previous else None
    previous_pat = _f(previous.pat) if previous else None
    previous_eps = _f(previous.eps) if previous else None

    quarterly_snapshots = await _all_quarterly_snapshots(session, instrument.id)

    revenue_growth_yoy = growth_yoy(_f(latest.revenue), previous_revenue)
    eps_growth_yoy = growth_yoy(_f(latest.eps), previous_eps)
    pat_growth_yoy = growth_yoy(_f(latest.pat), previous_pat)
    ebitda_growth_yoy = growth_yoy(_f(latest.ebitda), previous_ebitda)

    if quarterly_snapshots:
        latest_q = quarterly_snapshots[0]
        period_ends = [s.period_end for s in quarterly_snapshots]
        year_ago_end = find_year_ago_period_end(period_ends, latest_q.period_end)
        
        if year_ago_end:
            year_ago_q = next((s for s in quarterly_snapshots if s.period_end == year_ago_end), None)
            if year_ago_q:
                revenue_growth_yoy = growth_yoy(_f(latest_q.revenue), _f(year_ago_q.revenue))
                eps_growth_yoy = growth_yoy(_f(latest_q.eps), _f(year_ago_q.eps))
                pat_growth_yoy = growth_yoy(_f(latest_q.pat), _f(year_ago_q.pat))
                ebitda_growth_yoy = growth_yoy(_f(latest_q.ebitda), _f(year_ago_q.ebitda))

    roe_value = roe(_f(latest.pat), _f(latest.equity))
    roce_value = roce_simplified(_f(latest.ebit), _f(latest.equity), _f(latest.total_debt))
    roa_value = return_on_assets(_f(latest.pat), _f(latest.total_assets))
    net_margin_value = net_profit_margin(_f(latest.pat), _f(latest.revenue))
    de_value = debt_to_equity(_f(latest.total_debt), _f(latest.equity))
    nd_ebitda_value = net_debt_to_ebitda(_f(latest.total_debt), _f(latest.cash), _f(latest.ebitda))
    interest_coverage_value = interest_coverage(_f(latest.ebit), _f(latest.interest_expense))
    current_ratio_value = current_ratio(_f(latest.current_assets), _f(latest.current_liabilities))
    asset_turnover_value = asset_turnover(_f(latest.revenue), _f(latest.total_assets))

    derived = DerivedMetricsOut(
        revenue_growth_yoy=revenue_growth_yoy,
        ebitda_growth_yoy=ebitda_growth_yoy,
        pat_growth_yoy=pat_growth_yoy,
        eps_growth_yoy=eps_growth_yoy,
        roe=roe_value,
        roce_simplified=roce_value,
        debt_to_equity=de_value,
        net_debt_to_ebitda=nd_ebitda_value,
        operating_margin=operating_margin(_f(latest.ebit), _f(latest.revenue)),
        fcf_margin=fcf_margin(_f(latest.free_cash_flow), _f(latest.revenue)),
        roa=roa_value,
        net_profit_margin=net_margin_value,
        asset_turnover=asset_turnover_value,
        financial_leverage=financial_leverage(_f(latest.total_assets), _f(latest.equity)),
        interest_coverage=interest_coverage_value,
        current_ratio=current_ratio_value,
        peg_ratio=None,  # filled below once P/E is known (needs the price-dependent valuation block)
    )

    # Single source of truth (SCORING.md "Fundamental Score"): this is
    # the exact same call `packages/scoring/components.py::score_fundamentals`
    # makes with the exact same derived inputs, so `fundamental_score.overall`
    # below is guaranteed identical to the Research Score's "fundamentals"
    # component score for this instrument.
    sub_scores = compute_fundamental_score(
        revenue_growth_yoy=revenue_growth_yoy,
        pat_growth_yoy=pat_growth_yoy,
        eps_growth_yoy=eps_growth_yoy,
        roe=roe_value,
        roce=roce_value,
        roa=roa_value,
        net_profit_margin=net_margin_value,
        debt_to_equity=de_value,
        net_debt_to_ebitda=nd_ebitda_value,
        interest_coverage=interest_coverage_value,
        current_ratio=current_ratio_value,
        asset_turnover=asset_turnover_value,
    )
    fundamental_score = FundamentalScoreOut(
        overall=sub_scores.overall,
        band=score_band(sub_scores.overall) if sub_scores.overall is not None else None,
        sub_scores=FundamentalSubScoresOut(
            growth=sub_scores.growth,
            profitability=sub_scores.profitability,
            leverage=sub_scores.leverage,
            efficiency=sub_scores.efficiency,
        ),
        methodology_version=FUNDAMENTAL_SCORE_METHODOLOGY_VERSION,
    )

    price_df = await load_ohlcv_dataframe(session, instrument.id)
    if not price_df.empty:
        close = float(price_df["adjusted_close"].iloc[-1])
        val = compute_valuation_metrics(
            close_price=close,
            period_end=latest.period_end,
            as_of=now.date(),
            eps=_f(latest.eps),
            equity=_f(latest.equity),
            shares_outstanding=_f(latest.shares_outstanding),
            revenue=_f(latest.revenue),
            ebitda=_f(latest.ebitda),
            total_debt=_f(latest.total_debt),
            cash=_f(latest.cash),
            free_cash_flow=_f(latest.free_cash_flow),
            dividend_yield=_f(latest.dividend_yield),
            stale_after_days=STALE_FUNDAMENTALS_AFTER_DAYS,
        )
        valuation = ValuationMetricsOut(
            pe=val.pe, pb=val.pb, ev_ebitda=val.ev_ebitda, ev_sales=val.ev_sales,
            dividend_yield=val.dividend_yield, fcf_yield=val.fcf_yield, market_cap=val.market_cap,
            enterprise_value=val.enterprise_value, data_age_days=val.data_age_days, stale=val.stale,
        )
        derived.peg_ratio = peg_ratio(val.pe, eps_growth_yoy)
    else:
        # Fundamentals exist but there's no priced close yet to combine
        # with them - every price*fundamentals valuation field is null,
        # but dividend_yield (fundamentals-only) still comes through.
        valuation = ValuationMetricsOut(
            pe=None, pb=None, ev_ebitda=None, ev_sales=None, dividend_yield=_f(latest.dividend_yield),
            fcf_yield=None, market_cap=None, enterprise_value=None,
            data_age_days=age_days, stale=age_days > STALE_FUNDAMENTALS_AFTER_DAYS,
        )

    quarterly = _build_quarterly_response(quarterly_snapshots, now)

    return FundamentalsResponse(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        as_of=now.isoformat(),
        has_fundamental_data=True,
        message=None,
        raw=raw,
        derived=derived,
        valuation=valuation,
        fundamental_score=fundamental_score,
        quarterly=quarterly,
    )
