"""Resolve the configured `FundamentalDataProvider` from settings.

Mirrors `packages/market_data/factory.py`. This is the only place that
should branch on `FUNDAMENTAL_PROVIDER` - callers (worker jobs, scripts,
API routes, the scoring engine) call `get_fundamental_provider()` and
depend only on the `FundamentalDataProvider` protocol afterwards.
"""
from __future__ import annotations

from packages.common.config import Settings
from packages.fundamentals.base import FundamentalDataProvider
from packages.fundamentals.providers.composite_provider import CompositeFundamentalProvider
from packages.fundamentals.providers.screener_in_provider import (
    ScreenerInFundamentalProvider,
    ScreenerInQuarterlyFundamentalProvider,
)
from packages.fundamentals.providers.tradingview_fundamental_provider import TradingViewFundamentalProvider
from packages.fundamentals.providers.yfinance_fundamental_provider import (
    YFinanceFundamentalProvider,
    YFinanceQuarterlyFundamentalProvider,
)


def get_fundamental_provider(settings: Settings) -> FundamentalDataProvider:
    # FUNDAMENTAL_PROVIDER defaults to None in Settings (SPEC.md section 85
    # treated it as a "future phase" placeholder) - this phase implements
    # it, so an unset value falls back to the same yfinance dev provider
    # family used for market data, consistent with DATA_SOURCES.md.
    provider_name = (settings.FUNDAMENTAL_PROVIDER or "yfinance_dev").lower()

    if provider_name == "yfinance_dev":
        return YFinanceFundamentalProvider()

    if provider_name == "yfinance_tradingview_fallback":
        # Composite: yfinance stays the primary/authoritative source;
        # tradingview-ta only fills fields yfinance left `None` (see
        # packages/fundamentals/providers/composite_provider.py and
        # DATA_SOURCES.md). Opt-in via FUNDAMENTAL_PROVIDER rather than
        # the default so existing behavior/tests are unaffected unless
        # explicitly requested.
        return CompositeFundamentalProvider(
            primary=YFinanceFundamentalProvider(), fallback=TradingViewFundamentalProvider()
        )

    if provider_name == "yfinance_screener_fallback":
        # yfinance stays primary (solid for revenue/pat/eps); screener.in
        # fills the balance-sheet fields (equity, total_debt,
        # total_liabilities, total_assets) yfinance frequently leaves
        # `None` for NSE names - see screener_in_provider.py's docstring
        # for scope/unit-handling/scraping-posture details.
        return CompositeFundamentalProvider(
            primary=YFinanceFundamentalProvider(), fallback=ScreenerInFundamentalProvider()
        )

    raise ValueError(
        f"Unknown FUNDAMENTAL_PROVIDER={settings.FUNDAMENTAL_PROVIDER!r}. "
        "Expected 'yfinance_dev', 'yfinance_tradingview_fallback', or 'yfinance_screener_fallback' "
        "in this phase (see SPEC.md sections 12 and 105)."
    )


def get_quarterly_fundamental_provider(settings: Settings) -> FundamentalDataProvider:
    """Resolve the quarterly (`period_type="Q"`) fundamentals provider.

    screener.in is primary here (not yfinance): its quarterly table
    typically covers 10+ quarters for NSE names vs yfinance's ~5-6 (see
    `screener_in_provider.py`), which directly improves the Quarterly
    Trend / all-time-high feature's accuracy. yfinance quarterly is the
    fallback for whatever screener.in doesn't have.

    **Known simplification, inherited from `CompositeFundamentalProvider`**
    (not re-engineered here - see that class's docstring): if screener.in
    returns zero quarters at all for an instrument (fully unavailable,
    not just thin), the composite synthesizes a single snapshot from the
    fallback's *latest* period only, not its full history - a total
    screener.in outage for one symbol degrades to one yfinance quarter
    rather than yfinance's full ~5-6. Accepted because screener.in being
    completely unreachable for a symbol that resolves at all is the rare
    case, not the common one.
    """
    return CompositeFundamentalProvider(
        primary=ScreenerInQuarterlyFundamentalProvider(), fallback=YFinanceQuarterlyFundamentalProvider()
    )
