"""API tests for /api/v1/stocks/* and /api/v1/instruments (SPEC.md section 64).

Same conventions as tests/api/test_api.py: in-process ASGI client, DB
dependency override onto the shared `db_session` fixture, synthetic
OHLCV rows seeded directly (never via yfinance/network).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily


def _trading_dates(n: int, end: date) -> list[date]:
    """n business days ending at `end` (inclusive), oldest first."""
    dates: list[date] = []
    current = end
    while len(dates) < n:
        if current.weekday() < 5:
            dates.append(current)
        current -= timedelta(days=1)
    return list(reversed(dates))


async def _seed_instrument_with_bars(
    db_session,
    symbol: str,
    sector: str | None,
    closes: list[float],
    end_date: date,
    exchange: str = "NSE",
) -> Instrument:
    instrument = Instrument(symbol=symbol, exchange=exchange, company_name=f"{symbol} Ltd", sector=sector)
    db_session.add(instrument)
    await db_session.flush()

    dates = _trading_dates(len(closes), end_date)
    for trading_date, close in zip(dates, closes, strict=True):
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
    return instrument


def _override_db(db_session):
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session


def _clear_override():
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture
def today() -> date:
    return date(2025, 6, 30)


@pytest.mark.asyncio
async def test_list_instruments_returns_all_active(db_session):
    db_session.add_all(
        [
            Instrument(symbol="RELIANCE", exchange="NSE", company_name="Reliance Industries Ltd", sector="Energy"),
            Instrument(symbol="TCS", exchange="NSE", company_name="Tata Consultancy Services Ltd", sector="IT"),
            Instrument(symbol="DEAD", exchange="NSE", company_name="Delisted Co", sector="IT", active=False),
        ]
    )
    await db_session.commit()
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments")
    finally:
        _clear_override()

    assert response.status_code == 200
    symbols = [i["symbol"] for i in response.json()]
    assert symbols == ["RELIANCE", "TCS"]  # active only, alphabetical


@pytest.mark.asyncio
async def test_get_price_unknown_symbol_is_404(db_session):
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOPE/price")
    finally:
        _clear_override()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_price_instrument_with_zero_bars_is_422_not_500(db_session):
    db_session.add(Instrument(symbol="EMPTY", exchange="NSE", company_name="No Data Ltd"))
    await db_session.commit()
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/EMPTY/price")
    finally:
        _clear_override()
    assert response.status_code == 422
    assert "no OHLCV data" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_price_returns_bars_scoped_to_range(db_session, today):
    closes = [100.0 + i * 0.1 for i in range(300)]
    await _seed_instrument_with_bars(db_session, "RELIANCE", "Energy", closes, today)
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp_1m = await client.get("/api/v1/stocks/RELIANCE/price", params={"range": "1M"})
            resp_all = await client.get("/api/v1/stocks/RELIANCE/price", params={"range": "ALL"})
            resp_default = await client.get("/api/v1/stocks/RELIANCE/price")
    finally:
        _clear_override()

    assert resp_1m.status_code == 200
    body_1m = resp_1m.json()
    assert len(body_1m["bars"]) < len(resp_all.json()["bars"])
    assert body_1m["range"] == "1M"
    # last bar should be the latest trading day we seeded
    assert body_1m["bars"][-1]["close"] == pytest.approx(closes[-1])
    assert body_1m["data_freshness"]["latest_trading_date"] is not None

    assert resp_default.json()["range"] == "6M"


@pytest.mark.asyncio
async def test_get_technicals_rsi_in_bounds_and_series_aligned(db_session, today):
    closes = [100.0 + i * 0.3 + (2 if i % 5 == 0 else -1) for i in range(260)]
    await _seed_instrument_with_bars(db_session, "TCS", "IT", closes, today)
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/TCS/technicals", params={"range": "3M"})
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    snapshot = body["snapshot"]
    assert 0 <= snapshot["rsi_14"] <= 100
    assert snapshot["sma_200"] is not None  # 260 bars seeded, enough for SMA200

    series = body["series"]
    assert len(series["dates"]) == len(series["close"]) == len(series["ema_20"]) == len(series["rsi_14"])
    assert all(0 <= v <= 100 for v in series["rsi_14"] if v is not None)


@pytest.mark.asyncio
async def test_get_technicals_short_history_has_null_long_window_fields(db_session, today):
    closes = [100.0 + i for i in range(30)]
    await _seed_instrument_with_bars(db_session, "NEWCO", "IT", closes, today)
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NEWCO/technicals")
    finally:
        _clear_override()

    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["sma_200"] is None
    assert snapshot["ema_200"] is None


@pytest.mark.asyncio
async def test_get_technicals_zero_bars_is_422(db_session):
    db_session.add(Instrument(symbol="EMPTY2", exchange="NSE", company_name="No Data Ltd"))
    await db_session.commit()
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/EMPTY2/technicals")
    finally:
        _clear_override()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_relative_strength_computes_against_sector_peers(db_session, today):
    # Stock up 20% over the full window; two IT peers up 10% and 0% -> avg peer +5%.
    n = 260
    stock_closes = [100.0 * (1.20 ** (i / (n - 1))) for i in range(n)]
    peer1_closes = [100.0 * (1.10 ** (i / (n - 1))) for i in range(n)]
    peer2_closes = [100.0 for _ in range(n)]

    await _seed_instrument_with_bars(db_session, "TCS", "IT", stock_closes, today)
    await _seed_instrument_with_bars(db_session, "INFY", "IT", peer1_closes, today)
    await _seed_instrument_with_bars(db_session, "WIPRO", "IT", peer2_closes, today)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/TCS/relative-strength")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["peer_universe"] == "seeded_sector_peers"
    assert body["peer_count"] == 2
    assert set(body["peer_symbols"]) == {"INFY", "WIPRO"}

    # 1Y horizon = trailing 252 trading bars, not the full 260-bar seeded
    # history, so compute the expected returns the same way the endpoint
    # does (over the last 252 bars) rather than assuming the full +20%/+10%.
    bars = 252
    expected_stock = (stock_closes[-1] / stock_closes[-1 - bars] - 1.0) * 100.0
    expected_peer1 = (peer1_closes[-1] / peer1_closes[-1 - bars] - 1.0) * 100.0
    expected_peer2 = (peer2_closes[-1] / peer2_closes[-1 - bars] - 1.0) * 100.0
    expected_peer_avg = (expected_peer1 + expected_peer2) / 2

    # abs=0.01 tolerance: OHLCVDaily.close is a Numeric(18,4) DB column, so
    # the seeded floats go through a 4-decimal-place round-trip server-side.
    one_year = body["metrics"]["1Y"]
    assert one_year["reason"] is None
    assert one_year["stock_return_pct"] == pytest.approx(expected_stock, abs=0.01)
    assert one_year["peer_avg_return_pct"] == pytest.approx(expected_peer_avg, abs=0.01)
    assert one_year["relative_strength_pct"] == pytest.approx(
        one_year["stock_return_pct"] - one_year["peer_avg_return_pct"], abs=1e-6
    )


@pytest.mark.asyncio
async def test_relative_strength_insufficient_peers_returns_null_not_fabricated(db_session, today):
    closes = [100.0 + i * 0.1 for i in range(260)]
    await _seed_instrument_with_bars(db_session, "LONELY", "Niche Sector", closes, today)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/LONELY/relative-strength")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["peer_count"] == 0
    for horizon in body["metrics"].values():
        assert horizon["peer_avg_return_pct"] is None
        assert horizon["relative_strength_pct"] is None
        assert horizon["reason"] == "insufficient_peer_universe"
        # the stock's OWN return is real data, not a fabricated comparison - still shown.
        assert horizon["stock_return_pct"] is not None


@pytest.mark.asyncio
async def test_relative_strength_no_sector_returns_null_with_reason(db_session, today):
    closes = [100.0 + i * 0.1 for i in range(260)]
    await _seed_instrument_with_bars(db_session, "NOSECTOR", None, closes, today)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOSECTOR/relative-strength")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["sector"] is None
    assert all(h["reason"] == "insufficient_peer_universe" for h in body["metrics"].values())


@pytest.mark.asyncio
async def test_relative_strength_unknown_symbol_is_404(db_session):
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOPE/relative-strength")
    finally:
        _clear_override()
    assert response.status_code == 404
