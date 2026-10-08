"""Data quality layer (SPEC.md section 11).

These functions are pure and operate on plain `list[dict]` bar records
(rather than ORM rows or even `DailyBar` pydantic models) so that:

1. They can be unit tested with hand-crafted fixtures, including
   malformed records that wouldn't even pass pydantic validation
   (missing fields, wrong types) - which is exactly the kind of input a
   flaky upstream provider can produce.
2. They have zero dependency on a database connection.

None of these functions mutate, drop, or "fix" the input data. They only
*report* issues as `QualityIssue` objects. The caller (the ingestion
service) decides what to do with the data and persists corresponding
`data_quality_events` rows. This is deliberate - SPEC.md section 81 rule 8
("Never silently fill missing market data") and section 11 ("Never
silently normalize [outliers]").

Expected bar record shape (dict keys):
    symbol, exchange, trading_date, open, high, low, close,
    adjusted_close, volume, source, source_timestamp

`trading_date` may be a `date`/`datetime` or an ISO-format string.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from numbers import Real
from typing import Any

from pydantic import BaseModel

from packages.market_data.models import QualityEventType, QualitySeverity

REQUIRED_FIELDS = (
    "symbol",
    "exchange",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "source",
    "source_timestamp",
)
NUMERIC_FIELDS = ("open", "high", "low", "close", "adjusted_close", "volume")


class QualityIssue(BaseModel):
    """A single data-quality finding, independent of persistence."""

    event_type: QualityEventType
    severity: QualitySeverity
    message: str
    details: dict[str, Any] = {}


def _bar_label(bar: dict[str, Any]) -> str:
    symbol = bar.get("symbol", "?")
    trading_date = bar.get("trading_date", "?")
    source = bar.get("source", "?")
    return f"{symbol}@{trading_date}[{source}]"


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def validate_schema(bars: list[dict[str, Any]]) -> list[QualityIssue]:
    """Required fields present, numeric types correct, dates parseable."""
    issues: list[QualityIssue] = []
    for bar in bars:
        label = _bar_label(bar)
        missing = [f for f in REQUIRED_FIELDS if bar.get(f) is None]
        if missing:
            issues.append(
                QualityIssue(
                    event_type=QualityEventType.schema,
                    severity=QualitySeverity.error,
                    message=f"Bar {label} is missing required field(s): {', '.join(missing)}",
                    details={"bar": label, "missing_fields": missing},
                )
            )
            continue  # further checks would be meaningless without the fields

        non_numeric = [f for f in NUMERIC_FIELDS if not isinstance(bar.get(f), Real) or isinstance(bar.get(f), bool)]
        if non_numeric:
            issues.append(
                QualityIssue(
                    event_type=QualityEventType.schema,
                    severity=QualitySeverity.error,
                    message=f"Bar {label} has non-numeric value(s) for: {', '.join(non_numeric)}",
                    details={"bar": label, "non_numeric_fields": non_numeric},
                )
            )

        if _parse_date(bar.get("trading_date")) is None:
            issues.append(
                QualityIssue(
                    event_type=QualityEventType.schema,
                    severity=QualitySeverity.error,
                    message=f"Bar {label} has an invalid trading_date: {bar.get('trading_date')!r}",
                    details={"bar": label, "trading_date": str(bar.get("trading_date"))},
                )
            )

    return issues


def validate_ohlc_ranges(bars: list[dict[str, Any]]) -> list[QualityIssue]:
    """high >= max(open, close); low <= min(open, close); volume >= 0."""
    issues: list[QualityIssue] = []
    for bar in bars:
        label = _bar_label(bar)
        try:
            o, h, lo, c, v = (bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"])
        except KeyError:
            continue  # schema check already reports this

        if not all(isinstance(x, Real) and not isinstance(x, bool) for x in (o, h, lo, c, v)):
            continue  # schema check already reports this

        if h < max(o, c):
            issues.append(
                QualityIssue(
                    event_type=QualityEventType.range,
                    severity=QualitySeverity.error,
                    message=f"Bar {label}: high ({h}) is less than max(open, close) ({max(o, c)})",
                    details={"bar": label, "high": h, "open": o, "close": c},
                )
            )
        if lo > min(o, c):
            issues.append(
                QualityIssue(
                    event_type=QualityEventType.range,
                    severity=QualitySeverity.error,
                    message=f"Bar {label}: low ({lo}) is greater than min(open, close) ({min(o, c)})",
                    details={"bar": label, "low": lo, "open": o, "close": c},
                )
            )
        if v < 0:
            issues.append(
                QualityIssue(
                    event_type=QualityEventType.range,
                    severity=QualitySeverity.error,
                    message=f"Bar {label}: volume is negative ({v})",
                    details={"bar": label, "volume": v},
                )
            )

    return issues


def detect_duplicates(bars: list[dict[str, Any]]) -> list[QualityIssue]:
    """Flag duplicate (symbol, exchange, trading_date, source) rows."""
    issues: list[QualityIssue] = []
    seen: dict[tuple[Any, Any, Any, Any], int] = defaultdict(int)
    for bar in bars:
        key = (bar.get("symbol"), bar.get("exchange"), str(bar.get("trading_date")), bar.get("source"))
        seen[key] += 1

    for key, count in seen.items():
        if count > 1:
            symbol, exchange, trading_date, source = key
            issues.append(
                QualityIssue(
                    event_type=QualityEventType.duplicate,
                    severity=QualitySeverity.error,
                    message=(
                        f"Found {count} duplicate rows for {symbol}@{trading_date} "
                        f"from source {source} ({exchange})"
                    ),
                    details={
                        "symbol": symbol,
                        "exchange": exchange,
                        "trading_date": trading_date,
                        "source": source,
                        "count": count,
                    },
                )
            )

    return issues


def detect_missing_trading_days(
    bars: list[dict[str, Any]], start: date, end: date
) -> list[QualityIssue]:
    """Detect gaps vs expected trading days between `start` and `end`.

    Approximation: expected trading days = weekdays (Mon-Fri). This does
    NOT account for exchange holidays. A proper NSE/BSE holiday calendar
    is a future improvement (tracked, not implemented, in this phase) -
    see SPEC.md section 11.
    """
    issues: list[QualityIssue] = []
    present_dates = {_parse_date(bar.get("trading_date")) for bar in bars}
    present_dates.discard(None)

    expected = set()
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            expected.add(current)
        current += timedelta(days=1)

    missing = sorted(expected - present_dates)
    if missing:
        issues.append(
            QualityIssue(
                event_type=QualityEventType.missing_data,
                severity=QualitySeverity.warning,
                message=(
                    f"{len(missing)} expected trading day(s) have no bar between "
                    f"{start.isoformat()} and {end.isoformat()} "
                    "(weekday approximation; holidays not yet excluded)"
                ),
                details={"missing_dates": [d.isoformat() for d in missing]},
            )
        )

    return issues


def flag_outliers(bars: list[dict[str, Any]], threshold: float = 0.25) -> list[QualityIssue]:
    """Flag (never drop) bars where abs daily % change in close exceeds `threshold`.

    A large move may be legitimate, split-related, or bad data - this
    function only flags it for human/downstream review (SPEC.md section 11).
    """
    issues: list[QualityIssue] = []
    by_symbol: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for bar in bars:
        if _parse_date(bar.get("trading_date")) is None or not isinstance(bar.get("close"), Real):
            continue
        by_symbol[(bar.get("symbol"), bar.get("exchange"), bar.get("source"))].append(bar)

    for _key, symbol_bars in by_symbol.items():
        ordered = sorted(symbol_bars, key=lambda b: _parse_date(b["trading_date"]) or date.min)
        for prev, curr in zip(ordered, ordered[1:], strict=False):
            prev_close = prev["close"]
            curr_close = curr["close"]
            if prev_close == 0:
                continue
            pct_change = (curr_close - prev_close) / prev_close
            if abs(pct_change) > threshold:
                issues.append(
                    QualityIssue(
                        event_type=QualityEventType.outlier,
                        severity=QualitySeverity.warning,
                        message=(
                            f"Bar {_bar_label(curr)}: close moved {pct_change:+.1%} vs previous "
                            f"close ({prev_close} -> {curr_close}), exceeding {threshold:.0%} threshold"
                        ),
                        details={
                            "bar": _bar_label(curr),
                            "previous_close": prev_close,
                            "current_close": curr_close,
                            "pct_change": pct_change,
                            "threshold": threshold,
                        },
                    )
                )

    return issues


def run_all_quality_checks(
    bars: list[dict[str, Any]], start: date, end: date, outlier_threshold: float = 0.25
) -> list[QualityIssue]:
    """Convenience wrapper running every check used by the ingestion service."""
    return [
        *validate_schema(bars),
        *validate_ohlc_ranges(bars),
        *detect_duplicates(bars),
        *detect_missing_trading_days(bars, start, end),
        *flag_outliers(bars, threshold=outlier_threshold),
    ]
