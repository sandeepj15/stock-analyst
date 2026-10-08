"""Arq background jobs (SPEC.md sections 56-58).

`sync_daily_bars` (instrument/data layer bootstrap), `sync_fundamentals`,
`sync_analyst_estimates_job` (standalone/manually-triggerable, like
`sync_fundamentals_job` - never part of the daily cron, since analyst
1Y price targets don't move daily), `sync_market_regime` (Phase 3,
SPEC.md sections 12, 15, 56),
`compute_all_scores_job` (batch Research Score pre-computation),
`compute_all_momentum_scans_job` (batch Stage 2 Momentum Scanner
pre-computation, `packages/momentum/`), and `daily_market_close_sync`
(the daily after-market-close orchestrating pipeline, see
`apps/worker/settings.py`'s `cron_jobs` registration) are implemented
here. News sync and indicator pre-computation jobs belong to later
phases and are intentionally not stubbed here to avoid implying they
exist.

The Research Score and Momentum Scan are also computed on demand
(`GET /stocks/{symbol}/score`, `GET /stocks/{symbol}/momentum-scan`) -
both routes are Redis-cache-first (SPEC.md section 59), and these two
batch jobs are each cache's *primary* write-through populator (see
`packages/scoring/engine.py` and `packages/momentum/service.py`'s
"Redis caching" comments). They exist *in addition to* the on-demand
paths so `GET /api/v1/instruments?sort=score|momentum_pass` can read a
cheap, already-persisted row per instrument instead of computing all
~750 scores/scans live on every home-page load - see
`apps/api/routes/instruments.py`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from packages.analyst_estimates.factory import get_analyst_estimate_provider
from packages.analyst_estimates.ingestion import (
    ANALYST_RATING_CACHE_TTL_SECONDS,
    analyst_rating_cache_key,
    sync_analyst_estimate,
    to_analyst_estimate_cache_payload,
)
from packages.analyst_estimates.models import AnalystEstimate
from packages.common import cache
from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.models import Instrument
from packages.fundamentals.factory import get_fundamental_provider, get_quarterly_fundamental_provider
from packages.fundamentals.ingestion import sync_fundamentals as sync_fundamentals_for_instrument
from packages.market_data.factory import get_provider
from packages.market_data.ingestion import DEFAULT_INGESTION_CONCURRENCY, ingest_daily_bars_for_instruments
from packages.momentum.rs_rank import percentile_rank_universe
from packages.momentum.service import (
    MOMENTUM_SCAN_CACHE_TTL_SECONDS,
    compute_momentum_scan,
    compute_universe_raw_scores,
    momentum_scan_cache_key,
    to_momentum_scan_cache_payload,
)
from packages.regime.service import compute_and_store_regime
from packages.scoring.components import compute_universe_valuation_values
from packages.scoring.engine import (
    SCORE_CACHE_TTL_SECONDS,
    compute_research_score,
    score_cache_key,
    to_score_response_payload,
)

logger = logging.getLogger(__name__)

DEFAULT_BACKFILL_DAYS = 730  # ~2 years, matches scripts/seed_dev_data.py

# Small trailing window used by the daily after-close pipeline
# (`daily_market_close_sync` below) instead of `DEFAULT_BACKFILL_DAYS`.
# 10 calendar days safely overlaps the last few already-ingested trading
# days (covering weekends/holidays/a missed run) - the idempotent
# `ON CONFLICT` upsert in `ingest_daily_bars` makes re-fetching those
# overlapping days a harmless, cheap no-op, never a duplicate.
DAILY_SYNC_OHLCV_LOOKBACK_DAYS = 10

# Bounded-concurrency fan-out for `sync_analyst_estimates_job`, same
# magnitude/reasoning as `scripts/seed_fundamentals.py::DEFAULT_CONCURRENCY`
# - both yfinance and tradingview-ta are free, unofficial, no-API-key
# endpoints that can throttle/block bursty traffic at ~750-symbol scale.
ANALYST_ESTIMATES_SYNC_CONCURRENCY = 6


async def sync_daily_bars(
    ctx: dict[str, Any], instrument_ids: list[str] | None = None, lookback_days: int | None = None
) -> dict[str, Any]:
    """Sync daily OHLCV bars for the given instruments (or all active ones).

    NOTE: SPEC.md section 83's pseudocode signature uses
    `instrument_ids: list[int]`; this implementation uses `list[str]`
    (UUID strings) because the instrument master's primary key is a UUID
    (see `packages/common/models.py::Instrument`), not an integer. The
    job name, idempotent-by-design behavior, and semantics are unchanged.

    `lookback_days`: `None` (the default) preserves this job's original
    behavior - a full `DEFAULT_BACKFILL_DAYS` (~2 year) backfill, exactly
    what every existing caller (manual full backfills, e.g. via
    `docker compose exec worker python -c "..."`) already gets. Pass a
    small value instead for a fast *incremental* sync - this is what
    `daily_market_close_sync` below does (`DAILY_SYNC_OHLCV_LOOKBACK_DAYS`)
    so the daily after-close pipeline never re-downloads ~2 years of
    history just to pick up today's one new bar per instrument.

    Covers every active `Instrument` regardless of `instrument_type`
    (same filter as before this change) - this naturally includes the
    NIFTY50 benchmark (`instrument_type="INDEX"`, see
    `packages/regime/service.py`) alongside every active EQUITY, with no
    separate benchmark-only code path needed.

    Runs with bounded concurrency (SPEC.md section 59) via
    `packages.market_data.ingestion.ingest_daily_bars_for_instruments` -
    the same semaphore-capped concurrent-fetch-with-retry/backoff pattern
    already proven at the ~750-symbol scale in
    `scripts/seed_dev_data.py`, not a sequential loop. One instrument's
    permanent failure never aborts the batch.

    Idempotent/safely re-runnable: `ingest_daily_bars` upserts on
    (instrument_id, trading_date, source), so running this job again with
    the same or overlapping date range never creates duplicates.
    """
    settings = get_settings()
    provider = get_provider(settings)

    end = date.today()
    days = lookback_days if lookback_days is not None else DEFAULT_BACKFILL_DAYS
    start = end - timedelta(days=days)

    async with session_scope() as session:
        stmt = select(Instrument.id, Instrument.symbol, Instrument.exchange).where(Instrument.active.is_(True))
        if instrument_ids:
            stmt = stmt.where(Instrument.id.in_(instrument_ids))
        instrument_refs = [(row.id, row.symbol, row.exchange) for row in (await session.execute(stmt)).all()]

    results = await ingest_daily_bars_for_instruments(
        provider, instrument_refs, start, end, concurrency=DEFAULT_INGESTION_CONCURRENCY
    )

    logger.info(
        "sync_daily_bars completed",
        extra={"synced": len(results["synced"]), "failed": len(results["failed"]), "lookback_days": days},
    )
    return results


async def sync_fundamentals_job(ctx: dict[str, Any], instrument_ids: list[str] | None = None) -> dict[str, Any]:
    """Sync fundamentals snapshots for the given instruments (or all active EQUITY ones).

    Mirrors `sync_daily_bars`: idempotent (upsert on `(instrument_id,
    period_end, period_type, source)`), and a single instrument's
    provider failure never aborts the rest of the batch (SPEC.md section
    58). A thinly-covered NSE ticker returning zero snapshots is a normal
    outcome, not a failure - see `packages/fundamentals/providers/`.
    """
    settings = get_settings()
    provider = get_fundamental_provider(settings)

    results: dict[str, Any] = {"synced": [], "failed": []}

    async with session_scope() as session:
        stmt = select(Instrument).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
        if instrument_ids:
            stmt = stmt.where(Instrument.id.in_(instrument_ids))
        instruments = (await session.execute(stmt)).scalars().all()

        for instrument in instruments:
            try:
                result = await sync_fundamentals_for_instrument(provider, session, instrument)
                results["synced"].append({"symbol": instrument.symbol, "rows_processed": result.rows_processed})
            except Exception as exc:
                logger.error(
                    "sync_fundamentals_job: instrument failed, continuing with next",
                    extra={"symbol": instrument.symbol, "exchange": instrument.exchange, "error": str(exc)},
                )
                results["failed"].append({"symbol": instrument.symbol, "error": str(exc)})

    logger.info(
        "sync_fundamentals_job completed", extra={"synced": len(results["synced"]), "failed": len(results["failed"])}
    )
    return results


async def sync_quarterly_fundamentals_job(ctx: dict[str, Any], instrument_ids: list[str] | None = None) -> dict[str, Any]:
    """Sync quarterly (`period_type="Q"`) fundamentals snapshots for the given instruments (or all active EQUITY ones).

    Standalone/manually-triggerable only, like `sync_fundamentals_job` and
    `sync_analyst_estimates_job` - deliberately **not** part of
    `daily_market_close_sync`'s cron pipeline: quarterly results change
    ~4x/year, so running this daily would be pure waste against a free,
    unofficial, rate-limitable provider for no freshness benefit.

    Reuses `sync_fundamentals_for_instrument` unchanged - it's already
    generic over `period_type`/`source`, it just needs a provider that
    returns `period_type="Q"` snapshots (see
    `YFinanceQuarterlyFundamentalProvider`). Same per-instrument
    try/except-and-continue behavior as `sync_fundamentals_job`.
    """
    settings = get_settings()
    provider = get_quarterly_fundamental_provider(settings)

    results: dict[str, Any] = {"synced": [], "failed": []}

    async with session_scope() as session:
        stmt = select(Instrument).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
        if instrument_ids:
            stmt = stmt.where(Instrument.id.in_(instrument_ids))
        instruments = (await session.execute(stmt)).scalars().all()

        for instrument in instruments:
            try:
                result = await sync_fundamentals_for_instrument(provider, session, instrument)
                results["synced"].append({"symbol": instrument.symbol, "rows_processed": result.rows_processed})
            except Exception as exc:
                logger.error(
                    "sync_quarterly_fundamentals_job: instrument failed, continuing with next",
                    extra={"symbol": instrument.symbol, "exchange": instrument.exchange, "error": str(exc)},
                )
                results["failed"].append({"symbol": instrument.symbol, "error": str(exc)})

    logger.info(
        "sync_quarterly_fundamentals_job completed",
        extra={"synced": len(results["synced"]), "failed": len(results["failed"])},
    )
    return results


async def sync_analyst_estimates_job(ctx: dict[str, Any], instrument_ids: list[str] | None = None) -> dict[str, Any]:
    """Sync analyst 1Y price-target estimates for the given instruments (or all active EQUITY ones).

    Standalone/manually-triggerable only, like `sync_fundamentals_job` -
    deliberately **not** part of `daily_market_close_sync`'s cron
    pipeline: analyst price targets don't move daily (unlike OHLCV/
    scores/momentum, which the daily pipeline exists to keep fresh), so
    running this on every market close would be pure waste against two
    free, unofficial, rate-limitable providers for no freshness benefit -
    same reasoning already applied to fundamentals.

    Idempotent (upsert on `instrument_id` - see
    `packages/analyst_estimates/models.py`), and a single instrument's
    provider failure never aborts the rest of the batch (SPEC.md section
    58). Zero analyst coverage for an instrument is a normal, common
    outcome for mid/small-cap NSE names, not a failure - see
    `packages/analyst_estimates/providers/`.

    Write-through populates the Redis analyst-rating cache for every
    instrument that has coverage (SPEC.md section 59) - see
    `packages/analyst_estimates/ingestion.py`'s "Redis caching" comment.
    An instrument that has zero coverage has its cache entry (if any)
    cleared, not left stale - `sync_analyst_estimate` already deletes any
    stale persisted row for that case, and no cache write-through is
    needed since the on-demand route's cache-miss path already reports
    "no coverage" correctly from an empty table.

    Runs with **bounded concurrency** (SPEC.md section 59), same
    reasoning/shape as `scripts/seed_fundamentals.py`: both yfinance and
    tradingview-ta are unofficial, free, no-API-key endpoints that can
    throttle/block bursty sequential traffic at hundreds-of-symbols
    scale, so this fans out a handful of concurrent in-flight requests
    (not hundreds, not fully sequential) via a semaphore, each with its
    own short-lived `session_scope()` - true per-instrument isolation,
    same rationale as `compute_all_scores_job`'s per-instrument sessions
    above, and safe for concurrent writes either way since
    `sync_analyst_estimate`'s upsert is idempotent.
    """
    settings = get_settings()
    provider = get_analyst_estimate_provider(settings)

    results: dict[str, Any] = {"synced": [], "no_coverage": [], "failed": []}
    semaphore = asyncio.Semaphore(ANALYST_ESTIMATES_SYNC_CONCURRENCY)

    async with session_scope() as session:
        stmt = select(Instrument.id, Instrument.symbol, Instrument.exchange).where(
            Instrument.active.is_(True), Instrument.instrument_type == "EQUITY"
        )
        if instrument_ids:
            stmt = stmt.where(Instrument.id.in_(instrument_ids))
        targets = (await session.execute(stmt)).all()

    async def _sync_batch(batch_targets: list[tuple[Any, str, str]]) -> None:
        async with semaphore:
            try:
                async with session_scope() as task_session:
                    from packages.analyst_estimates.ingestion import sync_analyst_estimates_batch
                    
                    ids = [t[0] for t in batch_targets]
                    stmt = select(Instrument).where(Instrument.id.in_(ids))
                    fresh_instruments = list((await task_session.execute(stmt)).scalars().all())
                    
                    batch_results = await sync_analyst_estimates_batch(provider, task_session, fresh_instruments)
                    
                    for res in batch_results:
                        if not res.has_coverage:
                            results["no_coverage"].append({"symbol": res.symbol})
                            inst = next(i for i in fresh_instruments if i.symbol == res.symbol)
                            await cache.delete(analyst_rating_cache_key(inst.id))
                        else:
                            results["synced"].append({"symbol": res.symbol, "source": res.source})
                            inst = next(i for i in fresh_instruments if i.symbol == res.symbol)
                            stmt2 = select(AnalystEstimate).where(AnalystEstimate.instrument_id == inst.id)
                            row = (await task_session.execute(stmt2)).scalar_one_or_none()
                            if row:
                                payload = to_analyst_estimate_cache_payload(row)
                                await cache.set_json(analyst_rating_cache_key(inst.id), payload, ANALYST_RATING_CACHE_TTL_SECONDS)
            except Exception as exc:
                logger.error("sync_analyst_estimates_batch failed", extra={"error": str(exc)})
                for t in batch_targets:
                    results["failed"].append({"symbol": t[1], "error": str(exc)})

    # Chunk into sizes of 100 to maximize TV batch efficiency (750 / 100 = ~8 chunks)
    batch_size = 100
    chunks = [targets[i:i + batch_size] for i in range(0, len(targets), batch_size)]
    tasks = [_sync_batch(chunk) for chunk in chunks]
    await asyncio.gather(*tasks)

    logger.info(
        "sync_analyst_estimates_job completed",
        extra={
            "synced": len(results["synced"]),
            "no_coverage": len(results["no_coverage"]),
            "failed": len(results["failed"]),
        },
    )
    return results


async def sync_market_regime(ctx: dict[str, Any]) -> dict[str, Any]:
    """Refresh the Nifty 50 benchmark and recompute today's market regime (SPEC.md section 15)."""
    settings = get_settings()
    async with session_scope() as session:
        result = await compute_and_store_regime(session, settings=settings)

    logger.info("sync_market_regime completed", extra={"date": result.date, "regime": result.regime})
    return result.model_dump()


async def compute_all_scores_job(ctx: dict[str, Any], instrument_ids: list[str] | None = None) -> dict[str, Any]:
    """Pre-compute and persist a fresh Research Strength v1 score for every active instrument.

    Reuses `compute_research_score` (packages/scoring/engine.py) exactly
    as the on-demand `GET /api/v1/stocks/{symbol}/score` path does - no
    scoring/analytics logic is duplicated here. This job's only purpose
    is to populate `research_scores` so `GET /api/v1/instruments` can
    report a `score`/`confidence`/`band` per instrument without computing
    all of them live on every request.

    Idempotent/safely re-runnable: `compute_research_score` always
    inserts a new `research_scores` row (append-only history, matching
    the on-demand endpoint's behavior and SPEC.md section 47) - it never
    mutates or deletes a prior row, so running this job again is always
    safe and simply adds a fresher row that `/api/v1/instruments` will
    pick up (it reads the most recently *persisted* row).

    Resilient to a single instrument's failure (e.g. zero OHLCV history,
    which `compute_research_score` raises `ValueError` for): logged and
    skipped, matching `sync_daily_bars`/`sync_fundamentals_job` above.
    Each instrument gets its own fresh `session_scope()` (rather than one
    session shared across the whole batch) - the same short-lived,
    one-transaction-per-unit-of-work pattern `get_db_session` already
    uses per HTTP request. This gives true per-instrument isolation (one
    instrument's failure can never leave a shared session/transaction in
    a bad state for the next one) and sidesteps the many-commits-on-one
    long-lived-session edge cases that pattern avoids elsewhere in this
    codebase.

    PERFORMANCE (fixed - see packages/scoring/components.py module-level
    comment and SCORING.md): `score_valuation`'s universe-wide valuation
    peer population (`_universe_valuation_values`) used to be rescanned
    from scratch on every single instrument's score computation, making
    this job O(N^2) in the number of active instruments - a few minutes
    at ~117 instruments, projected 40x+ worse (likely over an hour) at
    ~750. This job now computes that universe scan exactly **once**, up
    front, and passes the same precomputed dict into every
    `compute_research_score` call below - O(N) total. The valuation
    *methodology* is unchanged (same `_universe_valuation_values` /
    `_percentile_cheaper` functions; see
    tests/unit/scoring/test_valuation_cache.py for a proof that the
    precomputed path returns identical percentiles to a naive
    per-instrument rescan).
    """
    results: dict[str, Any] = {"scored": [], "failed": []}

    async with session_scope() as session:
        stmt = select(Instrument.id, Instrument.symbol, Instrument.exchange).where(
            Instrument.active.is_(True), Instrument.instrument_type == "EQUITY"
        )
        if instrument_ids:
            stmt = stmt.where(Instrument.id.in_(instrument_ids))
        targets = (await session.execute(stmt)).all()

        # Computed once for the whole batch (see docstring above) - every
        # instrument below reuses this same dict instead of triggering its
        # own full universe rescan.
        universe_valuation = await compute_universe_valuation_values(session, datetime.now(UTC))

    for instrument_id, symbol, exchange in targets:
        try:
            async with session_scope() as session:
                instrument = await session.get(Instrument, instrument_id)
                if instrument is None:
                    raise ValueError(f"instrument {instrument_id} no longer exists")
                result = await compute_research_score(
                    session, instrument, precomputed_universe_valuation=universe_valuation
                )
            # Write-through cache population (SPEC.md section 59): this is
            # the *primary* way the Redis score cache gets populated - see
            # packages/scoring/engine.py's "Redis caching" comment. The
            # on-demand `/score` endpoint's own cache-miss path is only a
            # safety net for instruments this batch run hasn't covered yet.
            await cache.set_json(
                score_cache_key(instrument_id), to_score_response_payload(result), SCORE_CACHE_TTL_SECONDS
            )
            results["scored"].append({"symbol": symbol, "score": result.score, "band": result.band})
        except Exception as exc:
            logger.error(
                "compute_all_scores_job: instrument failed, continuing with next",
                extra={"symbol": symbol, "exchange": exchange, "error": str(exc)},
            )
            results["failed"].append({"symbol": symbol, "error": str(exc)})

    logger.info(
        "compute_all_scores_job completed",
        extra={"scored": len(results["scored"]), "failed": len(results["failed"])},
    )
    return results


async def compute_all_momentum_scans_job(ctx: dict[str, Any], instrument_ids: list[str] | None = None) -> dict[str, Any]:
    """Pre-compute and persist a fresh Stage 2 Momentum Scan for every active EQUITY instrument.

    Mirrors `compute_all_scores_job` exactly: RS Rank requires a
    universe-wide percentile, so this job computes every instrument's
    raw score **once**, ranks the whole universe together in one
    O(n log n) sort (`packages.momentum.rs_rank.percentile_rank_universe`),
    and passes each instrument's own percentile into
    `compute_momentum_scan` - never an O(n^2) rescan per instrument (the
    same mistake already fixed for valuation percentiles, see
    packages/scoring/components.py).

    Idempotent/safely re-runnable (always inserts a new `momentum_scans`
    row, same append-only pattern as `research_scores` - see
    packages/momentum/models.py) and resilient to a single instrument's
    failure, matching every other batch job in this module.

    Write-through populates the Redis momentum-scan cache for every
    instrument immediately (SPEC.md section 59) - see
    packages/momentum/service.py's "Redis caching" comment.
    """
    results: dict[str, Any] = {"scanned": [], "failed": []}

    async with session_scope() as session:
        stmt = select(Instrument.id, Instrument.symbol, Instrument.exchange).where(
            Instrument.active.is_(True), Instrument.instrument_type == "EQUITY"
        )
        if instrument_ids:
            stmt = stmt.where(Instrument.id.in_(instrument_ids))
        targets = (await session.execute(stmt)).all()

        # Computed + ranked exactly once for the whole batch (see docstring above).
        raw_scores = await compute_universe_raw_scores(session)
        rs_ranks = percentile_rank_universe({str(k): v for k, v in raw_scores.items()})

    for instrument_id, symbol, exchange in targets:
        try:
            precomputed_rs_rank = rs_ranks.get(str(instrument_id))
            async with session_scope() as session:
                instrument = await session.get(Instrument, instrument_id)
                if instrument is None:
                    raise ValueError(f"instrument {instrument_id} no longer exists")
                result = await compute_momentum_scan(
                    session, instrument, precomputed_rs_rank=precomputed_rs_rank
                )
            await cache.set_json(
                momentum_scan_cache_key(instrument_id, result.sma200_trend_lookback_days),
                to_momentum_scan_cache_payload(result),
                MOMENTUM_SCAN_CACHE_TTL_SECONDS,
            )
            results["scanned"].append({"symbol": symbol, "passed": result.passed, "rs_rank": result.rs_rank})
        except Exception as exc:
            logger.error(
                "compute_all_momentum_scans_job: instrument failed, continuing with next",
                extra={"symbol": symbol, "exchange": exchange, "error": str(exc)},
            )
            results["failed"].append({"symbol": symbol, "error": str(exc)})

    logger.info(
        "compute_all_momentum_scans_job completed",
        extra={"scanned": len(results["scanned"]), "failed": len(results["failed"])},
    )
    return results


# Wildcard match for every `GET /api/v1/instruments` listing cache key
# variant (one per exchange/active_only/sort/order/momentum_pass
# combination - see `apps/api/routes/instruments.py`'s `cache_key`
# f-string). All share the `instruments_listing:v1:` prefix, so a single
# pattern delete covers every variant without enumerating them.
INSTRUMENTS_LISTING_CACHE_PATTERN = "instruments_listing:v1:*"


def _summarize_step_result(result: Any) -> dict[str, Any]:
    """Reduce a reused job's raw return value to a small, loggable summary.

    Every reused job here (`sync_daily_bars`, `compute_all_scores_job`,
    `compute_all_momentum_scans_job`) returns a dict with one or more
    list-valued keys (`synced`/`failed`, `scored`/`failed`, ...) - this
    reduces those to counts. `sync_market_regime` instead returns a
    small single-record dict (date/regime/...) with no list fields, which
    is returned as-is since it's already small and informative.
    """
    if isinstance(result, dict):
        list_counts = {f"{key}_count": len(value) for key, value in result.items() if isinstance(value, list)}
        if list_counts:
            return list_counts
        return result
    return {"result": repr(result)}


async def daily_market_close_sync(ctx: dict[str, Any]) -> dict[str, Any]:
    """Daily, automatic, Mon-Fri-only, after-market-close refresh pipeline.

    Scheduled by arq's native cron support - see `apps/worker/settings.py`'s
    `cron_jobs` registration for the exact UTC schedule and the IST<->UTC
    reasoning/arq weekday-numbering verification. This function is also
    independently callable (e.g. for a manual test trigger via
    `docker compose exec worker python -c "..."`, matching every other
    job in this module).

    Runs five steps, strictly in this order, because each later step
    depends on an earlier one's output being fresh (SPEC.md section 58 -
    scoring/momentum must never run against stale prices):

    1. Incremental OHLCV sync (`sync_daily_bars` with a small
       `DAILY_SYNC_OHLCV_LOOKBACK_DAYS`-day lookback, not a full ~2-year
       backfill) for every active instrument - EQUITY *and* the NIFTY50
       benchmark, both already covered by `sync_daily_bars`'s single
       `Instrument.active.is_(True)` filter.
    2. `sync_market_regime` - recomputes today's regime/breadth from the
       now-fresh benchmark and universe OHLCV. Reused exactly as-is
       (methodology untouched); its own internal benchmark refresh still
       does its original full-history call, which is cheap (one symbol)
       and a harmless idempotent no-op/overlap with step 1.
    3. `compute_all_scores_job` - fresh Research Score for every active
       EQUITY instrument, written straight through to the Redis score
       cache (packages/scoring/engine.py).
    4. `compute_all_momentum_scans_job` - fresh Stage 2 Momentum Scan for
       every active EQUITY instrument, written straight through to the
       Redis momentum-scan cache (packages/momentum/service.py).
    5. Proactively invalidate every `GET /api/v1/instruments` listing
       cache key variant (`packages.common.cache.delete_pattern`) so the
       home page reflects today's fresh data immediately, instead of
       waiting up to `LISTING_CACHE_TTL_SECONDS` (90s) for the existing
       TTL to lapse.

    Each step is independently try/except-isolated: a genuine failure in
    one step (e.g. 5 of 755 OHLCV syncs failing, or even all of step 1
    raising) is logged and this job proceeds to the remaining steps
    regardless, matching the per-instrument resilience pattern already
    used inside every one of these four reused jobs - one bad step must
    never silently skip the rest of the pipeline, and must never be
    reported as if the whole run succeeded.

    Idempotent/safely re-runnable: every underlying step already is
    (upsert-based OHLCV sync, idempotent upsert-by-date regime row,
    append-only score/momentum rows, best-effort cache operations) -
    running this job twice in a row (e.g. a manual test trigger followed
    by the real scheduled fire) is always safe and never double-counts
    anything.

    Does not replace, duplicate, or change the behavior of
    `sync_daily_bars` / `sync_market_regime` / `compute_all_scores_job` /
    `compute_all_momentum_scans_job` as independently callable arq jobs -
    all four remain exactly as before (e.g. for a manual full backfill
    via `make seed`/`make sync-regime`/`make compute-scores`); this job
    only orchestrates calls into their existing logic with a smaller,
    faster OHLCV window and in a fixed, dependency-respecting order.

    Known limitation (not fixed here, SPEC.md section 81): NSE holidays
    aren't modeled, so a Mon-Fri cron still fires on NSE holidays that
    land on a weekday. yfinance simply returns no new bar for that date,
    which the existing missing-trading-day data quality check already
    handles as a harmless, already-documented weekday-approximation
    limitation (packages/market_data/quality.py) - not a new issue
    introduced by this job.
    """
    started_at = datetime.now(UTC)
    step_summary: dict[str, Any] = {}

    async def _run_step(name: str, coro: Any) -> None:
        step_started = time.monotonic()
        try:
            result = await coro
        except Exception as exc:
            logger.error(
                "daily_market_close_sync: step failed, continuing with remaining steps",
                extra={"step": name, "error": str(exc)},
            )
            step_summary[name] = {"ok": False, "duration_seconds": round(time.monotonic() - step_started, 2), "error": str(exc)}
            return
        step_summary[name] = {
            "ok": True,
            "duration_seconds": round(time.monotonic() - step_started, 2),
            **_summarize_step_result(result),
        }

    await _run_step("ohlcv_sync", sync_daily_bars(ctx, lookback_days=DAILY_SYNC_OHLCV_LOOKBACK_DAYS))
    await _run_step("market_regime", sync_market_regime(ctx))
    await _run_step("research_scores", compute_all_scores_job(ctx))
    await _run_step("momentum_scans", compute_all_momentum_scans_job(ctx))

    cache_step_started = time.monotonic()
    try:
        keys_deleted = await cache.delete_pattern(INSTRUMENTS_LISTING_CACHE_PATTERN)
        step_summary["cache_invalidation"] = {
            "ok": True,
            "duration_seconds": round(time.monotonic() - cache_step_started, 2),
            "keys_deleted": keys_deleted,
        }
    except Exception as exc:
        logger.error("daily_market_close_sync: cache invalidation step failed", extra={"error": str(exc)})
        step_summary["cache_invalidation"] = {
            "ok": False,
            "duration_seconds": round(time.monotonic() - cache_step_started, 2),
            "error": str(exc),
        }

    finished_at = datetime.now(UTC)
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
        "steps": step_summary,
    }
    logger.info("daily_market_close_sync completed", extra=summary)
    return summary
