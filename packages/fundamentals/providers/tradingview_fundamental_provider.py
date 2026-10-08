"""Secondary/fallback `FundamentalDataProvider` backed by `tradingview-ta`.

SPEC.md section 12 ("many fields will be `None` for many stocks" is
expected) + section 81 rule 23 ("if required data is unavailable, expose
the limitation rather than fabricating it") motivate this: yfinance's
NSE fundamentals coverage is inconsistent (see
`yfinance_fundamental_provider.py`'s docstring), so a second, independent
free/no-key source can genuinely reduce the number of instruments with
zero fundamentals coverage - as long as it never overwrites a value the
primary provider already supplied (SPEC.md section 13, section 81 rule
8). This module is the ONLY place in `packages/fundamentals` allowed to
`import tradingview_ta` - see `packages/fundamentals/providers/composite_provider.py`
for how it is combined with `YFinanceFundamentalProvider` behind the
`FundamentalDataProvider` protocol, and `DATA_SOURCES.md` for the
licensing caveats (same "unofficial, free, dev-only" status as
yfinance).

## Field mapping - empirically verified, not guessed

`tradingview_ta` is a thin wrapper around TradingView's public stock
*screener* endpoint (`scanner.tradingview.com`), which can return
arbitrary named "columns" beyond the ~90 technical-indicator columns the
library ships by default (`TradingView.indicators`). Every field name
below was verified live (Oct 2026) against several real NSE symbols
(RELIANCE, TCS, ITC, COALINDIA, HDFCBANK, INFY) before being hardcoded
here - this is NOT a list of field names assumed from memory/training
data, several plausible-sounding names (e.g. `total_liabilities`,
`ebit`, `operating_income_ttm`) returned `None`/didn't exist and were
discarded in favor of the names confirmed to actually return a value:

    revenue              -> total_revenue
    ebitda               -> ebitda_ttm (fallback: ebitda)
    ebit                 -> ebit_ttm (fallback: oper_income_ttm - same value, confirmed empirically)
    pat                  -> net_income_ttm
    eps                  -> earnings_per_share_diluted_ttm (fallback: earnings_per_share_basic_ttm)
    operating_cash_flow  -> cash_f_operating_activities_ttm
    free_cash_flow       -> free_cash_flow_ttm
    total_assets         -> total_assets_fq
    total_liabilities    -> total_liabilities_fq
    total_debt           -> total_debt_fq
    cash                 -> cash_n_short_term_invest_fq
    equity               -> total_equity_fq
    shares_outstanding   -> total_shares_outstanding_fundamental
    dividend_yield       -> dividends_yield
    current_assets       -> total_current_assets_fq (added for the Fundamental Score's Leverage sub-score)
    current_liabilities  -> total_current_liabilities_fq (same)

`interest_expense` was also checked (candidate: `interest_expense_ttm`)
and found to be `None` for every test symbol (RELIANCE, TCS, ITC,
HDFCBANK, INFY) - this provider does **not** supply `interest_expense`;
it is left `None` here and only ever sourced from yfinance (see
`yfinance_fundamental_provider.py`).

Known, empirically-observed limitation: coverage is inconsistent across
symbols, same as yfinance (e.g. `free_cash_flow_ttm`/`total_assets_fq`
were `None` for RELIANCE/ITC/COALINDIA in verification testing but
present for TCS/INFY/HDFCBANK; `total_current_assets_fq`/
`total_current_liabilities_fq` were present for TCS but `None` for
RELIANCE/ITC/HDFCBANK) - this provider returns `None` for whatever
TradingView's screener doesn't have, exactly like
`YFinanceFundamentalProvider`, never a fabricated value.

Also empirically confirmed: TradingView's screener has no concept of
"fiscal period" for these fields - `_ttm`/`_fq` fields are always a
*current*, continuously-refreshed trailing-twelve-month/latest-quarter
snapshot, not a specific historical reporting period. This provider
therefore always returns at most one snapshot, stamped with
`period_type="TTM"` and `period_end=`today (the date observed), not a
specific fiscal year-end - callers must not treat it as a historical
time series the way yfinance's multi-period snapshots are.

`dividends_yield` is already in percentage-point units (verified: ITC
~5.64, Coal India ~6.29, Reliance ~0.51, TCS ~3.13 - all match real-world
dividend yields directly, not as fractions), matching the same unit
convention `FundamentalSnapshot.dividend_yield` already documents for
yfinance - no conversion needed.
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime
from typing import Any

from tradingview_ta import Interval, TA_Handler, TradingView

from packages.common.rate_limit import RetryPolicy, call_with_retry
from packages.fundamentals.base import FundamentalSnapshotData

logger = logging.getLogger(__name__)

SOURCE_NAME = "tradingview_ta"
SCREENER = "india"

# Appended to TradingView's default technical-indicator column list (never
# replacing it - the library's internal `calculate()` indexes into the
# list positionally for the technical summary, which this provider
# doesn't use but must not break for any other caller of the same
# process-wide `TradingView.indicators` default).
_FUNDAMENTAL_COLUMNS = (
    "total_revenue",
    "ebitda_ttm",
    "ebitda",
    "ebit_ttm",
    "oper_income_ttm",
    "net_income_ttm",
    "earnings_per_share_diluted_ttm",
    "earnings_per_share_basic_ttm",
    "cash_f_operating_activities_ttm",
    "free_cash_flow_ttm",
    "total_assets_fq",
    "total_liabilities_fq",
    "total_debt_fq",
    "cash_n_short_term_invest_fq",
    "total_equity_fq",
    "total_shares_outstanding_fundamental",
    "dividends_yield",
    "total_current_assets_fq",
    "total_current_liabilities_fq",
)

_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=1.5, max_delay_seconds=6.0)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


class TradingViewFundamentalProvider:
    """`FundamentalDataProvider` implementation using `tradingview-ta`.

    Secondary/fallback only (see `composite_provider.py`) - for local
    development/dev-use only, same licensing caveat as the yfinance
    providers (SPEC.md sections 8, 73): TradingView's screener is a free,
    unofficial, no-API-key endpoint, not a licensed commercial data
    product.
    """

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        if exchange.upper() != "NSE":
            # The `india` screener only covers NSE/BSE-style India listings;
            # never guess a mapping for an exchange this provider wasn't
            # verified against.
            return []

        def _fetch() -> dict[str, Any]:
            handler = TA_Handler(symbol=symbol.upper(), exchange=exchange.upper(), screener=SCREENER, interval=Interval.INTERVAL_1_DAY)
            handler.indicators = TradingView.indicators.copy() + list(_FUNDAMENTAL_COLUMNS)
            analysis = handler.get_analysis()
            return dict(analysis.indicators)

        try:
            fields = call_with_retry(_fetch, policy=_RETRY_POLICY, retry_on=(Exception,))
        except Exception as exc:
            logger.warning(
                "tradingview_ta fetch failed", extra={"symbol": symbol, "exchange": exchange, "error": str(exc)}
            )
            return []

        revenue = _safe_float(fields.get("total_revenue"))
        ebitda = _safe_float(fields.get("ebitda_ttm")) or _safe_float(fields.get("ebitda"))
        ebit = _safe_float(fields.get("ebit_ttm")) or _safe_float(fields.get("oper_income_ttm"))
        pat = _safe_float(fields.get("net_income_ttm"))
        eps = _safe_float(fields.get("earnings_per_share_diluted_ttm")) or _safe_float(
            fields.get("earnings_per_share_basic_ttm")
        )
        operating_cash_flow = _safe_float(fields.get("cash_f_operating_activities_ttm"))
        free_cash_flow = _safe_float(fields.get("free_cash_flow_ttm"))
        total_assets = _safe_float(fields.get("total_assets_fq"))
        total_liabilities = _safe_float(fields.get("total_liabilities_fq"))
        total_debt = _safe_float(fields.get("total_debt_fq"))
        cash = _safe_float(fields.get("cash_n_short_term_invest_fq"))
        equity = _safe_float(fields.get("total_equity_fq"))
        shares_outstanding = _safe_float(fields.get("total_shares_outstanding_fundamental"))
        dividend_yield = _safe_float(fields.get("dividends_yield"))
        current_assets = _safe_float(fields.get("total_current_assets_fq"))
        current_liabilities = _safe_float(fields.get("total_current_liabilities_fq"))
        # Not sourced from this provider - verified `None` for every test
        # symbol (see module docstring). Always `None` here; only
        # yfinance ever supplies this field.
        interest_expense = None

        values = (
            revenue,
            ebitda,
            ebit,
            pat,
            eps,
            operating_cash_flow,
            free_cash_flow,
            total_assets,
            total_liabilities,
            total_debt,
            cash,
            equity,
            shares_outstanding,
            dividend_yield,
            current_assets,
            current_liabilities,
        )
        if all(v is None for v in values):
            # Genuinely zero coverage from this provider either - never
            # fabricate a snapshot out of nothing (SPEC.md section 81 rule 8).
            return []

        now = datetime.now(UTC)
        return [
            FundamentalSnapshotData(
                symbol=symbol.upper(),
                exchange=exchange.upper(),
                period_end=date.today(),
                period_type="TTM",
                revenue=revenue,
                ebitda=ebitda,
                ebit=ebit,
                pat=pat,
                eps=eps,
                operating_cash_flow=operating_cash_flow,
                free_cash_flow=free_cash_flow,
                total_assets=total_assets,
                total_liabilities=total_liabilities,
                total_debt=total_debt,
                cash=cash,
                equity=equity,
                shares_outstanding=shares_outstanding,
                dividend_yield=dividend_yield,
                interest_expense=interest_expense,
                current_assets=current_assets,
                current_liabilities=current_liabilities,
                source=SOURCE_NAME,
                source_timestamp=now,
            )
        ]
