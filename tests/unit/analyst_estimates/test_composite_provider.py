"""Tests for packages/analyst_estimates/providers/composite_provider.py.

Mirrors tests/unit/fundamentals/test_composite_provider.py's shape and
intent, with the opposite primary/fallback assignment (TradingView
primary for price targets, yfinance fallback + the sole source of
recommendation fields - see composite_provider.py's module docstring
for the empirical justification). Hand-written fake providers only, no
network/yfinance/tradingview_ta.
"""
from __future__ import annotations

from datetime import UTC, datetime

from packages.analyst_estimates.base import AnalystEstimateData
from packages.analyst_estimates.providers.composite_provider import CompositeAnalystEstimateProvider


def _estimate(**overrides: object) -> AnalystEstimateData:
    base = dict(
        symbol="TESTCO",
        exchange="NSE",
        target_mean_price=None,
        target_high_price=None,
        target_low_price=None,
        target_median_price=None,
        recommendation_mean=None,
        recommendation_key=None,
        number_of_analyst_opinions=None,
        source="tradingview_ta",
        source_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return AnalystEstimateData(**base)  # type: ignore[arg-type]


class _FakeProvider:
    def __init__(self, estimate: AnalystEstimateData | None) -> None:
        self._estimate = estimate

    def get_analyst_estimate(self, symbol: str, exchange: str) -> AnalystEstimateData | None:
        return self._estimate


def test_primary_price_target_wins_and_is_never_overwritten_by_fallback() -> None:
    primary = _estimate(target_mean_price=1000.0, source="tradingview_ta")
    fallback = _estimate(target_mean_price=999.0, source="yfinance")  # must NOT win
    provider = CompositeAnalystEstimateProvider(primary=_FakeProvider(primary), fallback=_FakeProvider(fallback))

    result = provider.get_analyst_estimate("TESTCO", "NSE")

    assert result is not None
    assert result.target_mean_price == 1000.0
    assert result.source == "tradingview_ta"
    assert result.field_sources["target_mean_price"] == "tradingview_ta"


def test_fallback_fills_price_target_gap_left_by_primary() -> None:
    primary = _estimate(target_mean_price=None, target_high_price=1200.0, source="tradingview_ta")
    fallback = _estimate(target_mean_price=950.0, source="yfinance")
    provider = CompositeAnalystEstimateProvider(primary=_FakeProvider(primary), fallback=_FakeProvider(fallback))

    result = provider.get_analyst_estimate("TESTCO", "NSE")

    assert result is not None
    assert result.target_mean_price == 950.0
    assert result.field_sources["target_mean_price"] == "yfinance"
    assert result.target_high_price == 1200.0
    assert result.field_sources["target_high_price"] == "tradingview_ta"


def test_recommendation_fields_always_sourced_from_fallback_never_from_primary() -> None:
    # Primary (TradingView) never carries recommendation_mean/key/count -
    # even if a fake test double tried to supply one, the composite must
    # not surface it as if it were genuine (empirically, TradingView's
    # screener has no such field - see providers/tradingview_analyst_provider.py).
    primary = _estimate(target_mean_price=1000.0, recommendation_mean=None, source="tradingview_ta")
    fallback = _estimate(recommendation_mean=1.8, recommendation_key="buy", number_of_analyst_opinions=12, source="yfinance")
    provider = CompositeAnalystEstimateProvider(primary=_FakeProvider(primary), fallback=_FakeProvider(fallback))

    result = provider.get_analyst_estimate("TESTCO", "NSE")

    assert result is not None
    assert result.recommendation_mean == 1.8
    assert result.recommendation_key == "buy"
    assert result.number_of_analyst_opinions == 12
    assert result.field_sources["recommendation_mean"] == "yfinance"


def test_zero_primary_coverage_falls_back_to_fallback_only_result() -> None:
    fallback = _estimate(target_mean_price=500.0, recommendation_key="hold", source="yfinance")
    provider = CompositeAnalystEstimateProvider(primary=_FakeProvider(None), fallback=_FakeProvider(fallback))

    result = provider.get_analyst_estimate("TESTCO", "NSE")

    assert result is not None
    assert result.source == "yfinance"  # honestly labeled - no TradingView result existed
    assert result.target_mean_price == 500.0
    assert result.field_sources["target_mean_price"] == "yfinance"


def test_both_providers_none_is_an_honest_none_not_fabricated() -> None:
    provider = CompositeAnalystEstimateProvider(primary=_FakeProvider(None), fallback=_FakeProvider(None))

    result = provider.get_analyst_estimate("TESTCO", "NSE")

    assert result is None
