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

    if provider_name in ("screener_in", "yfinance_screener_fallback"):
        return ScreenerInFundamentalProvider()

    raise ValueError(
        f"Unknown FUNDAMENTAL_PROVIDER={settings.FUNDAMENTAL_PROVIDER!r}. "
        "Expected 'yfinance_dev', 'yfinance_tradingview_fallback', 'yfinance_screener_fallback', or 'screener_in' "
        "in this phase (see SPEC.md sections 12 and 105)."
    )


def get_quarterly_fundamental_provider(settings: Settings) -> FundamentalDataProvider:
    """Resolve the quarterly (`period_type="Q"`) fundamentals provider.

    Uses ScreenerInQuarterlyFundamentalProvider directly which parses from
    the local raw_provider_scrapes data lake at lightning speed without external network requests.
    """
    return ScreenerInQuarterlyFundamentalProvider()
