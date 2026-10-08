"""Ingestion idempotency tests (SPEC.md sections 57, 81 rule 19).

Uses `FakeMarketDataProvider` - no real network / yfinance calls. Proves
that running `ingest_daily_bars` twice with identical input leaves
`ohlcv_daily` in the same end state (no duplicates, same row count, same
values).
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from packages.common.models import Instrument
from packages.market_data.ingestion import ingest_daily_bars
from packages.market_data.models import DataIngestionRun, IngestionStatus, OHLCVDaily
from tests.fixtures.fake_provider import FailingMarketDataProvider, FakeMarketDataProvider, make_bar


async def _make_instrument(session) -> Instrument:
    instrument = Instrument(symbol="RELIANCE", exchange="NSE", company_name="Reliance Industries Ltd")
    session.add(instrument)
    await session.commit()
    return instrument


@pytest.mark.asyncio
async def test_ingest_twice_with_identical_input_is_idempotent(db_session):
    instrument = await _make_instrument(db_session)

    bars = [
        make_bar(trading_date=date(2024, 1, 2), close=100.0, adjusted_close=100.0),
        make_bar(trading_date=date(2024, 1, 3), close=101.0, adjusted_close=101.0),
        make_bar(trading_date=date(2024, 1, 4), close=102.0, adjusted_close=102.0),
    ]
    provider = FakeMarketDataProvider({("RELIANCE", "NSE"): bars})

    first = await ingest_daily_bars(provider, db_session, instrument, date(2024, 1, 1), date(2024, 1, 5))
    assert first.rows_inserted == 3
    assert first.rows_updated == 0
    assert first.status == IngestionStatus.success

    rows_after_first = (
        await db_session.execute(select(OHLCVDaily).where(OHLCVDaily.instrument_id == instrument.id))
    ).scalars().all()
    assert len(rows_after_first) == 3
    snapshot_first = sorted((r.trading_date, float(r.close), r.data_version) for r in rows_after_first)

    second = await ingest_daily_bars(provider, db_session, instrument, date(2024, 1, 1), date(2024, 1, 5))
    assert second.rows_inserted == 0
    assert second.rows_updated == 0  # identical data -> true no-op, not a re-write
    assert second.status == IngestionStatus.success

    rows_after_second = (
        await db_session.execute(select(OHLCVDaily).where(OHLCVDaily.instrument_id == instrument.id))
    ).scalars().all()
    assert len(rows_after_second) == 3  # no duplicates
    snapshot_second = sorted((r.trading_date, float(r.close), r.data_version) for r in rows_after_second)
    assert snapshot_first == snapshot_second  # same end state, including unchanged data_version

    # Two ingestion runs should be recorded, both successful, for observability.
    runs = (await db_session.execute(select(DataIngestionRun).where(DataIngestionRun.instrument_id == instrument.id))).scalars().all()
    assert len(runs) == 2
    assert all(r.status == IngestionStatus.success for r in runs)


@pytest.mark.asyncio
async def test_ingest_updates_changed_values_without_duplicating_rows(db_session):
    instrument = await _make_instrument(db_session)
    provider = FakeMarketDataProvider(
        {("RELIANCE", "NSE"): [make_bar(trading_date=date(2024, 1, 2), close=100.0, adjusted_close=100.0)]}
    )

    first = await ingest_daily_bars(provider, db_session, instrument, date(2024, 1, 1), date(2024, 1, 3))
    assert first.rows_inserted == 1

    # Simulate a corrected/restated bar for the same (instrument, date, source).
    provider.set_bars(
        "RELIANCE", "NSE", [make_bar(trading_date=date(2024, 1, 2), close=105.0, adjusted_close=105.0)]
    )
    second = await ingest_daily_bars(provider, db_session, instrument, date(2024, 1, 1), date(2024, 1, 3))
    assert second.rows_inserted == 0
    assert second.rows_updated == 1

    rows = (
        await db_session.execute(select(OHLCVDaily).where(OHLCVDaily.instrument_id == instrument.id))
    ).scalars().all()
    assert len(rows) == 1
    assert float(rows[0].close) == 105.0
    assert rows[0].data_version == 2


@pytest.mark.asyncio
async def test_provider_failure_is_recorded_and_raised(db_session):
    instrument = await _make_instrument(db_session)
    provider = FailingMarketDataProvider()

    with pytest.raises(RuntimeError):
        await ingest_daily_bars(provider, db_session, instrument, date(2024, 1, 1), date(2024, 1, 5))

    runs = (
        await db_session.execute(select(DataIngestionRun).where(DataIngestionRun.instrument_id == instrument.id))
    ).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == IngestionStatus.failed
    assert "simulated provider outage" in runs[0].error_message

    rows = (
        await db_session.execute(select(OHLCVDaily).where(OHLCVDaily.instrument_id == instrument.id))
    ).scalars().all()
    assert rows == []  # never silently fabricate/use stale data on failure
