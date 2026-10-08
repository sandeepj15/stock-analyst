"""Single-source-of-truth guarantee for the Fundamental Score (SCORING.md "Fundamental Score").

Proves `GET /stocks/{symbol}/score`'s "fundamentals" component score and
`GET /stocks/{symbol}/fundamentals`'s `fundamental_score.overall` are the
*exact same number* for the same instrument/snapshot - both ultimately
call `packages.scoring.signals.compute_fundamental_score` with the same
derived inputs (`packages/scoring/components.py::score_fundamentals` and
`apps/api/routes/fundamentals.py::get_fundamentals` respectively), so
they can never silently diverge.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

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
                volume=1_000_000, source="fake",
                source_timestamp=datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC),
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_score_fundamentals_component_matches_standalone_fundamental_score(db_session):
    today = date(2025, 6, 30)
    instrument = Instrument(symbol="TRUTHCO", exchange="NSE", company_name="Single Source Ltd", sector="IT")
    db_session.add(instrument)
    await db_session.flush()

    closes = [100.0 + i * 0.2 + (1.0 if i % 9 == 0 else -0.3) for i in range(300)]
    await _seed_bars(db_session, instrument, closes, today)

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
            score_response = await client.get("/api/v1/stocks/TRUTHCO/score")
            fundamentals_response = await client.get("/api/v1/stocks/TRUTHCO/fundamentals")
    finally:
        _clear_override()

    assert score_response.status_code == 200
    assert fundamentals_response.status_code == 200

    score_body = score_response.json()
    fundamentals_body = fundamentals_response.json()

    fundamentals_component = next(c for c in score_body["components"] if c["name"] == "fundamentals")
    assert fundamentals_component["available"] is True

    standalone_overall = fundamentals_body["fundamental_score"]["overall"]
    assert standalone_overall is not None
    # The single-source-of-truth guarantee: identical number, not just
    # "close" - both call the exact same `compute_fundamental_score`.
    assert fundamentals_component["score"] == pytest.approx(standalone_overall, abs=1e-9)


@pytest.mark.asyncio
async def test_matches_even_when_leverage_subscore_is_partially_unavailable(db_session):
    """Same guarantee, but for an instrument where interest_expense/current_assets/
    current_liabilities are NULL (current_assets/current_liabilities in particular are
    structurally unavailable for banks, see DATA_SOURCES.md) - the degraded leverage
    sub-score must still agree between the two endpoints."""
    today = date(2025, 6, 30)
    instrument = Instrument(symbol="TRUTHBANK", exchange="NSE", company_name="Single Source Bank Ltd", sector="Financials")
    db_session.add(instrument)
    await db_session.flush()

    closes = [100.0 + i * 0.1 for i in range(300)]
    await _seed_bars(db_session, instrument, closes, today)

    db_session.add(
        FundamentalSnapshot(
            id=uuid.uuid4(), instrument_id=instrument.id, period_end=date(2025, 3, 31), period_type="FY",
            revenue=1140.0, ebitda=300.0, ebit=250.0, pat=200.0, eps=5.0,
            operating_cash_flow=220.0, free_cash_flow=150.0, total_assets=2000.0, total_liabilities=800.0,
            total_debt=400.0, cash=100.0, equity=1000.0, shares_outstanding=100.0, dividend_yield=0.01,
            source="yfinance", source_timestamp=datetime(2025, 3, 31, 0, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    _override_db(db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            score_response = await client.get("/api/v1/stocks/TRUTHBANK/score")
            fundamentals_response = await client.get("/api/v1/stocks/TRUTHBANK/fundamentals")
    finally:
        _clear_override()

    score_body = score_response.json()
    fundamentals_body = fundamentals_response.json()
    fundamentals_component = next(c for c in score_body["components"] if c["name"] == "fundamentals")

    assert fundamentals_body["derived"]["interest_coverage"] is None
    assert fundamentals_body["fundamental_score"]["sub_scores"]["leverage"] is not None  # de + nd/ebitda still there
    assert fundamentals_component["score"] == pytest.approx(
        fundamentals_body["fundamental_score"]["overall"], abs=1e-9
    )
