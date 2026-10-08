"""In-memory fake `MarketDataProvider` for tests.

Never hits the network. Satisfies the `MarketDataProvider` protocol via
structural typing (no inheritance needed) so it can stand in for
`YFinanceDevProvider` anywhere a provider is required.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from packages.market_data.base import DailyBar, InstrumentData, IntradayBar, Quote


class FakeMarketDataProvider:
    """Returns a fixed, caller-provided set of daily bars.

    Pass `bars` as a mapping of (symbol, exchange) -> list[DailyBar], or
    use `set_bars` after construction.
    """

    def __init__(self, bars: dict[tuple[str, str], list[DailyBar]] | None = None) -> None:
        self._bars = bars or {}

    def set_bars(self, symbol: str, exchange: str, bars: list[DailyBar]) -> None:
        self._bars[(symbol.upper(), exchange.upper())] = bars

    def get_instrument(self, symbol: str, exchange: str) -> InstrumentData:
        return InstrumentData(symbol=symbol.upper(), exchange=exchange.upper(), company_name=f"{symbol.upper()} Ltd")

    def get_daily_bars(self, symbol: str, exchange: str, start: date, end: date) -> list[DailyBar]:
        bars = self._bars.get((symbol.upper(), exchange.upper()), [])
        return [b for b in bars if start <= b.trading_date <= end]

    def get_intraday_bars(
        self, symbol: str, exchange: str, timeframe: str, start: datetime, end: datetime
    ) -> list[IntradayBar]:
        raise NotImplementedError("FakeMarketDataProvider does not support intraday bars")

    def get_quotes(self, symbols: list[str], exchange: str) -> list[Quote]:
        now = datetime.now()
        return [
            Quote(symbol=s.upper(), exchange=exchange.upper(), price=100.0, as_of=now, source="fake")
            for s in symbols
        ]


class FailingMarketDataProvider:
    """A provider whose `get_daily_bars` always raises, to test failure handling."""

    def get_instrument(self, symbol: str, exchange: str) -> InstrumentData:
        raise RuntimeError("simulated provider outage")

    def get_daily_bars(self, symbol: str, exchange: str, start: date, end: date) -> list[DailyBar]:
        raise RuntimeError("simulated provider outage")

    def get_intraday_bars(self, *args: Any, **kwargs: Any) -> list[IntradayBar]:
        raise RuntimeError("simulated provider outage")

    def get_quotes(self, symbols: list[str], exchange: str) -> list[Quote]:
        raise RuntimeError("simulated provider outage")


def make_bar(
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
    trading_date: date = date(2024, 1, 2),
    open: float = 100.0,
    high: float = 105.0,
    low: float = 99.0,
    close: float = 103.0,
    adjusted_close: float = 103.0,
    volume: int = 1_000_000,
    source: str = "fake",
    source_timestamp: datetime | None = None,
) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        exchange=exchange,
        trading_date=trading_date,
        open=open,
        high=high,
        low=low,
        close=close,
        adjusted_close=adjusted_close,
        volume=volume,
        source=source,
        source_timestamp=source_timestamp or datetime(2024, 1, 2, 18, 0),
    )
