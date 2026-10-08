"""Integration tests for packages/scoring/engine.py (SPEC.md sections 17-22, 86).

DB-backed (uses the shared `db_session` fixture, real Postgres per
tests/conftest.py's rationale) - seeds OHLCV, fundamentals, sector peers,
and a market regime row directly, then runs the full
`compute_research_score` pipeline end to end.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from packages.common.models import Instrument
from packages.fundamentals.models import FundamentalSnapshot
from packages.market_data.models import OHLCVDaily
from packages.regime.classifier import RULE_VERSION
from packages.regime.models import MarketRegime, MarketRegimeLabel
from packages.scoring.bands import score_band
from packages.scoring.constants import METHODOLOGY_VERSION
from packages.scoring.engine import compute_research_score
from packages.scoring.models import EvidenceItem


def _trading_dates(n: int, end: date) -> list[date]:
    dates: list[date] = []
    current = end
    while len(dates) < n:
        if current.weekday() < 5:
            dates.append(current)
        current -= timedelta(days=1)
    return list(reversed(dates))


async def _seed_bars(db_session, instrument: Instrument, closes: list[float], end_date: date) -> None:
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
                source_timestamp=datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC),
            )
        )
    await db_session.commit()


async def _seed_fundamentals(db_session, instrument: Instrument, *, period_end: date, age_days_ok: bool = True) -> None:
    db_session.add_all(
        [
            FundamentalSnapshot(
                id=uuid.uuid4(),
                instrument_id=instrument.id,
                period_end=period_end,
                period_type="FY",
                revenue=1_200_000.0,
                ebitda=300_000.0,
                ebit=250_000.0,
                pat=180_000.0,
                eps=18.0,
                operating_cash_flow=220_000.0,
                free_cash_flow=150_000.0,
                total_assets=2_000_000.0,
                total_liabilities=800_000.0,
                total_debt=400_000.0,
                cash=200_000.0,
                equity=1_200_000.0,
                shares_outstanding=10_000.0,
                dividend_yield=0.01,
                source="yfinance",
                source_timestamp=datetime.combine(period_end, datetime.min.time(), tzinfo=UTC),
            ),
            FundamentalSnapshot(
                id=uuid.uuid4(),
                instrument_id=instrument.id,
                period_end=period_end.replace(year=period_end.year - 1),
                period_type="FY",
                revenue=1_000_000.0,
                ebitda=250_000.0,
                ebit=200_000.0,
                pat=140_000.0,
                eps=14.0,
                operating_cash_flow=180_000.0,
                free_cash_flow=100_000.0,
                total_assets=1_800_000.0,
                total_liabilities=750_000.0,
                total_debt=380_000.0,
                cash=150_000.0,
                equity=1_050_000.0,
                shares_outstanding=10_000.0,
                dividend_yield=0.01,
                source="yfinance",
                source_timestamp=datetime.combine(period_end, datetime.min.time(), tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()


async def _seed_regime(db_session, as_of: date, label: MarketRegimeLabel = MarketRegimeLabel.bullish_trend) -> None:
    db_session.add(
        MarketRegime(
            id=uuid.uuid4(),
            date=as_of,
            regime=label,
            nifty_close=25000.0,
            nifty_vs_200dma_pct=5.0,
            breadth_above_50dma_pct=70.0,
            breadth_above_200dma_pct=65.0,
            rolling_volatility_pct=14.0,
            rule_version=RULE_VERSION,
        )
    )
    await db_session.commit()


@pytest.fixture
def today() -> date:
    return date(2025, 6, 30)


@pytest.mark.asyncio
async def test_full_score_computation_persists_real_evidence(db_session, today):
    instrument = Instrument(symbol="FULLCO", exchange="NSE", company_name="Full Co Ltd", sector="IT")
    db_session.add(instrument)
    await db_session.flush()

    closes = [100.0 + i * 0.25 + (1.5 if i % 7 == 0 else -0.5) for i in range(300)]
    await _seed_bars(db_session, instrument, closes, today)
    await _seed_fundamentals(db_session, instrument, period_end=date(2025, 3, 31))
    await _seed_regime(db_session, today - timedelta(days=1))

    result = await compute_research_score(db_session, instrument)

    assert result.score is not None
    assert 0.0 <= result.score <= 100.0
    assert 0.0 <= result.confidence <= 100.0
    assert result.band == score_band(result.score)
    assert result.methodology_version == METHODOLOGY_VERSION

    # News is always unavailable in this version.
    news = next(c for c in result.components if c.name == "event_news_context")
    assert news.available is False
    assert news.score is None

    # Every evidence_id referenced anywhere in the response actually
    # exists in evidence_items (SPEC.md section 25's validation
    # principle, applied without an LLM in the loop).
    referenced_ids = {eid for c in result.components for eid in c.evidence}
    referenced_ids |= {e.evidence_id for e in result.bull_case}
    referenced_ids |= {e.evidence_id for e in result.bear_case}
    assert referenced_ids, "expected at least some evidence to have been generated"

    stmt = select(EvidenceItem.id).where(EvidenceItem.id.in_([uuid.UUID(i) for i in referenced_ids]))
    found_ids = {str(row) for row in (await db_session.execute(stmt)).scalars().all()}
    assert referenced_ids == found_ids


@pytest.mark.asyncio
async def test_missing_fundamentals_reduces_confidence_and_renormalizes(db_session, today):
    instrument = Instrument(symbol="THINCO", exchange="NSE", company_name="Thin Co Ltd", sector="IT")
    db_session.add(instrument)
    await db_session.flush()

    closes = [100.0 + i * 0.1 for i in range(300)]
    await _seed_bars(db_session, instrument, closes, today)
    await _seed_regime(db_session, today - timedelta(days=1))
    # No fundamentals seeded at all - thinly-covered-stock scenario.

    result = await compute_research_score(db_session, instrument)

    fundamentals = next(c for c in result.components if c.name == "fundamentals")
    valuation = next(c for c in result.components if c.name == "valuation")
    assert fundamentals.available is False
    assert fundamentals.reason == "no_fundamental_data"
    assert valuation.available is False
    assert fundamentals.weight_used == 0.0
    assert valuation.weight_used == 0.0

    # Score is still produced from the remaining available components.
    assert result.score is not None


@pytest.mark.asyncio
async def test_stale_fundamentals_lower_confidence_than_fresh(db_session, today):
    fresh_instrument = Instrument(symbol="FRESHCO", exchange="NSE", company_name="Fresh Co Ltd", sector="IT")
    stale_instrument = Instrument(symbol="STALECO", exchange="NSE", company_name="Stale Co Ltd", sector="IT")
    db_session.add_all([fresh_instrument, stale_instrument])
    await db_session.flush()

    closes = [100.0 + i * 0.1 for i in range(300)]
    await _seed_bars(db_session, fresh_instrument, closes, today)
    await _seed_bars(db_session, stale_instrument, closes, today)
    await _seed_regime(db_session, today - timedelta(days=1))

    await _seed_fundamentals(db_session, fresh_instrument, period_end=date(2025, 6, 1))  # ~29 days old
    await _seed_fundamentals(db_session, stale_instrument, period_end=date(2022, 1, 1))  # years old

    fresh_result = await compute_research_score(db_session, fresh_instrument)
    stale_result = await compute_research_score(db_session, stale_instrument)

    fresh_fundamentals = next(c for c in fresh_result.components if c.name == "fundamentals")
    stale_fundamentals = next(c for c in stale_result.components if c.name == "fundamentals")
    assert fresh_fundamentals.available and stale_fundamentals.available

    assert stale_result.confidence < fresh_result.confidence
