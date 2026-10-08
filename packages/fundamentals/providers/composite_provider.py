"""Composite primary+fallback `FundamentalDataProvider` (SPEC.md sections 2.1, 13, 81).

`CompositeFundamentalProvider` wraps a primary provider (in practice,
`YFinanceFundamentalProvider`) and a fallback provider (in practice,
`TradingViewFundamentalProvider`) behind the same
`FundamentalDataProvider` protocol every other provider implements, so
no caller (ingestion service, worker job, seed script, scoring engine)
needs to know a fallback is involved at all.

## Fill-only-if-missing, never overwrite

For every snapshot the primary provider returns, this fills `None`
fields from the fallback's *latest* snapshot - and only `None` fields.
A value the primary provider already supplied is never replaced,
per SPEC.md section 81 rule 8 ("never silently fill missing market
data" - read in context, the rule this project applies here is "never
let a fallback value masquerade as the primary's own data" - see
section 13, "never overwrite raw source data").

If the primary provider has **zero** snapshots for an instrument at all
(not uncommon - see `yfinance_fundamental_provider.py`'s coverage
caveat), and the fallback has *some* data, this synthesizes a single
snapshot from the fallback alone (clearly stamped `source=`
`tradingview_ta`, not blended with a nonexistent yfinance row) rather
than returning nothing - a genuine net improvement in coverage, not a
blurring of provenance.

## Provenance (`field_sources`)

Every returned snapshot's `field_sources` records, per non-null field,
which provider actually supplied the final value (e.g.
`{"revenue": "yfinance", "eps": "tradingview_ta"}`) - see
`packages/fundamentals/models.py::FundamentalSnapshot.field_sources`
and the migration that added it. The top-level `source` column stays
the primary provider's name whenever the primary contributed at least
one field, so existing code that reads `source` is unaffected; the new
column is purely additive, inspectable provenance.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from packages.fundamentals.base import FundamentalDataProvider, FundamentalSnapshotData

logger = logging.getLogger(__name__)

# Every raw numeric field a snapshot can carry - excludes identity/source
# metadata (symbol, exchange, period_end, period_type, source,
# source_timestamp, field_sources itself).
FILLABLE_FIELDS: tuple[str, ...] = (
    "revenue",
    "ebitda",
    "ebit",
    "pat",
    "eps",
    "operating_cash_flow",
    "free_cash_flow",
    "total_assets",
    "total_liabilities",
    "total_debt",
    "cash",
    "equity",
    "shares_outstanding",
    "dividend_yield",
    "interest_expense",
    "current_assets",
    "current_liabilities",
)


class CompositeFundamentalProvider:
    """`FundamentalDataProvider` that fills primary-provider gaps from a fallback.

    Both `primary` and `fallback` need only satisfy the
    `FundamentalDataProvider` protocol (structural typing) - this class
    has no knowledge of yfinance or tradingview_ta specifically.
    """

    def __init__(self, primary: FundamentalDataProvider, fallback: FundamentalDataProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        primary_snapshots = list(self._primary.get_fundamental_snapshots(symbol, exchange))

        if not primary_snapshots:
            return self._synthesize_from_fallback_only(symbol, exchange)

        fallback_snapshots = self._safe_fallback_snapshots(symbol, exchange)
        fallback_latest = fallback_snapshots[0] if fallback_snapshots else None

        filled: list[FundamentalSnapshotData] = []
        for snap in primary_snapshots:
            filled.append(self._fill_gaps(snap, fallback_latest))
        return filled

    def _safe_fallback_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        """The fallback's snapshots, or `[]` if the fallback itself raises.

        A network/rate-limit failure in the *fallback* (e.g. screener.in
        returning 429 under load) must never take down the primary's
        already-good data - the primary provider already succeeded by the
        time this is called, so losing its result to a fallback hiccup
        would be strictly worse than just skipping the gap-fill for this
        run. Same "one provider's failure never aborts the rest" principle
        `sync_fundamentals_job` already applies at the per-instrument
        level (SPEC.md section 58), extended to the per-provider level
        within a single instrument's composite call.
        """
        try:
            return list(self._fallback.get_fundamental_snapshots(symbol, exchange))
        except Exception as exc:
            logger.warning(
                "fundamentals composite: fallback provider failed, continuing with primary-only data",
                extra={"symbol": symbol, "exchange": exchange, "error": str(exc)},
            )
            return []

    def _fill_gaps(
        self, primary_snap: FundamentalSnapshotData, fallback_snap: FundamentalSnapshotData | None
    ) -> FundamentalSnapshotData:
        values = primary_snap.model_dump()
        field_sources: dict[str, str] = dict(primary_snap.field_sources or {})

        for field in FILLABLE_FIELDS:
            current_value = values.get(field)
            if current_value is not None:
                # Primary already has it - record provenance without
                # touching the value, and never let the fallback override it.
                field_sources.setdefault(field, primary_snap.source)
                continue
            if fallback_snap is None:
                continue
            fallback_value = getattr(fallback_snap, field, None)
            if fallback_value is None:
                continue
            values[field] = fallback_value
            field_sources[field] = fallback_snap.source
            logger.info(
                "fundamentals composite: filled gap from fallback provider",
                extra={
                    "symbol": primary_snap.symbol,
                    "exchange": primary_snap.exchange,
                    "field": field,
                    "fallback_source": fallback_snap.source,
                },
            )

        values["field_sources"] = field_sources
        return FundamentalSnapshotData(**values)

    def _synthesize_from_fallback_only(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        fallback_snapshots = self._safe_fallback_snapshots(symbol, exchange)
        if not fallback_snapshots:
            return []  # genuine double-gap - both providers have nothing, report honestly

        fallback_latest = fallback_snapshots[0]
        field_sources = {
            field: fallback_latest.source
            for field in FILLABLE_FIELDS
            if getattr(fallback_latest, field, None) is not None
        }
        logger.info(
            "fundamentals composite: primary had zero coverage, using fallback-only snapshot",
            extra={"symbol": symbol, "exchange": exchange, "fallback_source": fallback_latest.source},
        )
        values = fallback_latest.model_dump()
        values["field_sources"] = field_sources
        values["source_timestamp"] = datetime.now(UTC)
        return [FundamentalSnapshotData(**values)]
