"""API tests for /api/v1/market/* (SPEC.md section 15, 48, 64; UI/UX
"Market Pulse" dashboard task for score-distribution/sectors)."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from fakeredis import aioredis as fake_aioredis
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.common import cache
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily
from packages.momentum.models import MomentumScan
from packages.momentum.scanner import DEFAULT_SMA200_TREND_LOOKBACK_DAYS
from packages.momentum.scanner import METHODOLOGY_VERSION as MOMENTUM_METHODOLOGY_VERSION
from packages.regime.classifier import RULE_VERSION
from packages.regime.models import MarketRegime, MarketRegimeLabel
from packages.scoring.constants import METHODOLOGY_VERSION
from packages.scoring.models import ResearchScore


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


@pytest.mark.asyncio
async def test_market_regime_not_yet_computed_is_404(db_session):
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/market/regime")
    finally:
        _clear_override()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_market_regime_returns_latest_with_breadth_universe_label(db_session):
    db_session.add(
        MarketRegime(
            id=uuid.uuid4(), date=date(2025, 6, 30), regime=MarketRegimeLabel.bullish_trend,
            nifty_close=25000.0, nifty_vs_200dma_pct=5.5, breadth_above_50dma_pct=72.0,
            breadth_above_200dma_pct=68.0, rolling_volatility_pct=13.0, rule_version=RULE_VERSION,
        )
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/market/regime")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["regime"] == "BULLISH_TREND"
    assert body["breadth_universe"] == "seeded_117"
    assert body["rule_version"] == RULE_VERSION
    assert body["nifty_close"] == pytest.approx(25000.0)


# --- GET /api/v1/market/score-distribution (UI/UX "Market Pulse" task) ---
# Hand-verified against a small, known set of instruments/scores: 2
# "Very Weak" (score < 30), 1 "Weak" (30 <= score < 45), 1 unscored.


async def _add_score(db_session, instrument: Instrument, score: float, computed_at: datetime) -> None:
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


@pytest.mark.asyncio
async def test_score_distribution_counts_match_hand_verified_bands(db_session):
    now = datetime(2026, 6, 30, tzinfo=UTC)
    very_weak_1 = Instrument(symbol="VW1", exchange="NSE", company_name="VW1 Ltd")
    very_weak_2 = Instrument(symbol="VW2", exchange="NSE", company_name="VW2 Ltd")
    weak_1 = Instrument(symbol="WK1", exchange="NSE", company_name="WK1 Ltd")
    unscored = Instrument(symbol="UNSCORED1", exchange="NSE", company_name="Unscored Ltd")
    db_session.add_all([very_weak_1, very_weak_2, weak_1, unscored])
    await db_session.commit()

    await _add_score(db_session, very_weak_1, 10.0, now)  # Very Weak (< 30)
    await _add_score(db_session, very_weak_2, 29.9, now)  # Very Weak (< 30)
    await _add_score(db_session, weak_1, 40.0, now)  # Weak (30 <= x < 45)
    # `unscored` has no persisted research_scores row at all.

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/market/score-distribution")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    counts = {b["band"]: b["count"] for b in body["bands"]}
    assert counts["Very Weak"] == 2
    assert counts["Weak"] == 1
    assert counts["Neutral"] == 0
    assert body["unscored_count"] == 1
    assert body["universe_size"] == 4


@pytest.mark.asyncio
async def test_score_distribution_response_is_cached(db_session, fake_redis):
    instrument = Instrument(symbol="CACHEDIST", exchange="NSE", company_name="Cached Dist Ltd")
    db_session.add(instrument)
    await db_session.commit()
    await _add_score(db_session, instrument, 10.0, datetime(2026, 6, 30, tzinfo=UTC))

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/api/v1/market/score-distribution")
            db_session.add(Instrument(symbol="ADDEDAFTER", exchange="NSE", company_name="Added After Ltd"))
            await db_session.commit()
            second = await client.get("/api/v1/market/score-distribution")
    finally:
        _clear_override()

    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()  # second call served from cache, unaffected by the new row


# --- GET /api/v1/market/sectors (UI/UX "Market Pulse" task) ---
# Hand-verified against a small, known set: 2 IT-sector instruments with
# scores 40/60 (avg 50) and day changes +2%/-4% (avg -1%), 1 passing
# Stage 2; 1 Energy-sector instrument with no score/momentum/price-change
# data at all (must not contribute a fabricated 0 to any average).


async def _add_momentum(db_session, instrument: Instrument, passed: bool, computed_at: datetime) -> None:
    db_session.add(
        MomentumScan(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            scan_date=computed_at.date(),
            passed=passed,
            conditions=[],
            distance_from_52w_high_pct=-5.0,
            rs_rank=80.0 if passed else 40.0,
            sma200_trend_lookback_days=DEFAULT_SMA200_TREND_LOOKBACK_DAYS,
            methodology_version=MOMENTUM_METHODOLOGY_VERSION,
            computed_at=computed_at,
        )
    )
    await db_session.commit()


async def _add_two_bars(db_session, instrument: Instrument, prev_close: float, latest_close: float) -> None:
    db_session.add_all(
        [
            OHLCVDaily(
                id=uuid.uuid4(), instrument_id=instrument.id, trading_date=date(2026, 10, 1),
                open=prev_close, high=prev_close, low=prev_close, close=prev_close, adjusted_close=prev_close,
                volume=1_000_000, source="fake", source_timestamp=datetime(2026, 10, 1, tzinfo=UTC),
            ),
            OHLCVDaily(
                id=uuid.uuid4(), instrument_id=instrument.id, trading_date=date(2026, 10, 2),
                open=latest_close, high=latest_close, low=latest_close, close=latest_close, adjusted_close=latest_close,
                volume=1_000_000, source="fake", source_timestamp=datetime(2026, 10, 2, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_sectors_aggregate_matches_hand_verified_averages(db_session):
    now = datetime(2026, 6, 30, tzinfo=UTC)
    it_a = Instrument(symbol="ITA", exchange="NSE", company_name="IT A Ltd", sector="IT")
    it_b = Instrument(symbol="ITB", exchange="NSE", company_name="IT B Ltd", sector="IT")
    energy_bare = Instrument(symbol="ENERGYBARE", exchange="NSE", company_name="Energy Bare Ltd", sector="Energy")
    db_session.add_all([it_a, it_b, energy_bare])
    await db_session.commit()

    await _add_score(db_session, it_a, 40.0, now)
    await _add_score(db_session, it_b, 60.0, now)
    await _add_two_bars(db_session, it_a, 100.0, 102.0)  # +2%
    await _add_two_bars(db_session, it_b, 100.0, 96.0)  # -4%
    await _add_momentum(db_session, it_a, True, now)
    await _add_momentum(db_session, it_b, False, now)
    # energy_bare: no score, no momentum scan, no OHLCV at all.

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/market/sectors")
    finally:
        _clear_override()

    assert response.status_code == 200
    sectors = {s["sector"]: s for s in response.json()["sectors"]}

    it_summary = sectors["IT"]
    assert it_summary["instrument_count"] == 2
    assert it_summary["avg_score"] == pytest.approx(50.0)
    assert it_summary["avg_day_change_pct"] == pytest.approx(-1.0)
    assert it_summary["momentum_pass_count"] == 1

    energy_summary = sectors["Energy"]
    assert energy_summary["instrument_count"] == 1
    assert energy_summary["avg_score"] is None  # never fabricated into 0
    assert energy_summary["avg_day_change_pct"] is None
    assert energy_summary["momentum_pass_count"] == 0


@pytest.mark.asyncio
async def test_sectors_groups_null_sector_as_unclassified(db_session):
    instrument = Instrument(symbol="NOSECTOR", exchange="NSE", company_name="No Sector Ltd", sector=None)
    db_session.add(instrument)
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/market/sectors")
    finally:
        _clear_override()

    assert response.status_code == 200
    sectors = {s["sector"]: s for s in response.json()["sectors"]}
    assert "Unclassified" in sectors
    assert sectors["Unclassified"]["instrument_count"] == 1
