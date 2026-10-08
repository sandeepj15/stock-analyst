"""Provider-agnostic fundamentals types + the `FundamentalDataProvider` protocol.

Mirrors `packages/market_data/base.py` exactly (SPEC.md sections 8, 12, 81
rule 17): every concrete provider (e.g. `YFinanceFundamentalProvider`) must
implement this `Protocol`. Application code (ingestion service, API routes,
worker jobs, the scoring engine) must depend only on this interface, never
on a concrete provider class or on `yfinance` directly.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class FundamentalSnapshotData(BaseModel):
    """One reporting period's raw fundamentals, as returned by a provider.

    Every financial field is `float | None` - a provider must return `None`
    (never 0, never a fabricated placeholder) for anything it could not
    retrieve. SPEC.md section 12/13: raw reported values only, never a
    derived/backfilled number.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: str
    period_end: date
    period_type: str  # "FY" (annual) or "TTM" (trailing twelve months)
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
    dividend_yield: float | None  # raw, as reported by the provider's current/point-in-time info - see models.py docstring
    # Added for the Fundamental Score's Leverage sub-score (SCORING.md,
    # migration b7a1c9d4e821). Default `None` so existing call sites that
    # construct a `FundamentalSnapshotData` without them (e.g. provider
    # tests predating this field) keep working unchanged - every other
    # field above intentionally has no default so a provider cannot
    # accidentally omit a value it should be reporting as missing.
    interest_expense: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    source: str
    source_timestamp: datetime
    # Per-field provenance (SPEC.md section 2.1/13 evidence traceability).
    # Empty for a single-provider snapshot (the field's provenance is just
    # `source` above). Populated by composite providers (see
    # `packages/fundamentals/providers/composite_provider.py`) that fill
    # some fields from a secondary source - e.g. {"eps": "tradingview_ta"}
    # for a field yfinance didn't have. Never used to overwrite a value
    # the primary provider already supplied.
    field_sources: dict[str, str] = {}


@runtime_checkable
class FundamentalDataProvider(Protocol):
    """Interface every fundamentals-data provider adapter must implement.

    `get_fundamental_snapshots` should return as many periods as the
    provider has available (most recent first or last - callers sort).
    If the provider has nothing for this instrument, return an empty list
    - never raise just because coverage is thin (SPEC.md section 12: "many
    fields will be `None` for many stocks" is expected, not an error).
    Raise only on genuine provider/network failure.
    """

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        """Return every available reporting-period snapshot for one instrument."""
        ...
