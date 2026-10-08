"""Resolve the configured `AnalystEstimateProvider` from settings.

Mirrors `packages/fundamentals/factory.py`. This is the only place that
should branch on `ANALYST_ESTIMATE_PROVIDER` - callers (worker jobs,
scripts, API routes) call `get_analyst_estimate_provider()` and depend
only on the `AnalystEstimateProvider` protocol afterwards.

Default is the composite (TradingView primary, yfinance fallback +
recommendation source - see `providers/composite_provider.py`), unlike
`packages/fundamentals/factory.py` where the composite is opt-in: this
task's explicit instruction was to prefer TradingView whenever it
genuinely has the data, so that preference is the default here, not an
opt-in variant.
"""
from __future__ import annotations

from packages.analyst_estimates.base import AnalystEstimateProvider
from packages.analyst_estimates.providers.composite_provider import CompositeAnalystEstimateProvider
from packages.analyst_estimates.providers.tradingview_analyst_provider import (
    TradingViewAnalystEstimateProvider,
)
from packages.analyst_estimates.providers.yfinance_analyst_provider import YFinanceAnalystEstimateProvider
from packages.common.config import Settings


def get_analyst_estimate_provider(settings: Settings) -> AnalystEstimateProvider:
    provider_name = (settings.ANALYST_ESTIMATE_PROVIDER or "tradingview_yfinance_composite").lower()

    if provider_name == "tradingview_yfinance_composite":
        return CompositeAnalystEstimateProvider(
            primary=TradingViewAnalystEstimateProvider(), fallback=YFinanceAnalystEstimateProvider()
        )
    if provider_name == "yfinance_dev":
        return YFinanceAnalystEstimateProvider()
    if provider_name == "tradingview_dev":
        return TradingViewAnalystEstimateProvider()

    raise ValueError(
        f"Unknown ANALYST_ESTIMATE_PROVIDER={settings.ANALYST_ESTIMATE_PROVIDER!r}. Expected "
        "'tradingview_yfinance_composite' (default), 'yfinance_dev', or 'tradingview_dev'."
    )
