"""Redis caching for GET /stocks/{symbol}/score (SPEC.md section 59).

Proves: (1) a cache hit returns without touching the DB's
`research_scores` table again, (2) a cache miss falls through to the
original live-compute-and-persist path and populates the cache, and
(3) the batch job's write-through payload is readable straight back
out of Redis via the exact key the on-demand route checks.

Uses `fakeredis`'s async client (not a real Redis connection) via
`packages.common.cache.get_redis_client`, monkeypatched for the
duration of each test - this is the module-level accessor every
`cache.get_json`/`cache.set_json` call (with no explicit `client=`)
resolves at call time, so patching it here exercises the exact same
code path `apps/api/routes/scoring.py` uses in production, just against
an in-memory fake instead of a real Redis connection.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fakeredis import aioredis as fake_aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from apps.api.main import app
from packages.common import cache
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily
from packages.scoring.constants import METHODOLOGY_VERSION
from packages.scoring.engine import score_cache_key, to_score_response_payload
from packages.scoring.models import ResearchScore


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


async def _seed_instrument_with_bars(db_session, symbol: str, today: date) -> Instrument:
    instrument = Instrument(symbol=symbol, exchange="NSE", company_name=f"{symbol} Ltd", sector="IT")
    db_session.add(instrument)
    await db_session.flush()

    closes = [100.0 + i * 0.2 + (1.0 if i % 9 == 0 else -0.3) for i in range(300)]
    for trading_date, close in zip(_trading_dates(len(closes), today), closes, strict=True):
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
    return instrument


async def _research_scores_count(db_session, instrument_id) -> int:
    stmt = select(func.count()).select_from(ResearchScore).where(ResearchScore.instrument_id == instrument_id)
    return (await db_session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_cache_miss_computes_persists_and_populates_cache(db_session, fake_redis):
    today = date(2025, 6, 30)
    instrument = await _seed_instrument_with_bars(db_session, "CACHEMISS", today)

    assert await _research_scores_count(db_session, instrument.id) == 0

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/CACHEMISS/score")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["cache_hit"] is False

    # The live path's usual side effect still happened on a miss.
    assert await _research_scores_count(db_session, instrument.id) == 1

    # And the cache is now warm for next time.
    cached = await cache.get_json(score_cache_key(instrument.id), client=fake_redis)
    assert cached is not None
    assert cached["symbol"] == "CACHEMISS"


@pytest.mark.asyncio
async def test_cache_hit_never_touches_the_db(db_session, fake_redis):
    today = date(2025, 6, 30)
    instrument = await _seed_instrument_with_bars(db_session, "CACHEHIT", today)

    # Pre-populate the cache directly - simulates a prior batch-job
    # write-through or a prior on-demand miss, without ever calling the
    # live-compute path for this test.
    fake_payload = {
        "instrument_id": str(instrument.id),
        "symbol": "CACHEHIT",
        "exchange": "NSE",
        "as_of_date": today.isoformat(),
        "computed_at": datetime.now(UTC).isoformat(),
        "score": 77.0,
        "confidence": 88.0,
        "band": "Strong",
        "methodology_version": METHODOLOGY_VERSION,
        "components": [],
        "bull_case": [],
        "bear_case": [],
    }
    await cache.set_json(score_cache_key(instrument.id), fake_payload, 1800, client=fake_redis)

    assert await _research_scores_count(db_session, instrument.id) == 0

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/CACHEHIT/score")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["cache_hit"] is True
    assert body["score"] == 77.0
    assert body["band"] == "Strong"

    # No new research_scores row was ever written - the cache hit short-circuited
    # the entire live-compute-and-persist path, never touching the DB for this call.
    assert await _research_scores_count(db_session, instrument.id) == 0


@pytest.mark.asyncio
async def test_batch_job_write_through_payload_is_readable_via_the_on_demand_cache_key(db_session, fake_redis):
    """Proves the exact helper the batch job uses to populate Redis
    (`to_score_response_payload` + `score_cache_key`, see
    apps/worker/jobs.py::compute_all_scores_job) round-trips through the
    cache correctly and under the same key the on-demand route reads."""
    today = date(2025, 6, 30)
    instrument = await _seed_instrument_with_bars(db_session, "BATCHWRITE", today)

    from packages.scoring.engine import compute_research_score

    result = await compute_research_score(db_session, instrument)

    # This is exactly what apps/worker/jobs.py::compute_all_scores_job does
    # right after computing each instrument's score.
    await cache.set_json(
        score_cache_key(instrument.id), to_score_response_payload(result), 1800, client=fake_redis
    )

    cached = await cache.get_json(score_cache_key(instrument.id), client=fake_redis)
    assert cached is not None
    assert cached["symbol"] == "BATCHWRITE"
    assert cached["score"] == result.score
    assert cached["methodology_version"] == result.methodology_version

    # And the on-demand route serves exactly this cached value on its next call.
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/BATCHWRITE/score")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["cache_hit"] is True
    assert body["score"] == result.score
