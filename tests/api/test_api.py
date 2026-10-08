"""API tests for /health and /api/v1/instruments/search (SPEC.md section 64).

Uses httpx.AsyncClient against the FastAPI app in-process (ASGI
transport) - no real server, no real network. The DB dependency is
overridden to use the test session fixture from tests/conftest.py.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.common.db import get_db_session
from packages.common.models import Instrument


@pytest.mark.asyncio
async def test_health_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_search_instruments_matches_symbol_and_company_name(db_session):
    db_session.add_all(
        [
            Instrument(symbol="RELIANCE", exchange="NSE", company_name="Reliance Industries Ltd", sector="Energy"),
            Instrument(symbol="TCS", exchange="NSE", company_name="Tata Consultancy Services Ltd", sector="IT"),
        ]
    )
    await db_session.commit()

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            by_symbol = await client.get("/api/v1/instruments/search", params={"q": "RELI"})
            by_name = await client.get("/api/v1/instruments/search", params={"q": "Tata Consultancy"})
            no_match = await client.get("/api/v1/instruments/search", params={"q": "doesnotexist"})
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert by_symbol.status_code == 200
    assert [i["symbol"] for i in by_symbol.json()] == ["RELIANCE"]

    assert by_name.status_code == 200
    assert [i["symbol"] for i in by_name.json()] == ["TCS"]

    assert no_match.status_code == 200
    assert no_match.json() == []


@pytest.mark.asyncio
async def test_get_instrument_returns_404_for_unknown_symbol(db_session):
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments/NOPE")
    finally:
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 404
