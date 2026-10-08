"""Development-only `FundamentalDataProvider` backed by the `yfinance` package.

Same rationale and licensing caveat as
`packages/market_data/providers/yfinance_provider.py`: free, no API key,
local-dev only, NOT licensed for commercial redistribution (SPEC.md
sections 8, 12, 73). This module is the ONLY place in `packages/fundamentals`
allowed to `import yfinance`.

Two providers live here: `YFinanceFundamentalProvider` (annual, `period_type="FY"`)
and `YFinanceQuarterlyFundamentalProvider` (`period_type="Q"`, see its own
docstring for the quarterly-coverage caveat). Both share the same
`_snapshot_from_period` field-mapping logic - yfinance uses identical row
labels in its quarterly statements as its annual ones, just with
quarter-end columns instead of fiscal-year-end ones.

**Known limitation (expected, not a bug):** yfinance's fundamentals
coverage for NSE (`.NS`) tickers is inconsistent - `income_stmt`,
`balance_sheet`, `cashflow` and `.info` frequently omit rows, return empty
DataFrames, or lack several periods of history for Indian tickers. This
provider never invents a value to fill a gap: every missing field comes
back as `None` and callers (the derive/scoring layers) must treat that as
missing data, not zero (SPEC.md section 81 rule 8).

**`interest_expense`/`current_assets`/`current_liabilities` (added for
the Fundamental Score's Leverage sub-score, SCORING.md) - empirically
verified live (Oct 2026)** against RELIANCE, TCS, ITC, HDFCBANK and INFY
before being hardcoded: `income_stmt` has an exact `"Interest Expense"`
row with a real nonzero value for **every** name tested, including
HDFCBANK (a bank) - this corrected an initial assumption made during
development that banks wouldn't carry a standalone interest-expense
line; re-checking live showed they do. `balance_sheet`'s `"Current
Assets"`/`"Current Liabilities"` rows, by contrast, are genuinely
**absent** for HDFCBANK specifically (confirmed:
`"Current Assets" in balance_sheet.index` is `False`) - a bank's
balance sheet has no current/non-current split at all, a real
structural difference from non-financial companies (present with real
values for RELIANCE, TCS, ITC, INFY), not a provider bug. Callers must
expect `current_assets`/`current_liabilities` to be `None` for bank
instruments; `interest_expense` is not expected to have this gap.
`tradingview_ta`'s screener was also checked for the same three
(`interest_expense_ttm`, `total_current_assets_fq`,
`total_current_liabilities_fq`) and found inconsistent across symbols
(current-assets/liabilities present for TCS, `None` for
RELIANCE/ITC/HDFCBANK; interest_expense_ttm `None` for every symbol
tested) - see `tradingview_fundamental_provider.py` for which of those
are wired up as a fallback.
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import yfinance as yf

from packages.fundamentals.base import FundamentalSnapshotData

logger = logging.getLogger(__name__)

SOURCE_NAME = "yfinance"

_EXCHANGE_SUFFIX = {
    "NSE": ".NS",
    "BSE": ".BO",
}


def _yf_symbol(symbol: str, exchange: str) -> str:
    suffix = _EXCHANGE_SUFFIX.get(exchange.upper(), _EXCHANGE_SUFFIX["NSE"])
    return f"{symbol.upper()}{suffix}"


def _safe_float(value: Any) -> float | None:
    """Coerce a yfinance cell to `float`, or `None` if it is missing/NaN/non-numeric.

    Never raises, never substitutes 0 - a non-numeric or NaN cell means the
    provider does not have this value, which must be surfaced as missing.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _cell(df: pd.DataFrame | None, column: Any, candidate_rows: tuple[str, ...]) -> float | None:
    """Look up the first matching row label in `candidate_rows` for `column`.

    yfinance uses slightly different row labels across tickers/versions
    (e.g. "EBITDA" vs "Normalized EBITDA") - trying several documented
    aliases is a reasonable accommodation, not a fabrication, because each
    alias refers to the same underlying reported line item.
    """
    if df is None or df.empty or column not in df.columns:
        return None
    for row_name in candidate_rows:
        if row_name in df.index:
            return _safe_float(df.loc[row_name, column])
    return None


def _fetch_statements(ticker: yf.Ticker, symbol: str, quarterly: bool) -> tuple[Any, Any, Any, dict[str, Any]]:
    """Fetch income/balance/cashflow/info, logging-and-`None`ing any that fail individually.

    Shared by both the annual and quarterly providers below - same
    per-call `try/except` isolation (one statement failing doesn't take
    down the other three), just pointed at the `quarterly_*` properties
    when `quarterly=True`.
    """
    income_attr = "quarterly_income_stmt" if quarterly else "income_stmt"
    balance_attr = "quarterly_balance_sheet" if quarterly else "balance_sheet"
    cashflow_attr = "quarterly_cashflow" if quarterly else "cashflow"

    try:
        income = getattr(ticker, income_attr)
    except Exception as exc:  # pragma: no cover - network/provider failure path
        logger.warning(f"yfinance {income_attr} fetch failed", extra={"symbol": symbol, "error": str(exc)})
        income = None
    try:
        balance = getattr(ticker, balance_attr)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"yfinance {balance_attr} fetch failed", extra={"symbol": symbol, "error": str(exc)})
        balance = None
    try:
        cashflow = getattr(ticker, cashflow_attr)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"yfinance {cashflow_attr} fetch failed", extra={"symbol": symbol, "error": str(exc)})
        cashflow = None
    try:
        info = ticker.info or {}
    except Exception as exc:  # pragma: no cover
        logger.warning("yfinance info fetch failed", extra={"symbol": symbol, "error": str(exc)})
        info = {}

    return income, balance, cashflow, info


def _snapshot_from_period(
    symbol: str,
    exchange: str,
    period: Any,
    period_type: str,
    income: pd.DataFrame | None,
    balance: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    shares_outstanding: float | None,
    dividend_yield: float | None,
    now: datetime,
) -> FundamentalSnapshotData:
    """Build one period's `FundamentalSnapshotData` from yfinance's statement DataFrames.

    Identical field-mapping logic for annual (`period_type="FY"`) and
    quarterly (`period_type="Q"`) data - `income`/`balance`/`cashflow`
    just come from the `quarterly_*` yfinance properties instead of the
    annual ones; the row labels yfinance uses are the same either way.
    """
    period_end = period.date() if hasattr(period, "date") else period
    return FundamentalSnapshotData(
        symbol=symbol.upper(),
        exchange=exchange.upper(),
        period_end=period_end,
        period_type=period_type,
        revenue=_cell(income, period, ("Total Revenue", "TotalRevenue")),
        ebitda=_cell(income, period, ("EBITDA", "Normalized EBITDA")),
        ebit=_cell(income, period, ("EBIT", "Operating Income")),
        pat=_cell(
            income,
            period,
            ("Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"),
        ),
        eps=_cell(income, period, ("Diluted EPS", "Basic EPS")),
        operating_cash_flow=_cell(
            cashflow,
            period,
            ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities"),
        ),
        free_cash_flow=_cell(cashflow, period, ("Free Cash Flow",)),
        total_assets=_cell(balance, period, ("Total Assets",)),
        total_liabilities=_cell(balance, period, ("Total Liabilities Net Minority Interest", "Total Liab")),
        total_debt=_cell(balance, period, ("Total Debt",)),
        cash=_cell(
            balance,
            period,
            ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
        ),
        equity=_cell(balance, period, ("Stockholders Equity", "Total Equity Gross Minority Interest")),
        shares_outstanding=shares_outstanding,
        dividend_yield=dividend_yield,
        # Added for the Fundamental Score's Leverage sub-score
        # (SCORING.md) - empirically verified live (Oct 2026):
        # `interest_expense` is present for every tested
        # company including banks (HDFCBANK). `current_assets`/
        # `current_liabilities` are present for non-financial
        # companies (RELIANCE, TCS, ITC, INFY) but genuinely
        # absent for banks (HDFCBANK's balance sheet has no
        # current/non-current split at all) - see
        # DATA_SOURCES.md. `None` here is a genuine
        # data-source gap, never fabricated.
        interest_expense=_cell(income, period, ("Interest Expense",)),
        current_assets=_cell(balance, period, ("Current Assets",)),
        current_liabilities=_cell(balance, period, ("Current Liabilities",)),
        source=SOURCE_NAME,
        source_timestamp=now,
    )


class YFinanceFundamentalProvider:
    """`FundamentalDataProvider` implementation using `yfinance`.

    For local development only. Not licensed for commercial redistribution.
    """

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        ticker = yf.Ticker(_yf_symbol(symbol, exchange))
        income, balance, cashflow, info = _fetch_statements(ticker, symbol, quarterly=False)

        periods: set[Any] = set()
        for df in (income, balance, cashflow):
            if df is not None and not df.empty:
                periods.update(df.columns)

        if not periods:
            # No fundamentals coverage at all for this ticker - an expected
            # outcome for many thinly-covered NSE names, not an error.
            return []

        shares_outstanding = _safe_float(info.get("sharesOutstanding"))
        dividend_yield = _safe_float(info.get("dividendYield"))
        now = datetime.now(UTC)

        return [
            _snapshot_from_period(
                symbol, exchange, period, "FY", income, balance, cashflow, shares_outstanding, dividend_yield, now
            )
            for period in sorted(periods, reverse=True)
        ]


class YFinanceQuarterlyFundamentalProvider:
    """`FundamentalDataProvider` implementation for quarterly yfinance data (`period_type="Q"`).

    **Known limitation (expected, not a bug):** yfinance's
    `quarterly_income_stmt`/`quarterly_balance_sheet`/`quarterly_cashflow`
    typically expose only the trailing ~4-5 reported quarters for NSE
    tickers (sometimes fewer, occasionally none) - nowhere near the
    multi-year quarterly history a site like screener.in shows. Callers
    (the fundamentals API route) must treat "all-time high" computed from
    this data as scoped to however many quarters were actually returned,
    never as true since-listing history - see DATA_SOURCES.md.
    """

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        ticker = yf.Ticker(_yf_symbol(symbol, exchange))
        income, balance, cashflow, info = _fetch_statements(ticker, symbol, quarterly=True)

        periods: set[Any] = set()
        for df in (income, balance, cashflow):
            if df is not None and not df.empty:
                periods.update(df.columns)

        if not periods:
            return []

        shares_outstanding = _safe_float(info.get("sharesOutstanding"))
        dividend_yield = _safe_float(info.get("dividendYield"))
        now = datetime.now(UTC)

        return [
            _snapshot_from_period(
                symbol, exchange, period, "Q", income, balance, cashflow, shares_outstanding, dividend_yield, now
            )
            for period in sorted(periods, reverse=True)
        ]
