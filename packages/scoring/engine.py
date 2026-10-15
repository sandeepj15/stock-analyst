"""Research Strength v1 engine (SPEC.md sections 17-22, 86).

`compute_research_score` is the single entry point: it loads an
instrument's current OHLCV/fundamentals/regime/relative-strength data,
scores all 8 SPEC.md section 17 components, persists every underlying
`EvidenceItem` plus one `research_scores` row, and returns a fully
explainable result object matching SPEC.md section 20's response
contract. Every score is reproducible from stored data (nothing here is
randomized or depends on wall-clock state beyond "latest available
data") and is computed fresh on every call - there is no caching layer,
consistent with how `/technicals` and `/relative-strength` already work
in this codebase.

No LLM calls anywhere in this module (SPEC.md section 81 rule 3).
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime, time

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.models import Instrument
from packages.indicators import compute_indicator_snapshot
from packages.market_data.history import load_ohlcv_dataframe
from packages.market_data.relative_strength import UniverseSectorRS
from packages.scoring.aggregate import aggregate_components
from packages.scoring.bands import score_band
from packages.scoring.bull_bear import build_bull_bear_case
from packages.scoring.components import (
    SignalPairs,
    UniverseValuation,
    score_fundamentals,
    score_market_regime,
    score_momentum,
    score_risk_quality,
    score_sector_relative_strength,
    score_technical_structure,
    score_valuation,
)
from packages.scoring.constants import METHODOLOGY_VERSION
from packages.scoring.evidence import EvidenceBuilder
from packages.scoring.models import ResearchScore as ResearchScoreRow

# Order matches SPEC.md section 17's weight table, used consistently in
# the API response's `components` list.
COMPONENT_ORDER = (
    "technical_structure",
    "momentum",
    "fundamentals",
    "valuation",
    "sector_relative_strength",
    "market_regime",
    "risk_quality",
)


class ComponentOut(BaseModel):
    name: str
    weight: float
    weight_used: float
    score: float | None
    contribution: float
    available: bool
    reason: str | None
    evidence: list[str]


class BullBearEntryOut(BaseModel):
    evidence_id: str
    metric_name: str
    interpretation: str
    magnitude: float
    strength: str


class ResearchScoreResult(BaseModel):
    instrument_id: str
    symbol: str
    exchange: str
    as_of_date: str
    computed_at: str
    score: float | None
    confidence: float
    band: str | None
    methodology_version: str
    components: list[ComponentOut]
    bull_case: list[BullBearEntryOut]
    bear_case: list[BullBearEntryOut]


# --- Redis caching (SPEC.md section 59; see packages/common/cache.py) ---
#
# `/stocks/{symbol}/score` used to recompute (and re-persist evidence
# for) a fresh score on *every* call - a documented limitation (see
# SCORING.md section 9's former "No caching layer" note). Fixed here:
# the on-demand route and `apps/worker/jobs.py::compute_all_scores_job`
# both read/write the exact same cache key + JSON shape via the two
# helpers below, so a batch run leaves the cache warm for every
# instrument immediately, and an on-demand cache hit skips the DB
# read/live-compute/evidence-persist path entirely.
#
# TTL (30 minutes): a safety net, not the primary population mechanism.
# `compute_all_scores_job` is expected to run at least that often in
# production and write-through on every instrument it scores; the TTL
# just bounds how stale a cache entry can get if the batch job is ever
# delayed, without serving indefinitely-stale data on a quiet system.
SCORE_CACHE_KEY_PREFIX = "score:v1"
SCORE_CACHE_TTL_SECONDS = 1800


def score_cache_key(instrument_id: object) -> str:
    return f"{SCORE_CACHE_KEY_PREFIX}:{instrument_id}"


def to_score_response_payload(result: ResearchScoreResult) -> dict:
    """JSON-serializable dict matching `apps/api/routes/scoring.py::ScoreResponse`
    (minus the per-request `cache_hit` flag, which is never itself cached -
    see that route for why). Shared by the on-demand route and the batch
    job's write-through so both populate the identical cache shape.
    """
    return {
        "instrument_id": result.instrument_id,
        "symbol": result.symbol,
        "exchange": result.exchange,
        "as_of_date": result.as_of_date,
        "computed_at": result.computed_at,
        "score": result.score,
        "confidence": result.confidence,
        "band": result.band,
        "methodology_version": result.methodology_version,
        "components": [c.model_dump() for c in result.components],
        "bull_case": [b.model_dump() for b in result.bull_case],
        "bear_case": [b.model_dump() for b in result.bear_case],
    }


async def compute_research_score(
    session: AsyncSession,
    instrument: Instrument,
    precomputed_universe_valuation: UniverseValuation | None = None,
    precomputed_universe_sector_rs: UniverseSectorRS | None = None,
    precomputed_regime_row: Any | None = None,
) -> ResearchScoreResult:
    """Compute and persist one instrument's Research Strength v1 score.

    `precomputed_universe_valuation`: optional performance escape hatch
    for batch callers (`apps/worker/jobs.py::compute_all_scores_job`)
    that already computed the universe-wide valuation peer population
    once for the whole run - see `packages/scoring/components.py` for
    why this exists and why it changes nothing about the on-demand
    `/score` endpoint's behavior (that endpoint simply omits this
    argument and gets the same methodology via a short-TTL cache
    instead of a precomputed value).

    `precomputed_universe_sector_rs`: optional precomputed sector returns
    for batch callers, eliminating O(N_sector^2) nested OHLCV peer queries.

    `precomputed_regime_row`: optional precomputed regime row for batch callers,
    avoiding redundant database queries across 1,510 stocks.
    """
    full_df = await load_ohlcv_dataframe(session, instrument.id)
    if full_df.empty:
        raise ValueError(
            f"Instrument {instrument.exchange}:{instrument.symbol} has no OHLCV data; cannot compute a research score."
        )

    snapshot = compute_indicator_snapshot(full_df)
    now = datetime.now(UTC)
    bar_timestamp = datetime.combine(snapshot.as_of_date, time.min, tzinfo=UTC)

    evidence_builder = EvidenceBuilder(instrument.id, METHODOLOGY_VERSION)

    technical_result, technical_pairs = score_technical_structure(snapshot, evidence_builder, now, bar_timestamp)
    momentum_result, momentum_pairs = score_momentum(snapshot, evidence_builder, now, bar_timestamp)
    risk_result, risk_pairs = score_risk_quality(full_df, snapshot, evidence_builder, now, bar_timestamp)
    fundamentals_result, fundamentals_pairs, latest_fundamental = await score_fundamentals(
        session, instrument, evidence_builder, now
    )
    valuation_result, valuation_pairs = await score_valuation(
        session,
        instrument,
        latest_fundamental,
        full_df,
        evidence_builder,
        now,
        precomputed_universe_valuation=precomputed_universe_valuation,
    )
    sector_result, sector_pairs = await score_sector_relative_strength(
        session,
        instrument,
        evidence_builder,
        now,
        stock_df=full_df,
        precomputed_universe_sector_rs=precomputed_universe_sector_rs,
    )
    regime_result, regime_pairs = await score_market_regime(
        session,
        evidence_builder,
        now,
        precomputed_regime_row=precomputed_regime_row,
    )

    results_by_name = {
        "technical_structure": technical_result,
        "momentum": momentum_result,
        "fundamentals": fundamentals_result,
        "valuation": valuation_result,
        "sector_relative_strength": sector_result,
        "market_regime": regime_result,
        "risk_quality": risk_result,
    }
    components = [results_by_name[name] for name in COMPONENT_ORDER]

    all_pairs: SignalPairs = [
        *technical_pairs,
        *momentum_pairs,
        *fundamentals_pairs,
        *valuation_pairs,
        *sector_pairs,
        *regime_pairs,
        *risk_pairs,
    ]

    aggregate = aggregate_components(components)
    bull_entries, bear_entries = build_bull_bear_case(all_pairs)
    band = score_band(aggregate.score) if aggregate.score is not None else None

    components_payload = [
        {
            "name": c.name,
            "weight": c.weight,
            "weight_used": c.weight_used,
            "score": c.score,
            "contribution": c.contribution,
            "available": c.available,
            "reason": c.reason,
            "evidence": list(c.evidence),
        }
        for c in aggregate.components
    ]
    bull_payload = [asdict(e) for e in bull_entries]
    bear_payload = [asdict(e) for e in bear_entries]

    if evidence_builder.items:
        session.add_all(evidence_builder.items)

    score_row = ResearchScoreRow(
        id=uuid.uuid4(),
        instrument_id=instrument.id,
        score=aggregate.score,
        confidence=aggregate.confidence,
        methodology_version=METHODOLOGY_VERSION,
        components=components_payload,
        bull_case=bull_payload,
        bear_case=bear_payload,
    )
    session.add(score_row)
    await session.commit()

    return ResearchScoreResult(
        instrument_id=str(instrument.id),
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        as_of_date=snapshot.as_of_date.isoformat(),
        computed_at=now.isoformat(),
        score=aggregate.score,
        confidence=aggregate.confidence,
        band=band,
        methodology_version=METHODOLOGY_VERSION,
        components=[ComponentOut.model_validate(c) for c in components_payload],
        bull_case=[BullBearEntryOut.model_validate(b) for b in bull_payload],
        bear_case=[BullBearEntryOut.model_validate(b) for b in bear_payload],
    )
