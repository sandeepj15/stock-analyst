"""`AnalystEstimateProvider` backed by `yfinance`.

Same rationale/licensing caveat as every other yfinance-backed provider
in this codebase (free, no API key, local-dev only, not licensed for
commercial redistribution - SPEC.md sections 8, 12, 73). This module is
the ONLY place in `packages/analyst_estimates` allowed to `import yfinance`.

## Field mapping - empirically verified live (Oct 2026), not guessed

Verified against RELIANCE, TCS, ITC, COALINDIA, HDFCBANK, INFY (all
`.NS`) via `Ticker.info`:

    target_mean_price          -> info["targetMeanPrice"]
    target_high_price          -> info["targetHighPrice"]
    target_low_price           -> info["targetLowPrice"]
    target_median_price        -> info["targetMedianPrice"]
    recommendation_mean        -> info["recommendationMean"]   (1.0 Strong Buy .. 5.0 Sell)
    recommendation_key         -> info["recommendationKey"]    (e.g. "buy", "strong_buy")
    number_of_analyst_opinions -> info["numberOfAnalystOpinions"]

All six symbols above had full coverage (20-42 analysts each). Coverage
is expected to be much thinner for mid/small-cap NSE names - `info`
simply omits these keys (or returns `None`) for an uncovered instrument,
which this provider surfaces as a genuine `None`, never a fabricated 0.
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

import yfinance as yf

from packages.analyst_estimates.base import AnalystEstimateData

logger = logging.getLogger(__name__)

SOURCE_NAME = "yfinance"

_EXCHANGE_SUFFIX = {
    "NSE": ".NS",
    "BSE": ".BO",
}


def _yf_symbol(symbol: str, exchange: str) -> str:
    suffix = _EXCHANGE_SUFFIX.get(exchange.upper(), _EXCHANGE_SUFFIX["NSE"])
    return f"{symbol.upper()}{suffix}"


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


def _safe_int(value: Any) -> int | None:
    f = _safe_float(value)
    return int(f) if f is not None else None


class YFinanceAnalystEstimateProvider:
    """`AnalystEstimateProvider` implementation using `yfinance`. Dev-only."""

    def get_analyst_estimate(self, symbol: str, exchange: str) -> AnalystEstimateData | None:
        ticker = yf.Ticker(_yf_symbol(symbol, exchange))
        info = ticker.info or {}

        target_mean = _safe_float(info.get("targetMeanPrice"))
        target_high = _safe_float(info.get("targetHighPrice"))
        target_low = _safe_float(info.get("targetLowPrice"))
        target_median = _safe_float(info.get("targetMedianPrice"))
        recommendation_mean = _safe_float(info.get("recommendationMean"))
        recommendation_key = info.get("recommendationKey")
        if not isinstance(recommendation_key, str) or not recommendation_key:
            recommendation_key = None
        number_of_analysts = _safe_int(info.get("numberOfAnalystOpinions"))

        if all(
            v is None
            for v in (target_mean, target_high, target_low, target_median, recommendation_mean, number_of_analysts)
        ):
            # Genuinely zero analyst coverage - common for thinly-covered
            # mid/small-cap NSE names, not an error (SPEC.md section 81 rule 8).
            return None

        return AnalystEstimateData(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
            target_mean_price=target_mean,
            target_high_price=target_high,
            target_low_price=target_low,
            target_median_price=target_median,
            recommendation_mean=recommendation_mean,
            recommendation_key=recommendation_key,
            number_of_analyst_opinions=number_of_analysts,
            source=SOURCE_NAME,
            source_timestamp=datetime.now(UTC),
        )

    def get_analyst_estimates_batch(self, instruments: list[tuple[str, str]]) -> dict[tuple[str, str], AnalystEstimateData | None]:
        result = {}
        for symbol, exchange in instruments:
            result[(symbol, exchange)] = self.get_analyst_estimate(symbol, exchange)
        return result
