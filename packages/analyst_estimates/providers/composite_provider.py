"""Composite primary(TradingView)+fallback(yfinance) `AnalystEstimateProvider`.

Mirrors `packages/fundamentals/providers/composite_provider.py`'s
fill-only-if-missing/never-overwrite shape, but with the opposite
primary/fallback assignment from the fundamentals composite - per this
task's explicit instruction, TradingView is preferred as the primary
source for the four price-target fields *because* empirical testing
(`providers/tradingview_analyst_provider.py`'s module docstring)
confirmed it genuinely provides them, cross-validated against yfinance.

TradingView, however, does not supply `recommendation_mean`/
`recommendation_key`/`number_of_analyst_opinions` at all (verified - its
only non-null candidate fields were technical-indicator consensus, not
a Wall-Street analyst poll) - those three fields are always filled from
yfinance here, never left as a TradingView gap to "fill", and never
backfilled from a TradingView technical field under a misleading name.

## Fill-only-if-missing, never overwrite

For the four price-target fields, a value TradingView already supplied
is never replaced by yfinance's; a field TradingView left `None` is
filled from yfinance's own value if present. If TradingView has nothing
at all for an instrument, this synthesizes a result from yfinance alone
(clearly stamped `source="yfinance"`) rather than reporting zero
coverage when a genuine value exists.

## Provenance (`field_sources`)

Every returned result's `field_sources` records, per non-null field,
which provider actually supplied the final value - e.g.
`{"target_mean_price": "tradingview_ta", "recommendation_mean": "yfinance"}`
for an instrument where TradingView had the target but, as always, not
the recommendation. The top-level `source` stays whichever provider
contributed the headline `target_mean_price` (TradingView whenever it
has one, else yfinance) - never blended, always inspectable.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from packages.analyst_estimates.base import AnalystEstimateData, AnalystEstimateProvider

logger = logging.getLogger(__name__)

# The four price-target fields TradingView can genuinely supply (see
# providers/tradingview_analyst_provider.py). Recommendation fields are
# deliberately excluded - they are always sourced from yfinance, never
# "filled" from TradingView's technical-indicator fields.
PRICE_TARGET_FIELDS: tuple[str, ...] = (
    "target_mean_price",
    "target_high_price",
    "target_low_price",
    "target_median_price",
)
RECOMMENDATION_FIELDS: tuple[str, ...] = (
    "recommendation_mean",
    "recommendation_key",
    "number_of_analyst_opinions",
)


class CompositeAnalystEstimateProvider:
    """`AnalystEstimateProvider` that prefers TradingView's price targets, filled from yfinance."""

    def __init__(self, primary: AnalystEstimateProvider, fallback: AnalystEstimateProvider) -> None:
        self._primary = primary  # TradingView, in practice
        self._fallback = fallback  # yfinance, in practice

    def get_analyst_estimate(self, symbol: str, exchange: str) -> AnalystEstimateData | None:
        primary_result = self._primary.get_analyst_estimate(symbol, exchange)
        fallback_result = self._fallback.get_analyst_estimate(symbol, exchange)

        if primary_result is None and fallback_result is None:
            return None  # genuine double-gap - report honestly, never fabricate

        if primary_result is None:
            # Primary (TradingView) has nothing - use the fallback alone,
            # clearly stamped as its own source.
            logger.info(
                "analyst_estimates composite: primary had zero coverage, using fallback-only result",
                extra={"symbol": symbol, "exchange": exchange, "fallback_source": fallback_result.source},  # type: ignore[union-attr]
            )
            fallback_only_field_sources = {
                field: fallback_result.source  # type: ignore[union-attr]
                for field in PRICE_TARGET_FIELDS + RECOMMENDATION_FIELDS
                if getattr(fallback_result, field, None) is not None
            }
            values = fallback_result.model_dump()  # type: ignore[union-attr]
            values["field_sources"] = fallback_only_field_sources
            values["source_timestamp"] = datetime.now(UTC)
            return AnalystEstimateData(**values)

        values = primary_result.model_dump()
        field_sources: dict[str, str] = dict(primary_result.field_sources or {})

        for field in PRICE_TARGET_FIELDS:
            current_value = values.get(field)
            if current_value is not None:
                field_sources.setdefault(field, primary_result.source)
                continue
            if fallback_result is None:
                continue
            fallback_value = getattr(fallback_result, field, None)
            if fallback_value is None:
                continue
            values[field] = fallback_value
            field_sources[field] = fallback_result.source
            logger.info(
                "analyst_estimates composite: filled price-target gap from fallback provider",
                extra={"symbol": symbol, "exchange": exchange, "field": field, "fallback_source": fallback_result.source},
            )

        # Recommendation fields are never sourced from TradingView
        # (verified to not genuinely exist there) - always yfinance's,
        # when available.
        for field in RECOMMENDATION_FIELDS:
            if fallback_result is None:
                continue
            fallback_value = getattr(fallback_result, field, None)
            if fallback_value is not None:
                values[field] = fallback_value
                field_sources[field] = fallback_result.source

        values["field_sources"] = field_sources
        values["source_timestamp"] = datetime.now(UTC)
        return AnalystEstimateData(**values)

    def get_analyst_estimates_batch(self, instruments: list[tuple[str, str]]) -> dict[tuple[str, str], AnalystEstimateData | None]:
        primary_results = self._primary.get_analyst_estimates_batch(instruments)
        
        # Only fallback for the ones that need it
        fallback_instruments = []
        for inst in instruments:
            primary_res = primary_results.get(inst)
            # If primary completely missed it, or is missing some fields, we might need fallback
            if primary_res is None or any(getattr(primary_res, f, None) is None for f in PRICE_TARGET_FIELDS) or any(getattr(primary_res, f, None) is None for f in RECOMMENDATION_FIELDS):
                fallback_instruments.append(inst)
                
        if fallback_instruments:
            fallback_results = self._fallback.get_analyst_estimates_batch(fallback_instruments)
        else:
            fallback_results = {}
            
        final_results = {}
        for symbol, exchange in instruments:
            primary_result = primary_results.get((symbol, exchange))
            fallback_result = fallback_results.get((symbol, exchange))
            
            if primary_result is None and fallback_result is None:
                final_results[(symbol, exchange)] = None
                continue
                
            if primary_result is None:
                fallback_only_field_sources = {
                    field: fallback_result.source
                    for field in PRICE_TARGET_FIELDS + RECOMMENDATION_FIELDS
                    if getattr(fallback_result, field, None) is not None
                }
                values = fallback_result.model_dump()
                values["field_sources"] = fallback_only_field_sources
                values["source_timestamp"] = datetime.now(UTC)
                final_results[(symbol, exchange)] = AnalystEstimateData(**values)
                continue
                
            values = primary_result.model_dump()
            field_sources: dict[str, str] = dict(primary_result.field_sources or {})
            
            for field in PRICE_TARGET_FIELDS:
                current_value = values.get(field)
                if current_value is not None:
                    field_sources.setdefault(field, primary_result.source)
                    continue
                if fallback_result is None:
                    continue
                fallback_value = getattr(fallback_result, field, None)
                if fallback_value is None:
                    continue
                values[field] = fallback_value
                field_sources[field] = fallback_result.source
                
            for field in RECOMMENDATION_FIELDS:
                if fallback_result is None:
                    continue
                fallback_value = getattr(fallback_result, field, None)
                if fallback_value is not None:
                    values[field] = fallback_value
                    field_sources[field] = fallback_result.source
                    
            values["field_sources"] = field_sources
            values["source_timestamp"] = datetime.now(UTC)
            final_results[(symbol, exchange)] = AnalystEstimateData(**values)
            
        return final_results
