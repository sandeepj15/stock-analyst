"""Provider-agnostic market data types + the `MarketDataProvider` protocol.

SPEC.md section 8 requires the data-provider abstraction to exist from day
one and forbids hardcoding the application to a single provider. Every
concrete provider (e.g. `YFinanceDevProvider`) must implement this
`Protocol`. Application code (ingestion service, API routes, worker jobs)
must depend only on this interface, never on a concrete provider class.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class InstrumentData(BaseModel):
    """Instrument reference data as returned by a provider.

    This is intentionally distinct from `packages.common.models.Instrument`
    (the persisted ORM row) - it is the provider's raw view of an
    instrument, which the caller may reconcile against the instrument
    master.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: str
    company_name: str
    currency: str = "INR"
    instrument_type: str = "EQUITY"
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None


class DailyBar(BaseModel):
    """A single daily OHLCV observation from a provider.

    `close` and `adjusted_close` are always kept separate (SPEC.md section
    2.8) - callers must never assume one can substitute for the other.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: str
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int
    source: str
    source_timestamp: datetime


class IntradayBar(BaseModel):
    """A single intraday OHLCV observation from a provider."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: str
    timestamp: datetime
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str
    source_timestamp: datetime


class Quote(BaseModel):
    """A latest-price quote from a provider."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    exchange: str
    price: float
    as_of: datetime
    source: str


@runtime_checkable
class MarketDataProvider(Protocol):
    """Interface every market data provider adapter must implement.

    Methods that cannot be implemented reliably by a given provider should
    raise `NotImplementedError` with a clear explanation rather than
    returning fabricated or approximated data (SPEC.md section 81, rule 23).
    """

    def get_instrument(self, symbol: str, exchange: str) -> InstrumentData:
        """Return reference data for a single instrument."""
        ...

    def get_daily_bars(
        self, symbol: str, exchange: str, start: date, end: date
    ) -> list[DailyBar]:
        """Return daily OHLCV bars for `symbol` between `start` and `end` (inclusive)."""
        ...

    def get_intraday_bars(
        self, symbol: str, exchange: str, timeframe: str, start: datetime, end: datetime
    ) -> list[IntradayBar]:
        """Return intraday OHLCV bars for `symbol` between `start` and `end`."""
        ...

    def get_quotes(self, symbols: list[str], exchange: str) -> list[Quote]:
        """Return the latest available quote for each symbol."""
        ...
