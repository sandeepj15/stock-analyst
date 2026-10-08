"""Unit tests for pure helpers in apps/api/routes/fundamentals.py.

`_dedupe_quarterly_by_period` needs no DB session - it operates on
already-loaded `FundamentalSnapshot` ORM objects, so these are
hand-verifiable-value tests same as packages/fundamentals/derive.py's
(SPEC.md section 81 rule 4), not "didn't crash" tests.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from apps.api.routes.fundamentals import _dedupe_quarterly_by_period
from packages.fundamentals.models import FundamentalSnapshot


def _snap(period_end: date, source: str, revenue: float | None = None) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        period_end=period_end,
        period_type="Q",
        source=source,
        source_timestamp=datetime.now(UTC),
        revenue=revenue,
    )


class TestDedupeQuarterlyByPeriod:
    def test_screener_in_preferred_over_yfinance_for_same_quarter(self):
        rows = [
            _snap(date(2026, 6, 30), "yfinance", revenue=100.0),
            _snap(date(2026, 6, 30), "screener_in", revenue=200.0),
        ]
        result = _dedupe_quarterly_by_period(rows)
        assert len(result) == 1
        assert result[0].source == "screener_in"
        assert result[0].revenue == 200.0

    def test_yfinance_kept_when_screener_in_has_no_row_for_that_quarter(self):
        rows = [
            _snap(date(2025, 9, 30), "yfinance", revenue=50.0),
            _snap(date(2026, 6, 30), "screener_in", revenue=200.0),
        ]
        result = _dedupe_quarterly_by_period(rows)
        assert len(result) == 2
        sources = {r.period_end: r.source for r in result}
        assert sources[date(2025, 9, 30)] == "yfinance"
        assert sources[date(2026, 6, 30)] == "screener_in"

    def test_result_sorted_most_recent_first(self):
        rows = [
            _snap(date(2024, 3, 31), "screener_in"),
            _snap(date(2026, 6, 30), "screener_in"),
            _snap(date(2025, 3, 31), "screener_in"),
        ]
        result = _dedupe_quarterly_by_period(rows)
        assert [r.period_end for r in result] == [date(2026, 6, 30), date(2025, 3, 31), date(2024, 3, 31)]

    def test_unknown_source_ranked_last(self):
        rows = [
            _snap(date(2026, 6, 30), "some_future_provider", revenue=1.0),
            _snap(date(2026, 6, 30), "yfinance", revenue=2.0),
        ]
        result = _dedupe_quarterly_by_period(rows)
        assert len(result) == 1
        assert result[0].source == "yfinance"

    def test_empty_input(self):
        assert _dedupe_quarterly_by_period([]) == []
