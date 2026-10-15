"""`AnalystEstimateProvider` backed by `tradingview-ta`.

## Empirical finding - corrects the initial assumption for this task

This codebase's fundamentals work (`packages/fundamentals/providers/
tradingview_fundamental_provider.py`) previously confirmed that
TradingView's free screener mostly exposes technical/screener fields,
not deep fundamental data, which made it reasonable to *expect* the same
would be true for a 1-year analyst price target. That expectation was
tested empirically here (live, Oct 2026, against RELIANCE, TCS, ITC,
COALINDIA, HDFCBANK, INFY on the `india` screener) and turned out to be
**wrong**: TradingView's screener genuinely does expose Wall-Street
analyst consensus price-target columns, not just technical buy/sell/
neutral signals:

    target_mean_price   -> price_target_average
    target_median_price -> price_target_median
    target_high_price   -> price_target_high
    target_low_price    -> price_target_low

These were cross-checked against yfinance's `targetMeanPrice` etc. for
the same six symbols and track closely (e.g. RELIANCE: TradingView
`price_target_average`=1656.75 vs. yfinance `targetMeanPrice`=1676.85;
HDFCBANK: 996.55 vs. 989.61; ITC: 326.03 vs. 327.15) - consistent with
two independent analyst-consensus aggregations of a real, overlapping
panel of sell-side analysts, not two unrelated numbers. `price_target_1y`
is an alias of `price_target_average` (identical value in every test) -
not used here to avoid double-counting the same figure.

**What TradingView does NOT genuinely provide here (verified, not
assumed):** a real analyst *recommendation*/analyst-*count* equivalent
to yfinance's `recommendationMean`/`recommendationKey`/
`numberOfAnalystOpinions`. The only candidate fields that returned
non-null values - `Recommend.All`, `Recommend.MA`, `Recommend.Other`,
`recommendation_mark` - are TradingView's own **technical indicator
consensus** (a blend of moving averages/oscillators), not a Wall-Street
analyst poll; `analyst_rating`, `rating`, `recommendation`, and
`number_of_analysts` all returned `None` for every symbol tested. Per
this task's explicit instruction, these technical fields are never
mislabeled as an analyst recommendation - `recommendation_mean`/
`recommendation_key`/`number_of_analyst_opinions` are left `None` by
this provider and only ever sourced from yfinance (see
`providers/composite_provider.py`).

Given the user's explicit preference for TradingView as the primary
source whenever it genuinely provides the data, this provider is wired
as the primary for the four price-target fields in
`providers/composite_provider.py`, with yfinance filling any gap and
supplying the recommendation/analyst-count fields this provider cannot.
This module is the ONLY place in `packages/analyst_estimates` allowed to
`import tradingview_ta`.
"""
from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

import requests
from tradingview_ta import TradingView

from packages.analyst_estimates.base import AnalystEstimateData
from packages.common.rate_limit import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)

SOURCE_NAME = "tradingview_ta"
SCREENER = "india"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Appended to TradingView's default technical-indicator column list,
# never replacing it - same accommodation as
# `tradingview_fundamental_provider.py`'s `_FUNDAMENTAL_COLUMNS`.
_ANALYST_COLUMNS = (
    "price_target_average",
    "price_target_median",
    "price_target_high",
    "price_target_low",
    "price_target_1y",
)

_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=1.5, max_delay_seconds=6.0)


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


class TradingViewAnalystEstimateProvider:
    """`AnalystEstimateProvider` implementation using `tradingview-ta`.

    Supplies only the four price-target fields (empirically confirmed
    genuine, see module docstring) - `recommendation_mean`/
    `recommendation_key`/`number_of_analyst_opinions` are always `None`
    here, never backfilled from this provider's technical-indicator
    fields.
    """

    def get_analyst_estimate(self, symbol: str, exchange: str) -> AnalystEstimateData | None:
        if exchange.upper() != "NSE":
            return None
        batch_res = self.get_analyst_estimates_batch([(symbol, exchange)])
        return batch_res.get((symbol, exchange))

    def get_analyst_estimates_batch(
        self, instruments: list[tuple[str, str]]
    ) -> dict[tuple[str, str], AnalystEstimateData | None]:
        if not instruments:
            return {}

        results: dict[tuple[str, str], AnalystEstimateData | None] = {}
        tv_symbol_to_inst: dict[str, tuple[str, str]] = {}
        tv_symbols: list[str] = []

        for symbol, exchange in instruments:
            if exchange.upper() == "NSE":
                sanitized = symbol.upper().replace("-", "_")
                tv_sym = f"NSE:{sanitized}"
                tv_symbol_to_inst[tv_sym] = (symbol, exchange)
                tv_symbols.append(tv_sym)
            else:
                results[(symbol, exchange)] = None

        if not tv_symbols:
            return results

        chunk_size = 250
        cols = list(_ANALYST_COLUMNS)
        scan_url = f"{TradingView.scan_url}{SCREENER}/scan"
        headers = {"User-Agent": DEFAULT_USER_AGENT}

        for i in range(0, len(tv_symbols), chunk_size):
            chunk = tv_symbols[i : i + chunk_size]

            def _fetch_chunk(symbols_chunk: list[str] = chunk) -> dict[str, Any]:
                payload = {"symbols": {"tickers": symbols_chunk}, "columns": cols}
                resp = requests.post(scan_url, json=payload, headers=headers, timeout=15)
                resp.raise_for_status()
                return resp.json()

            try:
                data = call_with_retry(_fetch_chunk, policy=_RETRY_POLICY, retry_on=(Exception,))
            except Exception as exc:
                logger.warning("tradingview_ta analyst-estimates batch fetch chunk failed", extra={"error": str(exc)})
                continue

            for item in data.get("data", []):
                tv_key = item.get("s")
                d = item.get("d", [])
                if not tv_key or not d:
                    continue

                # Indices correspond to _ANALYST_COLUMNS
                # 0: price_target_average
                # 1: price_target_median
                # 2: price_target_high
                # 3: price_target_low
                # 4: price_target_1y
                target_mean = _safe_float(d[0]) or _safe_float(d[4])
                target_median = _safe_float(d[1])
                target_high = _safe_float(d[2])
                target_low = _safe_float(d[3])

                inst = tv_symbol_to_inst.get(tv_key)
                if not inst:
                    continue

                if all(v is None for v in (target_mean, target_median, target_high, target_low)):
                    results[inst] = None
                    continue

                results[inst] = AnalystEstimateData(
                    symbol=inst[0].upper(),
                    exchange=inst[1].upper(),
                    target_mean_price=target_mean,
                    target_high_price=target_high,
                    target_low_price=target_low,
                    target_median_price=target_median,
                    recommendation_mean=None,
                    recommendation_key=None,
                    number_of_analyst_opinions=None,
                    source=SOURCE_NAME,
                    source_timestamp=datetime.now(UTC),
                )

        # Fill any missing requested instruments with None
        for inst in instruments:
            if inst not in results:
                results[inst] = None

        return results
