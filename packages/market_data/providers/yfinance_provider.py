"""Development-only `MarketDataProvider` backed by the `yfinance` package.

IMPORTANT - read before using outside local development:

`yfinance` is an unofficial, free wrapper around Yahoo Finance endpoints.
It is used here ONLY as the local-dev, no-API-key market data source
(SPEC.md sections 8 and 105). It is explicitly **not licensed for
commercial redistribution**. Before any commercial launch, this provider
must be swapped for a properly licensed NSE/BSE vendor feed behind the
same `MarketDataProvider` interface (SPEC.md section 73) - no other code
should need to change.

This module is the ONLY place in the codebase allowed to `import
yfinance`. Everything else must depend on `packages.market_data.base`.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import yfinance as yf

from packages.market_data.base import DailyBar, InstrumentData, IntradayBar, Quote

logger = logging.getLogger(__name__)

SOURCE_NAME = "yfinance"

_EXCHANGE_SUFFIX = {
    "NSE": ".NS",
    "BSE": ".BO",
}

# SPEC.md section 15 (Market Regime Engine) needs Nifty 50's daily history
# as a benchmark. Yahoo Finance's ticker for it is the index symbol
# "^NSEI", which does not follow the equity (symbol + exchange suffix)
# convention above - it is not an NSE-listed equity. Rather than bending
# the equity suffix logic to special-case an index, this is a small,
# explicit, documented accommodation: any symbol in this map is resolved
# directly to its Yahoo ticker regardless of the `exchange` argument. The
# instrument is still registered/stored like any other instrument (see
# `packages/regime/service.py`), just with `instrument_type="INDEX"`.
_INDEX_YF_TICKERS = {
    "NIFTY50": "^NSEI",
}


def _yf_symbol(symbol: str, exchange: str) -> str:
    """Map (symbol, exchange) to the Yahoo Finance ticker string.

    Defaults to NSE (`.NS`) when the exchange is unrecognized, since NSE
    is the primary market for this product (SPEC.md: "Primary market:
    Indian equities first"). Known index symbols (see `_INDEX_YF_TICKERS`)
    bypass the equity suffix convention entirely.
    """
    symbol_upper = symbol.upper()
    if symbol_upper in _INDEX_YF_TICKERS:
        return _INDEX_YF_TICKERS[symbol_upper]
    suffix = _EXCHANGE_SUFFIX.get(exchange.upper(), _EXCHANGE_SUFFIX["NSE"])
    return f"{symbol_upper}{suffix}"


class YFinanceDevProvider:
    """`MarketDataProvider` implementation using `yfinance`.

    For local development only. Not licensed for commercial redistribution.
    """

    def get_instrument(self, symbol: str, exchange: str) -> InstrumentData:
        ticker = yf.Ticker(_yf_symbol(symbol, exchange))
        info = ticker.info or {}

        return InstrumentData(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            company_name=info.get("longName") or info.get("shortName") or symbol.upper(),
            currency=info.get("currency") or "INR",
            instrument_type="EQUITY",
            isin=info.get("isin"),
            sector=info.get("sector"),
            industry=info.get("industry"),
        )

    def get_daily_bars(self, symbol: str, exchange: str, start: date, end: date) -> list[DailyBar]:
        """Fetch daily bars via `yfinance.Ticker.history()`.

        We explicitly fetch with `auto_adjust=False` so yfinance returns
        the raw OHLC columns, and separately request the "Adj Close"
        column it provides for dividend/split adjustment. This keeps raw
        close and adjusted close distinct per SPEC.md section 2.8 - we
        never derive one from the other ourselves.
        """
        ticker = yf.Ticker(_yf_symbol(symbol, exchange))
        # yfinance's `end` is exclusive, so add one day to include it.
        history = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=False,
        )

        if history.empty:
            return []

        now = datetime.now(UTC)
        bars: list[DailyBar] = []
        for ts, row in history.iterrows():
            trading_date = ts.date() if hasattr(ts, "date") else ts
            try:
                bars.append(
                    DailyBar(
                        symbol=symbol.upper(),
                        exchange=exchange.upper(),
                        trading_date=trading_date,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        adjusted_close=float(row.get("Adj Close", row["Close"])),
                        volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,  # NaN guard
                        source=SOURCE_NAME,
                        source_timestamp=now,
                    )
                )
            except (TypeError, ValueError) as exc:
                # Never fabricate a value for a malformed row - skip it and
                # let the data-quality layer's missing-day check surface
                # the gap instead of silently inventing data.
                logger.warning(
                    "Skipping malformed yfinance row",
                    extra={"symbol": symbol, "exchange": exchange, "trading_date": str(trading_date), "error": str(exc)},
                )
                continue

        return bars

    def get_intraday_bars(
        self, symbol: str, exchange: str, timeframe: str, start: datetime, end: datetime
    ) -> list[IntradayBar]:
        """Not implemented for the dev provider.

        yfinance's intraday endpoints are rate-limited, retention-limited
        (typically ~60 days for 1-minute data) and flaky enough that
        silently returning partial/approximate data would violate the
        "never fabricate missing data" rule (SPEC.md section 81, rule 23).
        Intraday support should be added once a licensed provider is
        selected, or implemented carefully with explicit gap-reporting.
        """
        raise NotImplementedError(
            "YFinanceDevProvider.get_intraday_bars is not implemented: this is a known "
            "dev-provider limitation (yfinance intraday data is unreliable/retention-limited). "
            "Use a licensed intraday provider for this capability."
        )

    def get_quotes(self, symbols: list[str], exchange: str) -> list[Quote]:
        """Best-effort latest quote using yfinance `fast_info`.

        This is a dev-only approximation (delayed/batched, not a real
        real-time quote feed) and is fine for local development, but must
        not be presented to end users as a live quote in production.
        """
        quotes: list[Quote] = []
        now = datetime.now(UTC)
        for symbol in symbols:
            ticker = yf.Ticker(_yf_symbol(symbol, exchange))
            try:
                price = ticker.fast_info["last_price"]
            except Exception as exc:
                logger.warning(
                    "Could not fetch quote from yfinance",
                    extra={"symbol": symbol, "exchange": exchange, "error": str(exc)},
                )
                continue
            if price is None:
                continue
            quotes.append(Quote(symbol=symbol.upper(), exchange=exchange.upper(), price=float(price), as_of=now, source=SOURCE_NAME))

        return quotes
