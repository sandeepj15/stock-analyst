"""Provider-agnostic analyst-estimate types + the `AnalystEstimateProvider` Protocol.

Mirrors `packages/fundamentals/base.py` exactly (same reasoning): every
concrete provider must implement this `Protocol`, and application code
(ingestion service, API routes, worker jobs) depends only on this
interface, never on a concrete provider class or on `yfinance`/
`tradingview_ta` directly.

This is a Wall-Street-analyst **1-year consensus price target** +
recommendation, NOT a technical/screener buy-sell-neutral signal (e.g.
TradingView's `Recommend.All`/`Recommend.MA`, which are purely technical
indicator consensus - see `packages/analyst_estimates/providers/
tradingview_analyst_provider.py`'s module docstring for the empirical
verification that distinguishes the two). Every field is `float | None`
- a provider must return `None` (never 0, never a fabricated placeholder)
for anything it does not have. Coverage is expected to be partial: many
mid/small-cap NSE names have zero analyst coverage - "missing" always
stays missing, never fabricated (SPEC.md section 81 rule 8).
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class AnalystEstimateData(BaseModel):
    """One provider's current analyst-consensus snapshot for one instrument.

    `target_mean_price`/`target_high_price`/`target_low_price`/
    `target_median_price` are 1-year analyst consensus price targets (in
    the instrument's trading currency, same convention as OHLCV close).
    `recommendation_mean`/`recommendation_key`/`number_of_analyst_opinions`
    are the Wall-Street analyst buy/hold/sell consensus and analyst
    count - genuinely different from a technical screener signal, see
    module docstring above. A provider that cannot supply these three
    fields (e.g. TradingView's screener - empirically verified, see
    `providers/tradingview_analyst_provider.py`) must leave them `None`
    rather than substituting a technical indicator under the same name.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: str
    target_mean_price: float | None
    target_high_price: float | None
    target_low_price: float | None
    target_median_price: float | None
    recommendation_mean: float | None
    recommendation_key: str | None
    number_of_analyst_opinions: int | None
    source: str
    source_timestamp: datetime
    # Per-field provenance (same pattern as
    # `packages.fundamentals.base.FundamentalSnapshotData.field_sources`):
    # populated by `providers/composite_provider.py` when a field was
    # filled from a secondary source. Empty for a single-provider result.
    field_sources: dict[str, str] = {}


@runtime_checkable
class AnalystEstimateProvider(Protocol):
    """Interface every analyst-estimate provider adapter must implement.

    Return `None` (never raise) if the provider genuinely has zero
    analyst coverage for this instrument - a very common, expected
    outcome for thinly-covered NSE names, not an error. Raise only on a
    genuine provider/network failure.
    """

    def get_analyst_estimate(self, symbol: str, exchange: str) -> AnalystEstimateData | None:
        """Return the current analyst-consensus snapshot for one instrument, or `None` if uncovered."""
        ...

    def get_analyst_estimates_batch(self, instruments: list[tuple[str, str]]) -> dict[tuple[str, str], AnalystEstimateData | None]:
        """Return the current analyst-consensus snapshot for multiple instruments."""
        ...
