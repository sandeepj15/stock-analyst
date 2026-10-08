"""API tests for /api/v1/stocks/{symbol}/fundamentals (SPEC.md sections 12, 13, 64)."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.common.db import get_db_session
from packages.common.models import Instrument
from packages.fundamentals.models import FundamentalSnapshot
from packages.market_data.models import OHLCVDaily


def _override_db(db_session):
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session


def _clear_override():
    app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.asyncio
async def test_fundamentals_missing_entirely_returns_null_fields_not_zero(db_session):
    db_session.add(Instrument(symbol="THIN", exchange="NSE", company_name="Thinly Covered Ltd"))
    await db_session.commit()
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/THIN/fundamentals")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["has_fundamental_data"] is False
    assert body["message"] is not None
    assert body["raw"]["revenue"] is None
    assert body["derived"]["revenue_growth_yoy"] is None
    assert body["valuation"]["pe"] is None


@pytest.mark.asyncio
async def test_fundamentals_full_data_computes_derived_and_valuation(db_session):
    instrument = Instrument(symbol="FULLFUN", exchange="NSE", company_name="Full Fundamentals Ltd")
    db_session.add(instrument)
    await db_session.flush()

    db_session.add(
        OHLCVDaily(
            id=uuid.uuid4(), instrument_id=instrument.id, trading_date=date(2025, 6, 30),
            open=100.0, high=101.0, low=99.0, close=100.0, adjusted_close=100.0, volume=1_000_000,
            source="fake", source_timestamp=datetime(2025, 6, 30, 18, 0, tzinfo=UTC),
        )
    )
    db_session.add_all(
        [
            FundamentalSnapshot(
                id=uuid.uuid4(), instrument_id=instrument.id, period_end=date(2025, 3, 31), period_type="FY",
                revenue=1140.0, ebitda=300.0, ebit=250.0, pat=200.0, eps=5.0,
                operating_cash_flow=220.0, free_cash_flow=150.0, total_assets=2000.0, total_liabilities=800.0,
                total_debt=400.0, cash=100.0, equity=1000.0, shares_outstanding=100.0, dividend_yield=0.01,
                source="yfinance", source_timestamp=datetime(2025, 3, 31, 0, 0, tzinfo=UTC),
            ),
            FundamentalSnapshot(
                id=uuid.uuid4(), instrument_id=instrument.id, period_end=date(2024, 3, 31), period_type="FY",
                revenue=1000.0, ebitda=250.0, ebit=200.0, pat=150.0, eps=4.0,
                operating_cash_flow=180.0, free_cash_flow=100.0, total_assets=1800.0, total_liabilities=750.0,
                total_debt=380.0, cash=90.0, equity=900.0, shares_outstanding=100.0, dividend_yield=0.01,
                source="yfinance", source_timestamp=datetime(2024, 3, 31, 0, 0, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/FULLFUN/fundamentals")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["has_fundamental_data"] is True
    assert body["raw"]["revenue"] == pytest.approx(1140.0)
    assert body["derived"]["revenue_growth_yoy"] == pytest.approx(0.14, abs=1e-6)
    assert body["derived"]["roe"] == pytest.approx(0.20, abs=1e-6)
    # close=100, eps=5 -> P/E=20; equity/shares=10 book value -> P/B=10.
    assert body["valuation"]["pe"] == pytest.approx(20.0)
    assert body["valuation"]["pb"] == pytest.approx(10.0)
    assert body["valuation"]["data_age_days"] is not None
    assert isinstance(body["valuation"]["stale"], bool)


@pytest.mark.asyncio
async def test_fundamentals_full_data_includes_fundamental_score_breakdown(db_session):
    """Hand-computed Fundamental Score for a snapshot with full leverage-sub-score inputs
    (interest_expense/current_assets/current_liabilities all present) - proves the new
    fields flow through to `derived` and that `fundamental_score.overall`/`sub_scores`
    match a hand-computed weighted blend (SCORING.md "Fundamental Score")."""
    instrument = Instrument(symbol="SCOREFUN", exchange="NSE", company_name="Score Fundamentals Ltd")
    db_session.add(instrument)
    await db_session.flush()

    db_session.add(
        OHLCVDaily(
            id=uuid.uuid4(), instrument_id=instrument.id, trading_date=date(2025, 6, 30),
            open=100.0, high=101.0, low=99.0, close=100.0, adjusted_close=100.0, volume=1_000_000,
            source="fake", source_timestamp=datetime(2025, 6, 30, 18, 0, tzinfo=UTC),
        )
    )
    db_session.add_all(
        [
            FundamentalSnapshot(
                id=uuid.uuid4(), instrument_id=instrument.id, period_end=date(2025, 3, 31), period_type="FY",
                revenue=1140.0, ebitda=300.0, ebit=250.0, pat=200.0, eps=5.0,
                operating_cash_flow=220.0, free_cash_flow=150.0, total_assets=2000.0, total_liabilities=800.0,
                total_debt=400.0, cash=100.0, equity=1000.0, shares_outstanding=100.0, dividend_yield=0.01,
                interest_expense=25.0, current_assets=600.0, current_liabilities=300.0,
                source="yfinance", source_timestamp=datetime(2025, 3, 31, 0, 0, tzinfo=UTC),
            ),
            FundamentalSnapshot(
                id=uuid.uuid4(), instrument_id=instrument.id, period_end=date(2024, 3, 31), period_type="FY",
                revenue=1000.0, ebitda=250.0, ebit=200.0, pat=150.0, eps=4.0,
                operating_cash_flow=180.0, free_cash_flow=100.0, total_assets=1800.0, total_liabilities=750.0,
                total_debt=380.0, cash=90.0, equity=900.0, shares_outstanding=100.0, dividend_yield=0.01,
                source="yfinance", source_timestamp=datetime(2024, 3, 31, 0, 0, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/SCOREFUN/fundamentals")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()

    # New raw fields flow through untouched.
    assert body["raw"]["interest_expense"] == pytest.approx(25.0)
    assert body["raw"]["current_assets"] == pytest.approx(600.0)
    assert body["raw"]["current_liabilities"] == pytest.approx(300.0)

    # New derived metrics, hand-computed from the raw fields above.
    assert body["derived"]["roa"] == pytest.approx(200.0 / 2000.0, abs=1e-6)
    assert body["derived"]["net_profit_margin"] == pytest.approx(200.0 / 1140.0, abs=1e-6)
    assert body["derived"]["asset_turnover"] == pytest.approx(1140.0 / 2000.0, abs=1e-6)
    assert body["derived"]["financial_leverage"] == pytest.approx(2000.0 / 1000.0, abs=1e-6)
    assert body["derived"]["interest_coverage"] == pytest.approx(250.0 / 25.0, abs=1e-6)
    assert body["derived"]["current_ratio"] == pytest.approx(600.0 / 300.0, abs=1e-6)

    # Hand-computed Fundamental Score (SCORING.md):
    # growth: revenue +8 (5-15% band), pat +15 (>=15%), eps +10 (half-weight, >=15%) -> 50+33=83
    # profitability: roe(0.20) +10, roce(0.17857) +10, roa(0.10) +10, net_margin(0.1754) +10 -> 90
    # leverage: de(0.4) +5, nd/ebitda(1.0) +5, interest_coverage(10.0) +15, current_ratio(2.0) +10 -> 85
    # efficiency: asset_turnover(0.57) +5 -> 55
    sub = body["fundamental_score"]["sub_scores"]
    assert sub["growth"] == pytest.approx(83.0, abs=1e-6)
    assert sub["profitability"] == pytest.approx(90.0, abs=1e-6)
    assert sub["leverage"] == pytest.approx(85.0, abs=1e-6)
    assert sub["efficiency"] == pytest.approx(55.0, abs=1e-6)

    expected_overall = 83.0 * 0.35 + 90.0 * 0.35 + 85.0 * 0.20 + 55.0 * 0.10
    assert body["fundamental_score"]["overall"] == pytest.approx(expected_overall, abs=1e-6)
    assert body["fundamental_score"]["band"] is not None
    assert body["fundamental_score"]["methodology_version"] == "fundamental_score_v1"


@pytest.mark.asyncio
async def test_fundamentals_partial_leverage_coverage_degrades_gracefully(db_session):
    """interest_expense/current_assets/current_liabilities all missing (a thinly-covered
    instrument where neither yfinance nor tradingview_ta had any of the three - current
    ratio alone is structurally missing for banks, see DATA_SOURCES.md; this test exercises
    the more general "none of the three available" degradation path) - leverage sub-score
    still computes from Debt/Equity + Net Debt/EBITDA alone, never erroring, never
    fabricating the other two."""
    instrument = Instrument(symbol="BANKISH", exchange="NSE", company_name="Bankish Ltd")
    db_session.add(instrument)
    await db_session.flush()

    db_session.add(
        OHLCVDaily(
            id=uuid.uuid4(), instrument_id=instrument.id, trading_date=date(2025, 6, 30),
            open=100.0, high=101.0, low=99.0, close=100.0, adjusted_close=100.0, volume=1_000_000,
            source="fake", source_timestamp=datetime(2025, 6, 30, 18, 0, tzinfo=UTC),
        )
    )
    db_session.add(
        FundamentalSnapshot(
            id=uuid.uuid4(), instrument_id=instrument.id, period_end=date(2025, 3, 31), period_type="FY",
            revenue=1140.0, ebitda=300.0, ebit=250.0, pat=200.0, eps=5.0,
            operating_cash_flow=220.0, free_cash_flow=150.0, total_assets=2000.0, total_liabilities=800.0,
            total_debt=400.0, cash=100.0, equity=1000.0, shares_outstanding=100.0, dividend_yield=0.01,
            # interest_expense/current_assets/current_liabilities deliberately omitted (NULL).
            source="yfinance", source_timestamp=datetime(2025, 3, 31, 0, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/BANKISH/fundamentals")
    finally:
        _clear_override()

    assert response.status_code == 200
    body = response.json()
    assert body["raw"]["interest_expense"] is None
    assert body["derived"]["interest_coverage"] is None
    assert body["derived"]["current_ratio"] is None
    # Leverage sub-score still computes from debt_to_equity(0.4)=+5 and net_debt_to_ebitda(1.0)=+5 -> 60.
    assert body["fundamental_score"]["sub_scores"]["leverage"] == pytest.approx(60.0, abs=1e-6)
    assert body["fundamental_score"]["overall"] is not None


@pytest.mark.asyncio
async def test_fundamentals_unknown_symbol_is_404(db_session):
    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/stocks/NOPE/fundamentals")
    finally:
        _clear_override()
    assert response.status_code == 404
