"""DB-backed orchestration for the Stage 2 Momentum Scanner.

Wires together `packages/indicators` (SMA50/150/200, 52-week high/low),
`packages/momentum/rs_rank.py` (universe-wide RS Rank), and
`packages/momentum/scanner.py` (the pure 8-condition evaluator), then
persists one `momentum_scans` row per instrument - the same orchestration
shape as `packages/scoring/engine.py::compute_research_score`.

`compute_momentum_scan` is the single entry point used by both the
on-demand `GET /stocks/{symbol}/momentum-scan` route and the batch
`apps/worker/jobs.py::compute_all_momentum_scans_job`.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.models import Instrument
from packages.indicators.snapshot import compute_indicator_series
from packages.market_data.history import load_ohlcv_dataframe
from packages.momentum.models import MomentumScan
from packages.momentum.rs_rank import (
    RS_RANK_UNIVERSE_LABEL,
    compute_raw_score,
    percentile_rank_universe,
)
from packages.momentum.scanner import (
    DEFAULT_SMA200_TREND_LOOKBACK_DAYS,
    METHODOLOGY_VERSION,
    MomentumScanResult,
    evaluate_stage2_momentum,
)

RawScoreUniverse = dict[uuid.UUID, float]  # instrument_id -> raw_score


class ConditionOut(BaseModel):
    name: str
    passed: bool
    value: float
    threshold: float
    description: str


class MomentumScanResponse(BaseModel):
    """JSON-serializable shape returned by the on-demand route, persisted
    by the batch job, and what gets cached in Redis (packages/common/cache.py)
    under `momentum_scan:v1:{instrument_id}:{sma200_trend_lookback_days}`."""

    instrument_id: str
    symbol: str
    exchange: str
    scan_date: str | None
    evaluable: bool
    passed: bool | None
    conditions: list[ConditionOut]
    distance_from_52w_high_pct: float | None
    rs_rank: float | None
    rs_rank_universe: str
    sma200_trend_lookback_days: int
    methodology_version: str
    computed_at: str
    reason: str | None
    is_vcp_setup: bool | None = None
    vcp_reason: str | None = None
    # Never itself cached (always set per-response, defaults to False for
    # any freshly-computed result) - see the "Redis caching" comment
    # below. `scan_date`/`computed_at` above always reflect when the
    # underlying scan was actually computed, cache hit or not.
    cache_hit: bool = False


# --- Redis caching (SPEC.md section 59; see packages/common/cache.py and
# packages/scoring/engine.py's identical pattern for the Research Score).
# `compute_all_momentum_scans_job` write-throughs every instrument's scan
# into Redis right after persisting it, so the cache is warm immediately
# after every batch run; the on-demand `/momentum-scan` route checks the
# cache first and only falls back to a live computation on a miss. TTL
# matches the score cache (30 minutes) for the same reason: a safety net
# bounding staleness if the batch job is ever delayed, not the primary
# population mechanism.
MOMENTUM_SCAN_CACHE_KEY_PREFIX = "momentum_scan:v1"
MOMENTUM_SCAN_CACHE_TTL_SECONDS = 1800


def momentum_scan_cache_key(instrument_id: object, sma200_trend_lookback_days: int) -> str:
    return f"{MOMENTUM_SCAN_CACHE_KEY_PREFIX}:{instrument_id}:{sma200_trend_lookback_days}"


def to_momentum_scan_cache_payload(result: MomentumScanResponse) -> dict:
    """JSON-serializable dict matching `MomentumScanResponse` (minus the
    per-request `cache_hit` flag - never itself cached, same reasoning
    as `packages.scoring.engine.to_score_response_payload`)."""
    payload = result.model_dump()
    payload.pop("cache_hit", None)
    return payload


def _none_if_nan(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


# PERFORMANCE (same lesson already learned for valuation percentiles -
# see packages/scoring/components.py's module-level comment): computing
# RS Rank requires a universe-wide percentile. The batch job
# (`compute_all_momentum_scans_job`) computes every instrument's raw
# score exactly once up front and ranks them together - O(n log n). The
# on-demand path below uses a short-TTL, process-local cache of that
# same universe scan so a single `/momentum-scan` call doesn't trigger
# its own full ~750-instrument rescan.
_RS_RANK_CACHE_TTL = timedelta(minutes=15)
_rs_rank_universe_cache: dict[str, Any] = {"computed_at": None, "raw_scores": None}


async def compute_universe_raw_scores(session: AsyncSession) -> RawScoreUniverse:
    """Raw RS Rank scores for every active EQUITY instrument with enough history.

    The uncached, full-universe computation - called exactly once per
    batch run. See `get_cached_universe_raw_scores` for the on-demand
    equivalent.
    """
    stmt = select(Instrument.id).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
    instrument_ids = [row[0] for row in (await session.execute(stmt)).all()]

    raw_scores: RawScoreUniverse = {}
    for instrument_id in instrument_ids:
        df = await load_ohlcv_dataframe(session, instrument_id)
        if df.empty:
            continue
        result = compute_raw_score(df["adjusted_close"])
        if result.raw_score is not None:
            raw_scores[instrument_id] = result.raw_score
    return raw_scores


async def get_cached_universe_raw_scores(session: AsyncSession, as_of: datetime) -> RawScoreUniverse:
    """TTL-cached wrapper around `compute_universe_raw_scores` for on-demand callers.

    Mirrors `packages.scoring.components.get_cached_universe_valuation_values`
    exactly (same TTL-cache shape, same reasoning): a process-local,
    module-level cache so N on-demand `/momentum-scan` calls within
    `_RS_RANK_CACHE_TTL` collapse into one universe scan instead of N.
    """
    cached_at: datetime | None = _rs_rank_universe_cache["computed_at"]
    if cached_at is not None:
        age = as_of - cached_at
        if timedelta(0) <= age < _RS_RANK_CACHE_TTL:
            return _rs_rank_universe_cache["raw_scores"]

    raw_scores = await compute_universe_raw_scores(session)
    _rs_rank_universe_cache["computed_at"] = as_of
    _rs_rank_universe_cache["raw_scores"] = raw_scores
    return raw_scores


async def _single_instrument_rs_rank(session: AsyncSession, instrument: Instrument, full_df: Any) -> float | None:
    """RS Rank for one instrument via the cached universe scan (on-demand path)."""
    own = compute_raw_score(full_df["adjusted_close"])
    if own.raw_score is None:
        return None

    now = datetime.now(UTC)
    universe = dict(await get_cached_universe_raw_scores(session, now))
    universe[instrument.id] = own.raw_score  # ensure this instrument is in the ranked population even if the cache predates it

    ranks = percentile_rank_universe({str(k): v for k, v in universe.items()})
    return ranks.get(str(instrument.id))


async def compute_momentum_scan(
    session: AsyncSession,
    instrument: Instrument,
    *,
    precomputed_rs_rank: float | None = None,
    sma200_trend_lookback_days: int = DEFAULT_SMA200_TREND_LOOKBACK_DAYS,
    persist: bool = True,
) -> MomentumScanResponse:
    """Compute (and, by default, persist) one instrument's Stage 2 Momentum Scan.

    `precomputed_rs_rank`: pass this when the caller already ranked the
    whole universe once for a batch run (`compute_all_momentum_scans_job`)
    - avoids re-deriving the universe scan per instrument. When omitted
    (the on-demand `/momentum-scan` route's call path), RS Rank is
    computed via `_single_instrument_rs_rank` (short-TTL-cached universe
    scan) instead - same methodology either way, just computed less
    often on the batch path.
    """
    full_df = await load_ohlcv_dataframe(session, instrument.id)
    now = datetime.now(UTC)

    scan_date: date | None
    if full_df.empty:
        result = MomentumScanResult(
            evaluable=False,
            passed=None,
            sma200_trend_lookback_days=sma200_trend_lookback_days,
            reason="insufficient_price_history",
        )
        scan_date = None
    else:
        series = compute_indicator_series(full_df)
        latest = series.iloc[-1]
        scan_date = latest["trading_date"]
        history_length = len(series)

        lookback_idx = -1 - sma200_trend_lookback_days
        sma_200_n_days_ago = (
            _none_if_nan(series["sma_200"].iloc[lookback_idx]) if history_length > sma200_trend_lookback_days else None
        )

        rs_rank = precomputed_rs_rank
        if rs_rank is None:
            rs_rank = await _single_instrument_rs_rank(session, instrument, full_df)

        result = evaluate_stage2_momentum(
            close=float(latest["close"]),
            sma_50=_none_if_nan(latest["sma_50"]),
            sma_150=_none_if_nan(latest["sma_150"]),
            sma_200=_none_if_nan(latest["sma_200"]),
            sma_200_n_days_ago=sma_200_n_days_ago,
            fifty_two_week_high=_none_if_nan(latest["fifty_two_week_high"]),
            fifty_two_week_low=_none_if_nan(latest["fifty_two_week_low"]),
            rs_rank=rs_rank,
            history_length=history_length,
            sma200_trend_lookback_days=sma200_trend_lookback_days,
        )

    conditions_payload = [asdict(c) for c in result.conditions]

    if persist:
        row = MomentumScan(
            id=uuid.uuid4(),
            instrument_id=instrument.id,
            scan_date=scan_date if scan_date is not None else now.date(),
            passed=result.passed,
            conditions=conditions_payload,
            distance_from_52w_high_pct=result.distance_from_52w_high_pct,
            rs_rank=result.rs_rank,
            sma200_trend_lookback_days=sma200_trend_lookback_days,
            methodology_version=METHODOLOGY_VERSION,
            computed_at=now,
        )
        session.add(row)
        await session.commit()

    return MomentumScanResponse(
        instrument_id=str(instrument.id),
        symbol=instrument.symbol,
        exchange=instrument.exchange,
        scan_date=scan_date.isoformat() if scan_date is not None else None,
        evaluable=result.evaluable,
        passed=result.passed,
        conditions=[ConditionOut.model_validate(c) for c in conditions_payload],
        distance_from_52w_high_pct=result.distance_from_52w_high_pct,
        rs_rank=result.rs_rank,
        rs_rank_universe=RS_RANK_UNIVERSE_LABEL,
        sma200_trend_lookback_days=sma200_trend_lookback_days,
        methodology_version=METHODOLOGY_VERSION,
        computed_at=now.isoformat(),
        reason=result.reason,
    )
