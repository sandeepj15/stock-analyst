"""Unit tests for the data quality layer (SPEC.md section 11).

Pure functions, no database, no network - crafted fixtures only.
"""
from __future__ import annotations

from datetime import date, datetime

from packages.market_data.models import QualityEventType, QualitySeverity
from packages.market_data.quality import (
    detect_duplicates,
    detect_missing_trading_days,
    flag_outliers,
    validate_ohlc_ranges,
    validate_schema,
)


def _bar(**overrides) -> dict:
    base = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "trading_date": date(2024, 1, 2),
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 103.0,
        "adjusted_close": 103.0,
        "volume": 1_000_000,
        "source": "fake",
        "source_timestamp": datetime(2024, 1, 2, 18, 0),
    }
    base.update(overrides)
    return base


class TestValidateSchema:
    def test_valid_bar_has_no_issues(self):
        assert validate_schema([_bar()]) == []

    def test_missing_required_field_is_flagged(self):
        bar = _bar()
        del bar["close"]
        issues = validate_schema([bar])
        assert len(issues) == 1
        assert issues[0].event_type == QualityEventType.schema
        assert issues[0].severity == QualitySeverity.error
        assert "close" in issues[0].details["missing_fields"]

    def test_non_numeric_field_is_flagged(self):
        bar = _bar(volume="not-a-number")
        issues = validate_schema([bar])
        assert any(i.event_type == QualityEventType.schema for i in issues)
        assert any("volume" in i.details.get("non_numeric_fields", []) for i in issues)

    def test_invalid_trading_date_is_flagged(self):
        bar = _bar(trading_date="not-a-date")
        issues = validate_schema([bar])
        assert any("trading_date" in i.message for i in issues)


class TestValidateOhlcRanges:
    def test_valid_bar_has_no_issues(self):
        assert validate_ohlc_ranges([_bar()]) == []

    def test_high_less_than_close_is_flagged(self):
        bar = _bar(high=101.0, close=103.0)
        issues = validate_ohlc_ranges([bar])
        assert len(issues) == 1
        assert issues[0].event_type == QualityEventType.range
        assert "high" in issues[0].message

    def test_low_greater_than_open_is_flagged(self):
        bar = _bar(low=102.0, open=100.0, close=101.0, high=103.0)
        issues = validate_ohlc_ranges([bar])
        assert len(issues) == 1
        assert "low" in issues[0].message

    def test_negative_volume_is_flagged(self):
        bar = _bar(volume=-500)
        issues = validate_ohlc_ranges([bar])
        assert len(issues) == 1
        assert "volume" in issues[0].message.lower()


class TestDetectDuplicates:
    def test_no_duplicates(self):
        bars = [_bar(trading_date=date(2024, 1, 2)), _bar(trading_date=date(2024, 1, 3))]
        assert detect_duplicates(bars) == []

    def test_duplicate_instrument_date_source_is_flagged(self):
        bars = [_bar(), _bar()]
        issues = detect_duplicates(bars)
        assert len(issues) == 1
        assert issues[0].event_type == QualityEventType.duplicate
        assert issues[0].details["count"] == 2

    def test_same_date_different_source_is_not_a_duplicate(self):
        bars = [_bar(source="fake"), _bar(source="other")]
        assert detect_duplicates(bars) == []


class TestDetectMissingTradingDays:
    def test_no_gaps(self):
        # Mon 1st, Tue 2nd, Wed 3rd (2024-01-01 is a Monday)
        bars = [_bar(trading_date=date(2024, 1, 1)), _bar(trading_date=date(2024, 1, 2)), _bar(trading_date=date(2024, 1, 3))]
        issues = detect_missing_trading_days(bars, date(2024, 1, 1), date(2024, 1, 3))
        assert issues == []

    def test_gap_is_flagged(self):
        bars = [_bar(trading_date=date(2024, 1, 1)), _bar(trading_date=date(2024, 1, 3))]
        issues = detect_missing_trading_days(bars, date(2024, 1, 1), date(2024, 1, 3))
        assert len(issues) == 1
        assert issues[0].event_type == QualityEventType.missing_data
        assert "2024-01-02" in issues[0].details["missing_dates"]

    def test_weekends_are_not_expected(self):
        # 2024-01-05 Fri, 2024-01-08 Mon - weekend gap must not be flagged
        bars = [_bar(trading_date=date(2024, 1, 5)), _bar(trading_date=date(2024, 1, 8))]
        issues = detect_missing_trading_days(bars, date(2024, 1, 5), date(2024, 1, 8))
        assert issues == []


class TestFlagOutliers:
    def test_normal_move_is_not_flagged(self):
        bars = [
            _bar(trading_date=date(2024, 1, 2), close=100.0),
            _bar(trading_date=date(2024, 1, 3), close=102.0),
        ]
        assert flag_outliers(bars, threshold=0.25) == []

    def test_large_move_is_flagged_not_removed(self):
        bars = [
            _bar(trading_date=date(2024, 1, 2), close=100.0),
            _bar(trading_date=date(2024, 1, 3), close=150.0),
        ]
        issues = flag_outliers(bars, threshold=0.25)
        assert len(issues) == 1
        assert issues[0].event_type == QualityEventType.outlier
        assert issues[0].severity == QualitySeverity.warning
        # the function must only report, never mutate its input
        assert bars[1]["close"] == 150.0

    def test_custom_threshold(self):
        bars = [
            _bar(trading_date=date(2024, 1, 2), close=100.0),
            _bar(trading_date=date(2024, 1, 3), close=106.0),
        ]
        assert flag_outliers(bars, threshold=0.25) == []
        assert len(flag_outliers(bars, threshold=0.05)) == 1
