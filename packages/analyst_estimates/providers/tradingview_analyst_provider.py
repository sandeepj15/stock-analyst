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

from tradingview_ta import Interval, TA_Handler, TradingView

from packages.analyst_estimates.base import AnalystEstimateData
from packages.common.rate_limit import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)

SOURCE_NAME = "tradingview_ta"
SCREENER = "india"

# Appended to TradingView's default technical-indicator column list,
# never replacing it - same accommodation as
# `tradingview_fundamental_provider.py`'s `_FUNDAMENTAL_COLUMNS`.
_ANALYST_COLUMNS = (
    "price_target_average",
    "price_target_median",
    "price_target_high",
    "price_target_low",
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
            # The `india` screener only covers NSE/BSE-style India listings -
            # never guess a mapping for an exchange not verified against.
            return None

        def _fetch() -> dict[str, Any]:
            handler = TA_Handler(
                symbol=symbol.upper(), exchange=exchange.upper(), screener=SCREENER, interval=Interval.INTERVAL_1_DAY
            )
            handler.indicators = TradingView.indicators.copy() + list(_ANALYST_COLUMNS)
            analysis = handler.get_analysis()
            return dict(analysis.indicators)

        fields = call_with_retry(_fetch, policy=_RETRY_POLICY, retry_on=(Exception,))

        target_mean = _safe_float(fields.get("price_target_average"))
        target_median = _safe_float(fields.get("price_target_median"))
        target_high = _safe_float(fields.get("price_target_high"))
        target_low = _safe_float(fields.get("price_target_low"))

        if all(v is None for v in (target_mean, target_median, target_high, target_low)):
            # Genuinely zero analyst-target coverage from this provider
            # either - never fabricate a value out of nothing.
            return None

        return AnalystEstimateData(
            symbol=symbol.upper(),
            exchange=exchange.upper(),
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

    def get_analyst_estimates_batch(self, instruments: list[tuple[str, str]]) -> dict[tuple[str, str], AnalystEstimateData | None]:
        if not instruments:
            return {}
            
        tv_symbols = []
        # TV requires EXCHANGE:SYMBOL
        for symbol, exchange in instruments:
            if exchange.upper() == "NSE":
                tv_symbols.append(f"NSE:{symbol.upper()}")
                
        if not tv_symbols:
            return {inst: None for inst in instruments}
            
        def _fetch():
            from tradingview_ta import get_multiple_analysis, Interval
            return get_multiple_analysis(
                screener=SCREENER,
                interval=Interval.INTERVAL_1_DAY,
                symbols=tv_symbols,
                additional_indicators=list(_ANALYST_COLUMNS)
            )
            
        try:
            analysis_dict = call_with_retry(_fetch, policy=_RETRY_POLICY, retry_on=(Exception,))
        except Exception as exc:
            logger.warning("tradingview_ta analyst-estimates batch fetch failed", extra={"error": str(exc)})
            raise  # Let it propagate so we don't wipe out data!
            
        results = {}
        for symbol, exchange in instruments:
            if exchange.upper() != "NSE":
                results[(symbol, exchange)] = None
                continue
                
            tv_key = f"NSE:{symbol.upper()}"
            analysis = analysis_dict.get(tv_key)
            
            if analysis is None or not analysis.indicators:
                results[(symbol, exchange)] = None
                continue
                
            fields = analysis.indicators
            
            target_mean = _safe_float(fields.get("price_target_average"))
            target_median = _safe_float(fields.get("price_target_median"))
            target_high = _safe_float(fields.get("price_target_high"))
            target_low = _safe_float(fields.get("price_target_low"))

            if all(v is None for v in (target_mean, target_median, target_high, target_low)):
                results[(symbol, exchange)] = None
                continue
                
            results[(symbol, exchange)] = AnalystEstimateData(
                symbol=symbol.upper(),
                exchange=exchange.upper(),
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
            
        return results
