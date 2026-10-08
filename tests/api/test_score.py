"""API tests for /api/v1/stocks/{symbol}/score and /evidence (SPEC.md sections 17-22, 46, 64)."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily
from packages.scoring.constants import METHODOLOGY_VERSION


def _override_db(db_session):
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session


def _clear_override():
    app.dependency_overrides.pop(get_db_session, None)


def _trading_dates(n: int, end: date) -> list[date]:
    dates: list[date] = []
    current = end
    while len(dates) < n:
        if current.weekday() < 5:
            dates.append(current)
        current -= timedelta(days=1)
    return list(reversed(dates))


async def _seed_bars(db_session, instrument, closes, end_date) -> None:
    dates = _trading_dates(len(closes), end_date)
    for trading_date, close in zip(dates, closes, strict=True):
        db_session.add(
            OHLCVDaily(
                id=uuid.uuid4(), instrument_id=instrument.id, trading_date=trading_date,
                open=close, high=close * 1.01, low=close * 0.99, close=close, adjusted_close=close,
                volume=1_000_000, source="fake", source_timestamp=datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC),
            )
        )
    await db_session.commit()


@pytest.fixture
def today() -> date:
    return date(2025, 6, 30)


@pytest.mark.asyncio
async def test_score_unknown_symbol_is_404(db_session):
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOPE/score")
    finally:
        _clear_override()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_score_zero_bars_is_422(db_session):
    db_session.add(Instrument(symbol="EMPTYSCORE", exchange="NSE", company_name="No Data Ltd"))
    await db_session.commit()
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/EMPTYSCORE/score")
    finally:
        _clear_override()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_score_and_evidence_round_trip(db_session, today):
    instrument = Instrument(symbol="SCORECO", exchange="NSE", company_name="Score Co Ltd", sector="IT")
    db_session.add(instrument)
    await db_session.flush()

    closes = [100.0 + i * 0.2 + (1.0 if i % 9 == 0 else -0.3) for i in range(300)]
    await _seed_bars(db_session, instrument, closes, today)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            score_response = await client.get("/api/v1/stocks/SCORECO/score")
            evidence_response = await client.get("/api/v1/stocks/SCORECO/evidence")
    finally:
        _clear_override()

    assert score_response.status_code == 200
    score_body = score_response.json()
    assert score_body["methodology_version"] == METHODOLOGY_VERSION
    assert score_body["score"] is None or 0.0 <= score_body["score"] <= 100.0
    assert 0.0 <= score_body["confidence"] <= 100.0
    news = next(c for c in score_body["components"] if c["name"] == "event_news_context")
    assert news["available"] is False

    assert evidence_response.status_code == 200
    evidence_body = evidence_response.json()
    assert evidence_body["count"] > 0

    # Every evidence_id referenced by the score response is present in
    # the evidence list for this instrument (SPEC.md section 25's
    # validation principle, applied without an LLM in the loop).
    evidence_ids_in_list = {item["id"] for item in evidence_body["items"]}
    referenced = {eid for c in score_body["components"] for eid in c["evidence"]}
    assert referenced <= evidence_ids_in_list
