"""Valuation-percentile caching correctness (SPEC.md section 81 rule 24).

Proves the performance fix in packages/scoring/components.py (universe-
wide valuation scan computed once per batch / short-TTL-cached for
on-demand calls, instead of rescanned on every single instrument) does
not change the *methodology* or its output: the precomputed-universe
path must return bit-identical percentiles to a naive full rescan on a
small synthetic universe, DB-backed, no network.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from packages.common.models import Instrument
from packages.fundamentals.models import FundamentalSnapshot
from packages.market_data.models import OHLCVDaily
from packages.scoring import components as scoring_components
from packages.scoring.components import (
    _universe_valuation_values,
    compute_universe_valuation_values,
    get_cached_universe_valuation_values,
    score_valuation,
)
from packages.scoring.constants import METHODOLOGY_VERSION
from packages.scoring.evidence import EvidenceBuilder

TODAY = date(2025, 6, 30)
PERIOD_END = date(2025, 3, 31)


@pytest.fixture(autouse=True)
def _reset_valuation_cache():
    """Isolate each test from the module-level TTL cache's process-global state.

    Without this, a fixed historical `as_of` (used throughout this file
    for determinism) could spuriously hit a cache entry populated by a
    different test's (dropped-and-recreated) DB fixture.
    """
    scoring_components._valuation_cache["computed_at"] = None
    scoring_components._valuation_cache["values"] = None
    yield
    scoring_components._valuation_cache["computed_at"] = None
    scoring_components._valuation_cache["values"] = None


async def _make_instrument_with_valuation(
    db_session, symbol: str, *, close: float, eps: float, equity: float, shares: float, ebitda: float
) -> Instrument:
    instrument = Instrument(symbol=symbol, exchange="NSE", company_name=f"{symbol} Ltd", sector="IT")
    db_session.add(instrument)
    await db_session.flush()

    db_session.add(
        OHLCVDaily(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            trading_date=TODAY,
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            adjusted_close=close,
            volume=1_000_000,
            source="fake",
            source_timestamp=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
        )
    )
    db_session.add(
        FundamentalSnapshot(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            period_end=PERIOD_END,
            period_type="FY",
            revenue=1_000_000.0,
            ebitda=ebitda,
            ebit=ebitda * 0.8,
            pat=eps * shares,
            eps=eps,
            operating_cash_flow=200_000.0,
            free_cash_flow=150_000.0,
            total_assets=2_000_000.0,
            total_liabilities=800_000.0,
            total_debt=400_000.0,
            cash=200_000.0,
            equity=equity,
            shares_outstanding=shares,
            dividend_yield=0.01,
            source="yfinance",
            source_timestamp=datetime.combine(PERIOD_END, datetime.min.time(), tzinfo=UTC),
        )
    )
    await db_session.commit()
    return instrument


@pytest.fixture
async def synthetic_universe(db_session) -> list[Instrument]:
    """6 instruments with distinct P/E, P/B, EV/EBITDA (>= MIN_VALUATION_PEER_POPULATION)."""
    specs = [
        ("PEERA", 100.0, 10.0, 500_000.0, 10_000.0, 200_000.0),
        ("PEERB", 150.0, 8.0, 600_000.0, 12_000.0, 180_000.0),
        ("PEERC", 200.0, 15.0, 900_000.0, 15_000.0, 300_000.0),
        ("PEERD", 80.0, 5.0, 300_000.0, 8_000.0, 120_000.0),
        ("PEERE", 300.0, 20.0, 1_200_000.0, 20_000.0, 400_000.0),
        ("TARGET", 120.0, 12.0, 700_000.0, 11_000.0, 250_000.0),
    ]
    instruments = []
    for symbol, close, eps, equity, shares, ebitda in specs:
        instruments.append(
            await _make_instrument_with_valuation(
                db_session, symbol, close=close, eps=eps, equity=equity, shares=shares, ebitda=ebitda
            )
        )
    return instruments


@pytest.mark.asyncio
async def test_precomputed_universe_matches_naive_full_rescan(db_session, synthetic_universe):
    as_of = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC)

    naive_universe = await _universe_valuation_values(db_session, as_of)
    precomputed_universe = await compute_universe_valuation_values(db_session, as_of)

    assert naive_universe == precomputed_universe
    assert len(naive_universe["pe"]) == 6


@pytest.mark.asyncio
async def test_score_valuation_identical_with_and_without_precomputed_universe(db_session, synthetic_universe):
    target = next(i for i in synthetic_universe if i.symbol == "TARGET")
    as_of = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC)

    from packages.market_data.history import load_ohlcv_dataframe

    full_df = await load_ohlcv_dataframe(db_session, target.id)
    latest_snapshot = (
        await db_session.execute(select(FundamentalSnapshot).where(FundamentalSnapshot.instrument_id == target.id))
    ).scalar_one()

    naive_universe = await _universe_valuation_values(db_session, as_of)

    builder_naive = EvidenceBuilder(target.id, METHODOLOGY_VERSION)
    naive_result, _ = await score_valuation(db_session, target, latest_snapshot, full_df, builder_naive, as_of)

    builder_precomputed = EvidenceBuilder(target.id, METHODOLOGY_VERSION)
    precomputed_result, _ = await score_valuation(
        db_session,
        target,
        latest_snapshot,
        full_df,
        builder_precomputed,
        as_of,
        precomputed_universe_valuation=naive_universe,
    )

    assert naive_result.available == precomputed_result.available
    assert naive_result.score == pytest.approx(precomputed_result.score)
    assert naive_result.freshness == precomputed_result.freshness


@pytest.mark.asyncio
async def test_cached_universe_helper_returns_same_values_within_ttl(db_session, synthetic_universe):
    as_of = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC)

    first = await get_cached_universe_valuation_values(db_session, as_of)
    # A second call shortly after (well within the TTL) must return the
    # exact same cached dict without re-querying - verified indirectly by
    # equality (and directly: it's the same object reference).
    second = await get_cached_universe_valuation_values(db_session, as_of)

    assert first == second
    assert first is second
