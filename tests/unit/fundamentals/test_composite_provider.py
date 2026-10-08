"""Tests for packages/fundamentals/providers/composite_provider.py.

SPEC.md section 13 ("never overwrite raw source data") and section 2.1
(evidence-before-opinion / per-field provenance) are the properties
under test here: the fallback must only ever fill a `None` field, never
replace a value the primary provider already supplied, and every filled
field must be inspectable via `field_sources`.

Uses hand-written fake providers (never yfinance/tradingview_ta
directly, no network) that satisfy `FundamentalDataProvider` by
structural typing.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from packages.fundamentals.base import FundamentalSnapshotData
from packages.fundamentals.providers.composite_provider import CompositeFundamentalProvider


def _snapshot(**overrides: object) -> FundamentalSnapshotData:
    base = dict(
        symbol="TESTCO",
        exchange="NSE",
        period_end=date(2025, 3, 31),
        period_type="FY",
        revenue=None,
        ebitda=None,
        ebit=None,
        pat=None,
        eps=None,
        operating_cash_flow=None,
        free_cash_flow=None,
        total_assets=None,
        total_liabilities=None,
        total_debt=None,
        cash=None,
        equity=None,
        shares_outstanding=None,
        dividend_yield=None,
        source="yfinance",
        source_timestamp=datetime(2025, 4, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return FundamentalSnapshotData(**base)  # type: ignore[arg-type]


class _FakeProvider:
    def __init__(self, snapshots: list[FundamentalSnapshotData]) -> None:
        self._snapshots = snapshots

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        return list(self._snapshots)


class _FakeFailingProvider:
    """Simulates a provider whose network/rate-limit call raises (e.g. screener.in 429s)."""

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        raise ConnectionError("simulated network failure")


def test_fallback_fills_only_none_fields_and_never_overwrites_present_values() -> None:
    primary_snap = _snapshot(revenue=1_000_000.0, eps=None, pat=None, source="yfinance")
    fallback_snap = _snapshot(
        revenue=999_999.0,  # deliberately different - must NOT win, primary already has revenue
        eps=42.0,
        pat=100_000.0,
        source="tradingview_ta",
    )
    provider = CompositeFundamentalProvider(
        primary=_FakeProvider([primary_snap]), fallback=_FakeProvider([fallback_snap])
    )

    result = provider.get_fundamental_snapshots("TESTCO", "NSE")

    assert len(result) == 1
    snap = result[0]
    assert snap.revenue == 1_000_000.0  # untouched - primary's value wins
    assert snap.eps == 42.0  # filled from fallback
    assert snap.pat == 100_000.0  # filled from fallback
    assert snap.source == "yfinance"  # top-level source stays the primary's


def test_field_sources_records_provenance_per_field() -> None:
    primary_snap = _snapshot(revenue=1_000_000.0, eps=None, source="yfinance")
    fallback_snap = _snapshot(eps=42.0, source="tradingview_ta")
    provider = CompositeFundamentalProvider(
        primary=_FakeProvider([primary_snap]), fallback=_FakeProvider([fallback_snap])
    )

    result = provider.get_fundamental_snapshots("TESTCO", "NSE")[0]

    assert result.field_sources["revenue"] == "yfinance"
    assert result.field_sources["eps"] == "tradingview_ta"
    # Fields neither provider had must not appear in field_sources at all.
    assert "pat" not in result.field_sources


def test_fallback_with_nothing_to_offer_leaves_field_none() -> None:
    primary_snap = _snapshot(revenue=1_000_000.0, eps=None, source="yfinance")
    fallback_snap = _snapshot(eps=None, source="tradingview_ta")  # fallback also has nothing for eps
    provider = CompositeFundamentalProvider(
        primary=_FakeProvider([primary_snap]), fallback=_FakeProvider([fallback_snap])
    )

    result = provider.get_fundamental_snapshots("TESTCO", "NSE")[0]
    assert result.eps is None
    assert "eps" not in result.field_sources


def test_zero_primary_coverage_falls_back_to_fallback_only_snapshot() -> None:
    fallback_snap = _snapshot(revenue=500_000.0, eps=10.0, source="tradingview_ta")
    provider = CompositeFundamentalProvider(primary=_FakeProvider([]), fallback=_FakeProvider([fallback_snap]))

    result = provider.get_fundamental_snapshots("TESTCO", "NSE")

    assert len(result) == 1
    snap = result[0]
    assert snap.source == "tradingview_ta"  # honestly labeled - no yfinance row existed
    assert snap.revenue == 500_000.0
    assert snap.field_sources["revenue"] == "tradingview_ta"
    assert snap.field_sources["eps"] == "tradingview_ta"


def test_both_providers_empty_is_an_honest_empty_list_not_fabricated() -> None:
    provider = CompositeFundamentalProvider(primary=_FakeProvider([]), fallback=_FakeProvider([]))

    result = provider.get_fundamental_snapshots("TESTCO", "NSE")

    assert result == []


def test_fallback_failure_never_discards_the_primarys_own_good_data() -> None:
    # Regression test: the fallback raising (network error, 429 rate-limit,
    # etc.) must not take down the primary's already-successful snapshot -
    # discovered live when a screener.in backfill got rate-limited mid-run
    # and was (before this fix) crashing the sync for every instrument it
    # touched, discarding yfinance's perfectly good data too.
    primary_snap = _snapshot(revenue=1_000_000.0, pat=500_000.0, source="yfinance")
    provider = CompositeFundamentalProvider(primary=_FakeProvider([primary_snap]), fallback=_FakeFailingProvider())

    result = provider.get_fundamental_snapshots("TESTCO", "NSE")

    assert len(result) == 1
    assert result[0].revenue == 1_000_000.0
    assert result[0].pat == 500_000.0
    assert result[0].source == "yfinance"


def test_fallback_failure_with_zero_primary_coverage_is_an_honest_empty_list() -> None:
    provider = CompositeFundamentalProvider(primary=_FakeProvider([]), fallback=_FakeFailingProvider())

    result = provider.get_fundamental_snapshots("TESTCO", "NSE")

    assert result == []


def test_multiple_primary_periods_each_filled_independently_from_latest_fallback() -> None:
    older = _snapshot(period_end=date(2024, 3, 31), revenue=800_000.0, eps=None, source="yfinance")
    newer = _snapshot(period_end=date(2025, 3, 31), revenue=1_000_000.0, eps=None, source="yfinance")
    fallback_snap = _snapshot(eps=42.0, source="tradingview_ta")
    provider = CompositeFundamentalProvider(
        primary=_FakeProvider([newer, older]), fallback=_FakeProvider([fallback_snap])
    )

    result = provider.get_fundamental_snapshots("TESTCO", "NSE")

    assert len(result) == 2
    assert all(snap.eps == 42.0 for snap in result)
    assert {snap.revenue for snap in result} == {800_000.0, 1_000_000.0}
