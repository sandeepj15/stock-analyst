"""API tests for GET /api/v1/stocks/{symbol}/analyst-rating.

Same conventions as tests/api/test_stocks.py / tests/api/test_instruments.py:
in-process ASGI client, DB dependency override onto the shared
`db_session` fixture, fake Redis so no test leaks into another's cache,
synthetic OHLCV/analyst_estimates rows seeded directly (never a real
yfinance/tradingview_ta network call).
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fakeredis import aioredis as fake_aioredis
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.analyst_estimates.models import AnalystEstimate
from packages.common import cache
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily


@pytest.fixture(autouse=True)
async def fake_redis(monkeypatch):
    client = fake_aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache, "get_redis_client", lambda: client)
    yield client
    await client.aclose()


def _override_db(db_session):
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session


def _clear_override():
    app.dependency_overrides.pop(get_db_session, None)


async def _add_ohlcv(db_session, instrument: Instrument, close: float, trading_date: date) -> None:
    db_session.add(
        OHLCVDaily(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            trading_date=trading_date,
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            adjusted_close=close,
            volume=1_000_000,
            source="fake",
            source_timestamp=datetime.combine(trading_date, datetime.min.time()),
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_analyst_rating_no_coverage_returns_honest_empty_state(db_session):
    instrument = Instrument(symbol="NOCOVER", exchange="NSE", company_name="No Cover Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_ohlcv(db_session, instrument, 100.0, date(2026, 10, 1))

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOCOVER/analyst-rating")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["has_coverage"] is False
    assert body["target_mean_price"] is None
    assert body["upside_pct"] is None
    assert body["reason"] == "no_analyst_coverage"


@pytest.mark.asyncio
async def test_analyst_rating_upside_pct_math_is_correct(db_session):
    instrument = Instrument(symbol="COVERED", exchange="NSE", company_name="Covered Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_ohlcv(db_session, instrument, 100.0, date(2026, 10, 1))  # current price

    db_session.add(
        AnalystEstimate(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            target_mean_price=120.0,  # +20% upside vs. current price of 100
            target_high_price=150.0,
            target_low_price=90.0,
            target_median_price=118.0,
            recommendation_mean=1.8,
            recommendation_key="buy",
            number_of_analyst_opinions=15,
            source="tradingview_ta",
            source_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/COVERED/analyst-rating")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["has_coverage"] is True
    assert body["target_mean_price"] == pytest.approx(120.0)
    assert body["current_price"] == pytest.approx(100.0)
    assert body["upside_pct"] == pytest.approx(20.0)
    assert body["recommendation_key"] == "buy"
    assert body["source"] == "tradingview_ta"


@pytest.mark.asyncio
async def test_analyst_rating_downside_is_negative_pct(db_session):
    instrument = Instrument(symbol="OVERVALUED", exchange="NSE", company_name="Overvalued Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_ohlcv(db_session, instrument, 200.0, date(2026, 10, 1))

    db_session.add(
        AnalystEstimate(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            target_mean_price=150.0,  # -25% vs current price of 200
            target_high_price=None,
            target_low_price=None,
            target_median_price=None,
            recommendation_mean=None,
            recommendation_key=None,
            number_of_analyst_opinions=None,
            source="yfinance",
            source_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/OVERVALUED/analyst-rating")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["upside_pct"] == pytest.approx(-25.0)
    assert body["source"] == "yfinance"


@pytest.mark.asyncio
async def test_analyst_rating_null_when_no_ohlcv_despite_coverage(db_session):
    """A target exists but there is no priced close yet - upside_pct must
    stay null (never divide by a fabricated price), while the target
    itself is still reported (SPEC.md section 81 rule 8)."""
    instrument = Instrument(symbol="NOPRICE", exchange="NSE", company_name="No Price Ltd")
    db_session.add(instrument)
    await db_session.commit()

    db_session.add(
        AnalystEstimate(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            target_mean_price=300.0,
            target_high_price=None,
            target_low_price=None,
            target_median_price=None,
            recommendation_mean=None,
            recommendation_key=None,
            number_of_analyst_opinions=None,
            source="yfinance",
            source_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOPRICE/analyst-rating")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["target_mean_price"] == pytest.approx(300.0)
    assert body["current_price"] is None
    assert body["upside_pct"] is None


@pytest.mark.asyncio
async def test_analyst_rating_data_age_days_computed_from_source_timestamp(db_session):
    instrument = Instrument(symbol="AGED", exchange="NSE", company_name="Aged Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_ohlcv(db_session, instrument, 50.0, date(2026, 10, 1))

    old_timestamp = datetime.now(UTC) - timedelta(days=10)
    db_session.add(
        AnalystEstimate(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            target_mean_price=55.0,
            target_high_price=None,
            target_low_price=None,
            target_median_price=None,
            recommendation_mean=None,
            recommendation_key=None,
            number_of_analyst_opinions=None,
            source="yfinance",
            source_timestamp=old_timestamp,
        )
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/AGED/analyst-rating")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["data_age_days"] == 10


@pytest.mark.asyncio
async def test_analyst_rating_unknown_symbol_is_404(db_session):
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOPE/analyst-rating")
    finally:
        _clear_override()
    assert response.status_code == 404
