"""Tests for the incremental OHLCV sync mode added for the daily
after-market-close pipeline (`apps/worker/jobs.py::sync_daily_bars`'s
`lookback_days` param + `packages/market_data/ingestion.py::
ingest_daily_bars_for_instruments`).

Uses the existing `FakeMarketDataProvider` convention
(tests/fixtures/fake_provider.py) - no real network/yfinance calls.
`session_scope` is monkeypatched to the test database bound by the
`engine` fixture (tests/conftest.py), rather than the real
`DATABASE_URL`, so `sync_daily_bars` can be exercised end-to-end
(instrument query -> bounded-concurrency fetch -> upsert) against a real
disposable Postgres without ever touching the live app database.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import apps.worker.jobs as jobs
import packages.market_data.ingestion as ingestion
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily
from tests.fixtures.fake_provider import FakeMarketDataProvider, make_bar


class RecordingProvider(FakeMarketDataProvider):
    """Same `FakeMarketDataProvider` behavior, plus a log of every
    `(symbol, exchange, start, end)` call so tests can assert exactly
    what date window was requested."""

    def __init__(self, bars):
        super().__init__(bars)
        self.calls: list[tuple[str, str, date, date]] = []

    def get_daily_bars(self, symbol: str, exchange: str, start: date, end: date):
        self.calls.append((symbol, exchange, start, end))
        return super().get_daily_bars(symbol, exchange, start, end)


@pytest.fixture
def _session_scope_bound_to_test_engine(monkeypatch, engine):
    """Point `session_scope()` (as seen by `apps.worker.jobs` and
    `packages.market_data.ingestion`, both of which imported it via
    `from packages.common.db import session_scope`) at the test-only
    `engine` fixture instead of the real app `DATABASE_URL` - the same
    disposable Postgres `tests/conftest.py` already creates/drops tables
    against for every other test in this suite.
    """
    sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def _fake_session_scope():
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(jobs, "session_scope", _fake_session_scope)
    monkeypatch.setattr(ingestion, "session_scope", _fake_session_scope)
    return sessionmaker


async def _make_instruments(sessionmaker, specs: list[tuple[str, str]]) -> list[Instrument]:
    instruments = []
    async with sessionmaker() as session:
        for symbol, exchange in specs:
            instrument = Instrument(symbol=symbol, exchange=exchange, company_name=f"{symbol} Ltd")
            session.add(instrument)
            instruments.append(instrument)
        await session.commit()
        for instrument in instruments:
            await session.refresh(instrument)
    return instruments


@pytest.mark.asyncio
async def test_sync_daily_bars_incremental_mode_requests_only_the_small_trailing_window(
    monkeypatch, _session_scope_bound_to_test_engine
):
    """`lookback_days=10` must request roughly the last 10 days, never the
    full ~2-year (`DEFAULT_BACKFILL_DAYS`) history."""
    sessionmaker = _session_scope_bound_to_test_engine
    await _make_instruments(sessionmaker, [("RELIANCE", "NSE"), ("TCS", "NSE")])

    today = date.today()
    provider = RecordingProvider(
        {
            ("RELIANCE", "NSE"): [make_bar(symbol="RELIANCE", trading_date=today)],
            ("TCS", "NSE"): [make_bar(symbol="TCS", trading_date=today)],
        }
    )
    monkeypatch.setattr(jobs, "get_provider", lambda settings: provider)

    lookback_days = 10
    result = await jobs.sync_daily_bars({}, lookback_days=lookback_days)

    assert len(result["failed"]) == 0
    assert len(result["synced"]) == 2
    assert len(provider.calls) == 2

    expected_start = today - timedelta(days=lookback_days)
    for _symbol, _exchange, start, end in provider.calls:
        assert start == expected_start
        assert end == today
        # Never the full ~2-year default window.
        assert (end - start).days == lookback_days
        assert (end - start).days < jobs.DEFAULT_BACKFILL_DAYS


@pytest.mark.asyncio
async def test_sync_daily_bars_default_lookback_still_does_the_full_backfill_window(
    monkeypatch, _session_scope_bound_to_test_engine
):
    """Existing callers (manual full backfills) that don't pass
    `lookback_days` must keep getting the original full-history window -
    this incremental mode must be additive, not a behavior change for
    them."""
    sessionmaker = _session_scope_bound_to_test_engine
    await _make_instruments(sessionmaker, [("INFY", "NSE")])

    today = date.today()
    provider = RecordingProvider({("INFY", "NSE"): [make_bar(symbol="INFY", trading_date=today)]})
    monkeypatch.setattr(jobs, "get_provider", lambda settings: provider)

    result = await jobs.sync_daily_bars({})  # no lookback_days -> original full-backfill default

    assert len(result["failed"]) == 0
    assert len(provider.calls) == 1
    _symbol, _exchange, start, end = provider.calls[0]
    assert end == today
    assert start == today - timedelta(days=jobs.DEFAULT_BACKFILL_DAYS)


@pytest.mark.asyncio
async def test_sync_daily_bars_incremental_mode_persists_rows_and_is_resilient_to_one_bad_symbol(
    monkeypatch, _session_scope_bound_to_test_engine
):
    """End-to-end: incremental sync still upserts real rows for the
    healthy instrument, and one instrument's provider failure never
    aborts the batch (SPEC.md section 58) - matching every other batch
    job's per-instrument resilience."""
    sessionmaker = _session_scope_bound_to_test_engine
    instruments = await _make_instruments(sessionmaker, [("RELIANCE", "NSE"), ("BROKEN", "NSE")])

    today = date.today()
    provider = RecordingProvider({("RELIANCE", "NSE"): [make_bar(symbol="RELIANCE", trading_date=today)]})
    # BROKEN has no bars configured -> FakeMarketDataProvider.get_daily_bars
    # returns [] for it (not a failure), so patch its lookup to raise
    # instead, to simulate a genuine per-symbol provider failure.
    original_get_daily_bars = provider.get_daily_bars

    def _flaky_get_daily_bars(symbol: str, exchange: str, start: date, end: date):
        if symbol.upper() == "BROKEN":
            provider.calls.append((symbol, exchange, start, end))
            raise RuntimeError("simulated provider outage for BROKEN")
        return original_get_daily_bars(symbol, exchange, start, end)

    monkeypatch.setattr(provider, "get_daily_bars", _flaky_get_daily_bars)
    monkeypatch.setattr(jobs, "get_provider", lambda settings: provider)

    result = await jobs.sync_daily_bars({}, lookback_days=10)

    assert len(result["synced"]) == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["symbol"] == "BROKEN"

    reliance = next(i for i in instruments if i.symbol == "RELIANCE")
    async with sessionmaker() as session:
        rows = (
            await session.execute(select(OHLCVDaily).where(OHLCVDaily.instrument_id == reliance.id))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].trading_date == today
