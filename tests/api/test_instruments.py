"""API tests for GET /api/v1/instruments sorting + score join (UI/UX task).

Same conventions as tests/api/test_api.py and tests/api/test_stocks.py:
in-process ASGI client, DB dependency override onto the shared
`db_session` fixture, synthetic rows seeded directly (never via a real
score computation or network call).

These tests cover the new `sort`/`order` query params and the
left-join onto the most recently persisted `research_scores` row per
instrument - not the scoring methodology itself (unchanged, see
packages/scoring/).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fakeredis import aioredis as fake_aioredis
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.analyst_estimates.models import AnalystEstimate
from packages.common import cache
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily
from packages.momentum.models import MomentumScan
from packages.momentum.scanner import DEFAULT_SMA200_TREND_LOOKBACK_DAYS
from packages.momentum.scanner import METHODOLOGY_VERSION as MOMENTUM_METHODOLOGY_VERSION
from packages.scoring.constants import METHODOLOGY_VERSION
from packages.scoring.models import ResearchScore


@pytest.fixture(autouse=True)
async def fake_redis(monkeypatch):
    """Isolates every test in this file from the real Redis instance and
    from any other test's cached listing - the listing endpoint is
    cache-first (SPEC.md section 59), so without this, two tests hitting
    the same cache key (same exchange/sort/order/filter) could read each
    other's cached rows instead of a fresh query."""
    client = fake_aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache, "get_redis_client", lambda: client)
    yield client
    await client.aclose()


async def _add_momentum_scan(
    db_session, instrument: Instrument, passed: bool | None, distance_from_high: float | None, computed_at: datetime
) -> None:
    db_session.add(
        MomentumScan(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            scan_date=computed_at.date(),
            passed=passed,
            conditions=[],
            distance_from_52w_high_pct=distance_from_high,
            rs_rank=80.0 if passed else 40.0,
            sma200_trend_lookback_days=DEFAULT_SMA200_TREND_LOOKBACK_DAYS,
            methodology_version=MOMENTUM_METHODOLOGY_VERSION,
            computed_at=computed_at,
        )
    )
    await db_session.commit()


def _override_db(db_session):
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session


def _clear_override():
    app.dependency_overrides.pop(get_db_session, None)


async def _add_score(db_session, instrument: Instrument, score: float | None, computed_at: datetime) -> None:
    db_session.add(
        ResearchScore(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            computed_at=computed_at,
            score=score,
            confidence=75.0,
            methodology_version=METHODOLOGY_VERSION,
            components=[],
            bull_case=[],
            bear_case=[],
        )
    )
    await db_session.commit()


@pytest.fixture
def now() -> datetime:
    return datetime(2025, 6, 30, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_list_instruments_default_sort_is_symbol_ascending(db_session):
    db_session.add_all(
        [
            Instrument(symbol="TCS", exchange="NSE", company_name="Tata Consultancy Services Ltd", sector="IT"),
            Instrument(symbol="RELIANCE", exchange="NSE", company_name="Reliance Industries Ltd", sector="Energy"),
            Instrument(symbol="INFY", exchange="NSE", company_name="Infosys Ltd", sector="IT"),
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
    body = response.json()
    assert [row["symbol"] for row in body] == ["INFY", "RELIANCE", "TCS"]
    # No research_scores rows exist yet - every instrument reports a null score/band.
    assert all(row["score"] is None and row["band"] is None and row["confidence"] is None for row in body)


@pytest.mark.asyncio
async def test_list_instruments_sort_by_score_desc_and_asc(db_session, now):
    high = Instrument(symbol="HIGH", exchange="NSE", company_name="High Score Ltd", sector="IT")
    mid = Instrument(symbol="MID", exchange="NSE", company_name="Mid Score Ltd", sector="IT")
    low = Instrument(symbol="LOW", exchange="NSE", company_name="Low Score Ltd", sector="IT")
    unscored = Instrument(symbol="NOSCORE", exchange="NSE", company_name="No Score Ltd", sector="IT")
    db_session.add_all([high, mid, low, unscored])
    await db_session.commit()

    await _add_score(db_session, high, 90.0, now)
    await _add_score(db_session, mid, 50.0, now)
    await _add_score(db_session, low, 10.0, now)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            desc = await client.get("/api/v1/instruments", params={"sort": "score", "order": "desc"})
            asc = await client.get("/api/v1/instruments", params={"sort": "score", "order": "asc"})
    finally:
        _clear_override()

    assert desc.status_code == 200 and asc.status_code == 200
    desc_symbols = [row["symbol"] for row in desc.json()]
    asc_symbols = [row["symbol"] for row in asc.json()]

    # Nulls sort last regardless of direction.
    assert desc_symbols == ["HIGH", "MID", "LOW", "NOSCORE"]
    assert asc_symbols == ["LOW", "MID", "HIGH", "NOSCORE"]

    high_row = next(row for row in desc.json() if row["symbol"] == "HIGH")
    assert high_row["score"] == 90.0
    assert high_row["band"] == "Very Strong"
    assert high_row["confidence"] == 75.0

    noscore_row = next(row for row in desc.json() if row["symbol"] == "NOSCORE")
    assert noscore_row["score"] is None
    assert noscore_row["band"] is None
    assert noscore_row["confidence"] is None


@pytest.mark.asyncio
async def test_list_instruments_sort_by_score_uses_most_recently_persisted_row(db_session, now):
    instrument = Instrument(symbol="EVOLV", exchange="NSE", company_name="Evolving Ltd", sector="IT")
    db_session.add(instrument)
    await db_session.commit()

    # Oldest score first, then a fresher one - the endpoint must report
    # the fresher (most recently computed) row, matching the on-demand
    # /score endpoint's "latest wins" append-only history semantics.
    await _add_score(db_session, instrument, 20.0, now - timedelta(days=1))
    await _add_score(db_session, instrument, 80.0, now)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments")
    finally:
        _clear_override()

    assert response.status_code == 200
    row = next(r for r in response.json() if r["symbol"] == "EVOLV")
    assert row["score"] == 80.0
    assert row["band"] == "Strong"


@pytest.mark.asyncio
async def test_list_instruments_sort_by_symbol_and_sector_desc(db_session):
    db_session.add_all(
        [
            Instrument(symbol="TCS", exchange="NSE", company_name="Tata Consultancy Services Ltd", sector="IT"),
            Instrument(symbol="RELIANCE", exchange="NSE", company_name="Reliance Industries Ltd", sector="Energy"),
            Instrument(symbol="INFY", exchange="NSE", company_name="Infosys Ltd", sector="IT"),
        ]
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            symbol_desc = await client.get("/api/v1/instruments", params={"sort": "symbol", "order": "desc"})
            sector_asc = await client.get("/api/v1/instruments", params={"sort": "sector", "order": "asc"})
    finally:
        _clear_override()

    assert symbol_desc.status_code == 200
    assert [row["symbol"] for row in symbol_desc.json()] == ["TCS", "RELIANCE", "INFY"]

    assert sector_asc.status_code == 200
    # Energy < IT alphabetically; ties within a sector break on symbol ascending.
    assert [row["symbol"] for row in sector_asc.json()] == ["RELIANCE", "INFY", "TCS"]


@pytest.mark.asyncio
async def test_list_instruments_rejects_invalid_sort_and_order(db_session):
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            bad_sort = await client.get("/api/v1/instruments", params={"sort": "nope"})
            bad_order = await client.get("/api/v1/instruments", params={"order": "sideways"})
    finally:
        _clear_override()

    assert bad_sort.status_code == 422
    assert bad_order.status_code == 422


@pytest.mark.asyncio
async def test_list_instruments_momentum_pass_filter(db_session, now):
    passer = Instrument(symbol="PASSER", exchange="NSE", company_name="Passer Ltd", sector="IT")
    failer = Instrument(symbol="FAILER", exchange="NSE", company_name="Failer Ltd", sector="IT")
    unscanned = Instrument(symbol="UNSCANNED", exchange="NSE", company_name="Unscanned Ltd", sector="IT")
    db_session.add_all([passer, failer, unscanned])
    await db_session.commit()

    await _add_momentum_scan(db_session, passer, True, -2.5, now)
    await _add_momentum_scan(db_session, failer, False, -40.0, now)
    # `unscanned` has no momentum_scans row at all.

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments", params={"momentum_pass": "true"})
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    symbols = [row["symbol"] for row in body]
    # Only the genuine, evaluable PASS is returned - never the FAIL and
    # never the not-yet-scanned instrument (null is not falsely treated
    # as either outcome).
    assert symbols == ["PASSER"]
    assert body[0]["momentum_pass"] is True
    assert body[0]["distance_from_52w_high_pct"] == -2.5


@pytest.mark.asyncio
async def test_list_instruments_sort_by_momentum_pass_true_first_desc(db_session, now):
    passer = Instrument(symbol="PASSER2", exchange="NSE", company_name="Passer2 Ltd", sector="IT")
    failer = Instrument(symbol="FAILER2", exchange="NSE", company_name="Failer2 Ltd", sector="IT")
    unscanned = Instrument(symbol="UNSCANNED2", exchange="NSE", company_name="Unscanned2 Ltd", sector="IT")
    db_session.add_all([passer, failer, unscanned])
    await db_session.commit()

    await _add_momentum_scan(db_session, passer, True, -2.5, now)
    await _add_momentum_scan(db_session, failer, False, -40.0, now)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            desc = await client.get("/api/v1/instruments", params={"sort": "momentum_pass", "order": "desc"})
    finally:
        _clear_override()

    assert desc.status_code == 200
    symbols = [row["symbol"] for row in desc.json()]
    # true-first on desc, nulls always last regardless of direction.
    assert symbols == ["PASSER2", "FAILER2", "UNSCANNED2"]


@pytest.mark.asyncio
async def test_list_instruments_uses_most_recently_persisted_momentum_scan(db_session, now):
    instrument = Instrument(symbol="EVOLVMOM", exchange="NSE", company_name="Evolving Mom Ltd", sector="IT")
    db_session.add(instrument)
    await db_session.commit()

    await _add_momentum_scan(db_session, instrument, False, -40.0, now - timedelta(days=1))
    await _add_momentum_scan(db_session, instrument, True, -1.0, now)

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments")
    finally:
        _clear_override()

    assert response.status_code == 200
    row = next(r for r in response.json() if r["symbol"] == "EVOLVMOM")
    assert row["momentum_pass"] is True
    assert row["distance_from_52w_high_pct"] == -1.0


@pytest.mark.asyncio
async def test_list_instruments_response_is_cached(db_session, fake_redis):
    db_session.add(Instrument(symbol="CACHEDLIST", exchange="NSE", company_name="Cached List Ltd"))
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/api/v1/instruments")
            # A second instrument added *after* the first call must not
            # appear in a second call within the TTL - proves the second
            # call was served from cache, not a fresh query.
            db_session.add(Instrument(symbol="ADDEDLATER", exchange="NSE", company_name="Added Later Ltd"))
            await db_session.commit()
            second = await client.get("/api/v1/instruments")
    finally:
        _clear_override()

    assert first.status_code == 200 and second.status_code == 200
    assert [r["symbol"] for r in first.json()] == [r["symbol"] for r in second.json()]
    assert "ADDEDLATER" not in [r["symbol"] for r in second.json()]


# --- day_change_pct (UI/UX "Market Pulse" dashboard task) ---
# A single window-function query (apps/api/routes/instruments.py /
# packages/common/listing_queries.py::latest_price_change_subquery) -
# these tests exercise its boundary cases: 0, 1, and 2+ OHLCV rows ever
# ingested for an instrument.


async def _add_bar(db_session, instrument: Instrument, close: float, trading_date) -> None:
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


@pytest.mark.asyncio
async def test_day_change_pct_with_two_bars_is_computed_correctly(db_session):
    from datetime import date

    instrument = Instrument(symbol="TWOBAR", exchange="NSE", company_name="Two Bar Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_bar(db_session, instrument, 100.0, date(2026, 10, 1))  # yesterday
    await _add_bar(db_session, instrument, 110.0, date(2026, 10, 2))  # today, +10%

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments")
    finally:
        _clear_override()

    assert response.status_code == 200
    row = next(r for r in response.json() if r["symbol"] == "TWOBAR")
    assert row["day_change_pct"] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_day_change_pct_is_null_not_a_crash_with_only_one_bar_ever(db_session):
    """Boundary case explicitly required by the task: an instrument with
    only one OHLCV row ever must report `day_change_pct: null`, never
    raise, never fabricate a 0%/divide-by-zero result."""
    from datetime import date

    instrument = Instrument(symbol="ONEBAR", exchange="NSE", company_name="One Bar Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_bar(db_session, instrument, 100.0, date(2026, 10, 2))

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments")
    finally:
        _clear_override()

    assert response.status_code == 200
    row = next(r for r in response.json() if r["symbol"] == "ONEBAR")
    assert row["day_change_pct"] is None


@pytest.mark.asyncio
async def test_day_change_pct_is_null_with_zero_bars_ever(db_session):
    instrument = Instrument(symbol="NOBAR", exchange="NSE", company_name="No Bar Ltd")
    db_session.add(instrument)
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments")
    finally:
        _clear_override()

    assert response.status_code == 200
    row = next(r for r in response.json() if r["symbol"] == "NOBAR")
    assert row["day_change_pct"] is None


@pytest.mark.asyncio
async def test_sort_by_day_change_pct_nulls_last(db_session):
    from datetime import date

    gainer = Instrument(symbol="GAINER", exchange="NSE", company_name="Gainer Ltd")
    loser = Instrument(symbol="LOSER", exchange="NSE", company_name="Loser Ltd")
    nodata = Instrument(symbol="NODATA", exchange="NSE", company_name="No Data Ltd")
    db_session.add_all([gainer, loser, nodata])
    await db_session.commit()

    await _add_bar(db_session, gainer, 100.0, date(2026, 10, 1))
    await _add_bar(db_session, gainer, 120.0, date(2026, 10, 2))  # +20%
    await _add_bar(db_session, loser, 100.0, date(2026, 10, 1))
    await _add_bar(db_session, loser, 90.0, date(2026, 10, 2))  # -10%

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            desc = await client.get("/api/v1/instruments", params={"sort": "day_change_pct", "order": "desc"})
    finally:
        _clear_override()

    assert desc.status_code == 200
    symbols = [r["symbol"] for r in desc.json()]
    assert symbols == ["GAINER", "LOSER", "NODATA"]


# --- analyst_target_price / analyst_upside_pct / analyst_recommendation
# (UI/UX "Market Pulse" / analyst-rating task) ---


@pytest.mark.asyncio
async def test_analyst_upside_pct_computed_against_latest_close(db_session):
    from datetime import date

    instrument = Instrument(symbol="ANALYZED", exchange="NSE", company_name="Analyzed Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_bar(db_session, instrument, 200.0, date(2026, 10, 2))  # current price
    db_session.add(
        AnalystEstimate(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            target_mean_price=250.0,  # +25% upside
            target_high_price=None,
            target_low_price=None,
            target_median_price=None,
            recommendation_mean=None,
            recommendation_key="buy",
            number_of_analyst_opinions=None,
            source="yfinance",
            source_timestamp=datetime.now(UTC),
        )
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
    row = next(r for r in response.json() if r["symbol"] == "ANALYZED")
    assert row["analyst_target_price"] == pytest.approx(250.0)
    assert row["analyst_upside_pct"] == pytest.approx(25.0)
    assert row["analyst_recommendation"] == "buy"


@pytest.mark.asyncio
async def test_analyst_fields_null_with_zero_coverage(db_session):
    from datetime import date

    instrument = Instrument(symbol="NOANALYST", exchange="NSE", company_name="No Analyst Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_bar(db_session, instrument, 100.0, date(2026, 10, 2))

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/instruments")
    finally:
        _clear_override()

    assert response.status_code == 200
    row = next(r for r in response.json() if r["symbol"] == "NOANALYST")
    assert row["analyst_target_price"] is None
    assert row["analyst_upside_pct"] is None
    assert row["analyst_recommendation"] is None


@pytest.mark.asyncio
async def test_sort_by_analyst_upside_pct_nulls_last(db_session):
    from datetime import date

    covered = Instrument(symbol="COVEREDLST", exchange="NSE", company_name="Covered Lst Ltd")
    uncovered = Instrument(symbol="UNCOVEREDLST", exchange="NSE", company_name="Uncovered Lst Ltd")
    db_session.add_all([covered, uncovered])
    await db_session.commit()
    await _add_bar(db_session, covered, 100.0, date(2026, 10, 2))
    await _add_bar(db_session, uncovered, 100.0, date(2026, 10, 2))
    db_session.add(
        AnalystEstimate(
            id=uuid.uuid4(),
            instrument_id=covered.id,
            target_mean_price=130.0,
            target_high_price=None,
            target_low_price=None,
            target_median_price=None,
            recommendation_mean=None,
            recommendation_key=None,
            number_of_analyst_opinions=None,
            source="yfinance",
            source_timestamp=datetime.now(UTC),
        )
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            desc = await client.get("/api/v1/instruments", params={"sort": "analyst_upside_pct", "order": "desc"})
    finally:
        _clear_override()

    assert desc.status_code == 200
    symbols = [r["symbol"] for r in desc.json()]
    assert symbols == ["COVEREDLST", "UNCOVEREDLST"]
