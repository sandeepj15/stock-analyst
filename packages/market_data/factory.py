"""Resolve the configured `MarketDataProvider` from settings.

This is the only place that should branch on `MARKET_DATA_PROVIDER` -
callers (worker jobs, scripts, API routes) should call `get_provider()`
and depend only on the `MarketDataProvider` protocol afterwards.
"""
from __future__ import annotations

from packages.common.config import Settings
from packages.market_data.base import MarketDataProvider
from packages.market_data.providers.yfinance_provider import YFinanceDevProvider


def get_provider(settings: Settings) -> MarketDataProvider:
    provider_name = settings.MARKET_DATA_PROVIDER.lower()

    if provider_name == "yfinance_dev":
        return YFinanceDevProvider()

    raise ValueError(
        f"Unknown MARKET_DATA_PROVIDER={settings.MARKET_DATA_PROVIDER!r}. "
        "Only 'yfinance_dev' is implemented in this phase (see SPEC.md section 8 and 105)."
    )
