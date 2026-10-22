"""Research Score + Evidence endpoints (SPEC.md sections 17-22, 46, 48/49, Phase 3).

`GET /api/v1/stocks/{symbol}/score` - full Research Strength v1
breakdown (SPEC.md section 20's response contract).
`GET /api/v1/stocks/{symbol}/evidence` - every persisted evidence item
for that instrument, newest first, capped at a reasonable count.

No LLM calls anywhere in this module (SPEC.md section 81 rule 3).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import resolve_instrument_or_404
from packages.common import cache
from packages.common.db import get_db_session
from packages.scoring.bands import score_band
from packages.scoring.engine import (
    SCORE_CACHE_TTL_SECONDS,
    BullBearEntryOut,
    ComponentOut,
    compute_research_score,
    score_cache_key,
    to_score_response_payload,
)
from packages.scoring.models import EvidenceItem, ResearchScore

router = APIRouter(prefix="/api/v1/stocks", tags=["scoring"])

EVIDENCE_LIST_CAP = 200


class ScoreResponse(BaseModel):
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
    # Never itself cached (always set per-response) - see packages/scoring/engine.py's
    # "Redis caching" comment. `as_of_date`/`computed_at` above always reflect
    # when the underlying score was actually computed, cache hit or not -
    # a cache hit never means "fresher" or "staler" data, only "faster".
    cache_hit: bool


class EvidenceItemOut(BaseModel):
    id: str
    evidence_type: str
    metric_name: str
    value_numeric: float | None
    value_text: str | None
    unit: str | None
    observed_at: str
    published_at: str | None
    source_name: str
    source_reference: str | None
    source_timestamp: str
    methodology_version: str
    confidence: float | None
    created_at: str


class EvidenceListResponse(BaseModel):
    symbol: str
    exchange: str
    count: int
    capped_at: int
    items: list[EvidenceItemOut]


@router.get("/{symbol}/score", response_model=ScoreResponse)
async def get_score(
    symbol: str,
    exchange: str = Query(default="NSE"),
    session: AsyncSession = Depends(get_db_session),
) -> ScoreResponse:
    """Research Strength v1 score for `symbol` - cache-first (SPEC.md section 59).

    Checks Redis first (`score:v1:{instrument_id}`, populated by
    `apps/worker/jobs.py::compute_all_scores_job`'s write-through and/or
    a previous cache miss here). On a hit, returns immediately without
    touching the DB or recomputing anything. On a miss, falls back to
    the original live-compute-and-persist path (SPEC.md section 46's
    full evidence audit trail), populates the cache, then serves it.

    404 if the symbol is unknown; 422 if the instrument has zero OHLCV
    history (same pattern as `/technicals` and `/relative-strength`).
    """
    instrument = await resolve_instrument_or_404(session, symbol, exchange)
    cache_key = score_cache_key(instrument.id)

    cached = await cache.get_json(cache_key)
    if cached is not None:
        return ScoreResponse(**cached, cache_hit=True)

    # Fast path: check if we have a persisted score in the database first
    stmt = (
        select(ResearchScore)
        .where(ResearchScore.instrument_id == instrument.id)
        .order_by(ResearchScore.computed_at.desc())
        .limit(1)
    )
    latest_row = (await session.execute(stmt)).scalar_one_or_none()
    if latest_row is not None:
        payload = {
            "instrument_id": str(latest_row.instrument_id),
            "symbol": instrument.symbol,
            "exchange": instrument.exchange,
            "as_of_date": latest_row.computed_at.date().isoformat(),
            "computed_at": latest_row.computed_at.isoformat(),
            "score": latest_row.score,
            "confidence": latest_row.confidence,
            "band": score_band(latest_row.score),
            "methodology_version": latest_row.methodology_version,
            "components": latest_row.components,
            "bull_case": latest_row.bull_case,
            "bear_case": latest_row.bear_case,
        }
        await cache.set_json(cache_key, payload, SCORE_CACHE_TTL_SECONDS)
        return ScoreResponse(**payload, cache_hit=False)

    try:
        result = await compute_research_score(session, instrument)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = to_score_response_payload(result)
    await cache.set_json(cache_key, payload, SCORE_CACHE_TTL_SECONDS)
    return ScoreResponse(**payload, cache_hit=False)


@router.get("/{symbol}/evidence", response_model=EvidenceListResponse)
async def get_evidence(
    symbol: str,
    exchange: str = Query(default="NSE"),
    limit: int = Query(default=100, le=EVIDENCE_LIST_CAP),
    session: AsyncSession = Depends(get_db_session),
) -> EvidenceListResponse:
    """Every persisted evidence item for this instrument, newest first.

    This is the full audit trail behind every score ever computed for
    the instrument (SPEC.md section 46) - not just the latest score's
    evidence. Capped at `EVIDENCE_LIST_CAP` regardless of the requested
    `limit`.
    """
    instrument = await resolve_instrument_or_404(session, symbol, exchange)

    capped_limit = min(limit, EVIDENCE_LIST_CAP)
    cache_key = f"stock_evidence:v2:{instrument.id}:{capped_limit}"
    cached = await cache.get_json(cache_key)
    if cached is not None:
        try:
            return EvidenceListResponse.model_validate(cached)
        except Exception:
            pass

    stmt = (
        select(EvidenceItem)
        .where(EvidenceItem.instrument_id == instrument.id)
        .order_by(EvidenceItem.created_at.desc())
        .limit(capped_limit)
    )
    rows = (await session.execute(stmt)).scalars().all()

    items = [
        EvidenceItemOut(
            id=str(row.id),
            evidence_type=row.evidence_type,
            metric_name=row.metric_name,
            value_numeric=float(row.value_numeric) if row.value_numeric is not None else None,
            value_text=row.value_text,
            unit=row.unit,
            observed_at=row.observed_at.isoformat(),
            published_at=row.published_at.isoformat() if row.published_at else None,
            source_name=row.source_name,
            source_reference=row.source_reference,
            source_timestamp=row.source_timestamp.isoformat(),
            methodology_version=row.methodology_version,
            confidence=float(row.confidence) if row.confidence is not None else None,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]

    resp = EvidenceListResponse(
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        count=len(items),
        capped_at=EVIDENCE_LIST_CAP,
        items=items,
    )
    await cache.set_json(cache_key, resp.model_dump(mode="json"), ttl_seconds=600)
    return resp
