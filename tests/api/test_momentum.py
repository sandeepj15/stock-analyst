"""API tests for GET /stocks/{symbol}/momentum-scan (packages/momentum/)."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fakeredis import aioredis as fake_aioredis
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.common import cache
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily


def _override_db(db_session):
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session


def _clear_override():
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
async def fake_redis(monkeypatch):
    client = fake_aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache, "get_redis_client", lambda: client)
    yield client
    await client.aclose()


def _trading_dates(n: int, end: date) -> list[date]:
    dates: list[date] = []
    current = end
    while len(dates) < n:
        if current.weekday() < 5:
            dates.append(current)
        current -= timedelta(days=1)
    return list(reversed(dates))


async def _seed_bars(db_session, instrument, closes, end_date) -> None:
    for trading_date, close in zip(_trading_dates(len(closes), end_date), closes, strict=True):
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
                source_timestamp=datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC),
            )
        )
    await db_session.commit()


@pytest.fixture
def today() -> date:
    return date(2025, 6, 30)


@pytest.mark.asyncio
async def test_momentum_scan_unknown_symbol_is_404(db_session, fake_redis):
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOPE/momentum-scan")
    finally:
        _clear_override()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_momentum_scan_insufficient_history_is_not_evaluable_not_an_error(db_session, fake_redis, today):
    instrument = Instrument(symbol="SHORTHIST", exchange="NSE", company_name="Short Hist Ltd")
    db_session.add(instrument)
    await db_session.flush()
    await _seed_bars(db_session, instrument, [100.0] * 50, today)  # well under 252 bars

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/SHORTHIST/momentum-scan")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["evaluable"] is False
    assert body["passed"] is None  # never a fabricated pass/fail
    assert body["reason"] == "insufficient_price_history"


@pytest.mark.asyncio
async def test_momentum_scan_uptrend_series_is_evaluable_and_returns_all_8_conditions(db_session, fake_redis, today):
    instrument = Instrument(symbol="UPTREND", exchange="NSE", company_name="Uptrend Ltd")
    db_session.add(instrument)
    await db_session.flush()

    # A smooth, steady uptrend with >= 252 bars - every SMA/52w input is
    # computable; the specific pass/fail outcome isn't asserted here
    # (that's covered exhaustively in tests/unit/momentum/test_scanner.py) -
    # only that the endpoint actually evaluates and surfaces all 8 conditions.
    closes = [100.0 + i * 0.5 for i in range(300)]
    await _seed_bars(db_session, instrument, closes, today)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/UPTREND/momentum-scan")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["evaluable"] is True
    assert body["passed"] in (True, False)
    assert len(body["conditions"]) == 8
    assert body["rs_rank_universe"] == "seeded_755"
    assert body["sma200_trend_lookback_days"] == 22
    assert body["methodology_version"] == "stage2_momentum_v1"
    assert body["cache_hit"] is False


@pytest.mark.asyncio
async def test_momentum_scan_custom_lookback_query_param(db_session, fake_redis, today):
    instrument = Instrument(symbol="LOOKBACK", exchange="NSE", company_name="Lookback Ltd")
    db_session.add(instrument)
    await db_session.flush()
    closes = [100.0 + i * 0.5 for i in range(300)]
    await _seed_bars(db_session, instrument, closes, today)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/stocks/LOOKBACK/momentum-scan", params={"sma200_trend_lookback_days": 100}
            )
    finally:
        _clear_override()

    assert response.status_code == 200
    assert response.json()["sma200_trend_lookback_days"] == 100


@pytest.mark.asyncio
async def test_momentum_scan_cache_hit_skips_recomputation(db_session, fake_redis, today):
    from packages.momentum.service import momentum_scan_cache_key

    instrument = Instrument(symbol="MOMCACHE", exchange="NSE", company_name="Mom Cache Ltd")
    db_session.add(instrument)
    await db_session.flush()
    closes = [100.0 + i * 0.5 for i in range(300)]
    await _seed_bars(db_session, instrument, closes, today)

    fake_cached = {
        "instrument_id": str(instrument.id),
        "symbol": "MOMCACHE",
        "exchange": "NSE",
        "scan_date": today.isoformat(),
        "evaluable": True,
        "passed": True,
        "conditions": [],
        "distance_from_52w_high_pct": -1.0,
        "rs_rank": 90.0,
        "rs_rank_universe": "seeded_755",
        "sma200_trend_lookback_days": 22,
        "methodology_version": "stage2_momentum_v1",
        "computed_at": datetime.now(UTC).isoformat(),
        "reason": None,
    }
    await cache.set_json(momentum_scan_cache_key(instrument.id, 22), fake_cached, 1800, client=fake_redis)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/MOMCACHE/momentum-scan")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["cache_hit"] is True
    assert body["rs_rank"] == 90.0
    assert body["passed"] is True
