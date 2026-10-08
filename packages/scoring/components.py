"""DB-backed component orchestration (SPEC.md sections 17-18, 86).

Thin wrappers that: load the data a component needs, call the pure point
functions in `packages/scoring/signals.py`, persist each sub-signal as an
`EvidenceItem` via the caller-supplied `EvidenceBuilder`, and return a
`packages.scoring.aggregate.ComponentResult` plus the `(Signal,
evidence_id)` pairs needed for the bull/bear case
(`packages/scoring/bull_bear.py`).

Every function here degrades to `ComponentResult(available=False, ...)`
rather than fabricating a score when its required data is missing -
never 0, never a neutral 50 standing in for "unknown" (SPEC.md section
81 rule 8, section 21 "do not pretend missing data is neutral").
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.analytics import max_drawdown as max_drawdown_fn
from packages.common.models import Instrument
from packages.fundamentals.derive import (
    asset_turnover,
    compute_valuation_metrics,
    current_ratio,
    debt_to_equity,
    fundamentals_data_age_days,
    fundamentals_freshness_score,
    growth_yoy,
    interest_coverage,
    net_debt_to_ebitda,
    net_profit_margin,
    return_on_assets,
    roce_simplified,
    roe,
)
from packages.fundamentals.models import FundamentalSnapshot
from packages.indicators import IndicatorSnapshot
from packages.market_data.history import load_ohlcv_dataframe
from packages.market_data.relative_strength import compute_relative_strength
from packages.regime.service import get_latest_regime
from packages.scoring.aggregate import ComponentResult
from packages.scoring.constants import COMPONENT_WEIGHTS
from packages.scoring.evidence import EvidenceBuilder
from packages.scoring.signals import (
    Signal,
    clamp_score,
    compute_fundamental_score,
    market_regime_signal,
    score_momentum_points,
    score_risk_quality_points,
    score_sector_relative_strength_points,
    score_technical_structure_points,
    score_valuation_points,
)

SignalPairs = list[tuple[Signal, uuid.UUID]]

MIN_VALUATION_PEER_POPULATION = 5
# Market regime should refresh daily (SPEC.md section 15/56) - freshness
# decays fast relative to fundamentals (SPEC.md section 12's much longer
# reporting cycle). Fully stale after 5 days with no refresh.
REGIME_FRESHNESS_DECAY_PER_DAY = 20.0


def _f(value: object) -> float | None:
    """Numeric ORM columns come back as `decimal.Decimal` - normalize to `float` (or `None`)."""
    return float(value) if value is not None else None  # type: ignore[arg-type]


def _unavailable(name: str, reason: str) -> ComponentResult:
    return ComponentResult(
        name=name, weight=COMPONENT_WEIGHTS[name], score=None, available=False, reason=reason, freshness=0.0
    )


def _emit_evidence(
    evidence_builder: EvidenceBuilder,
    *,
    evidence_type: str,
    signals: list[Signal],
    source_name: str,
    observed_at: datetime,
    source_timestamp: datetime,
    interpretation_suffix: str = "",
) -> SignalPairs:
    pairs: SignalPairs = []
    for s in signals:
        item = evidence_builder.add(
            evidence_type=evidence_type,
            metric_name=s.metric_name,
            interpretation=s.interpretation + interpretation_suffix,
            value_numeric=s.value,
            source_name=source_name,
            observed_at=observed_at,
            source_timestamp=source_timestamp,
            unit=s.unit,
        )
        pairs.append((s, item.id))
    return pairs


def score_technical_structure(
    snapshot: IndicatorSnapshot, evidence_builder: EvidenceBuilder, now: datetime, bar_timestamp: datetime
) -> tuple[ComponentResult, SignalPairs]:
    score, signals = score_technical_structure_points(
        close=snapshot.close,
        sma_50=snapshot.sma_50,
        sma_200=snapshot.sma_200,
        ema_20=snapshot.ema_20,
        ema_50=snapshot.ema_50,
        adx_14=snapshot.adx_14,
        breakout_20d=snapshot.breakout_20d,
        breakdown_20d=snapshot.breakdown_20d,
    )
    if not signals:
        return _unavailable("technical_structure", "insufficient_price_history"), []

    pairs = _emit_evidence(
        evidence_builder,
        evidence_type="technical_structure",
        signals=signals,
        source_name="indicator_engine",
        observed_at=now,
        source_timestamp=bar_timestamp,
    )
    result = ComponentResult(
        name="technical_structure",
        weight=COMPONENT_WEIGHTS["technical_structure"],
        score=score,
        available=True,
        reason=None,
        freshness=100.0,
        evidence_ids=tuple(str(eid) for _, eid in pairs),
    )
    return result, pairs


def score_momentum(
    snapshot: IndicatorSnapshot, evidence_builder: EvidenceBuilder, now: datetime, bar_timestamp: datetime
) -> tuple[ComponentResult, SignalPairs]:
    score, signals = score_momentum_points(
        rsi_14=snapshot.rsi_14,
        macd_histogram=snapshot.macd_histogram,
        roc_12=snapshot.roc_12,
        stochastic_k=snapshot.stochastic_k,
    )
    if not signals:
        return _unavailable("momentum", "insufficient_price_history"), []

    pairs = _emit_evidence(
        evidence_builder,
        evidence_type="momentum",
        signals=signals,
        source_name="indicator_engine",
        observed_at=now,
        source_timestamp=bar_timestamp,
    )
    result = ComponentResult(
        name="momentum",
        weight=COMPONENT_WEIGHTS["momentum"],
        score=score,
        available=True,
        reason=None,
        freshness=100.0,
        evidence_ids=tuple(str(eid) for _, eid in pairs),
    )
    return result, pairs


def score_risk_quality(
    full_df: pd.DataFrame, snapshot: IndicatorSnapshot, evidence_builder: EvidenceBuilder, now: datetime, bar_timestamp: datetime
) -> tuple[ComponentResult, SignalPairs]:
    atr_pct = (snapshot.atr_14 / snapshot.close * 100.0) if snapshot.atr_14 is not None and snapshot.close else None
    rolling_vol_pct = snapshot.rolling_volatility_20 * 100.0 if snapshot.rolling_volatility_20 is not None else None

    mdd = max_drawdown_fn(full_df["adjusted_close"])
    max_drawdown_pct = mdd * 100.0 if mdd == mdd else None  # NaN check (NaN != NaN)

    score, signals = score_risk_quality_points(
        atr_pct=atr_pct, rolling_volatility_pct=rolling_vol_pct, max_drawdown_pct=max_drawdown_pct
    )
    if not signals:
        return _unavailable("risk_quality", "insufficient_price_history"), []

    pairs = _emit_evidence(
        evidence_builder,
        evidence_type="risk_quality",
        signals=signals,
        source_name="indicator_engine",
        observed_at=now,
        source_timestamp=bar_timestamp,
    )
    result = ComponentResult(
        name="risk_quality",
        weight=COMPONENT_WEIGHTS["risk_quality"],
        score=score,
        available=True,
        reason=None,
        freshness=100.0,
        evidence_ids=tuple(str(eid) for _, eid in pairs),
    )
    return result, pairs


async def _latest_fundamental_snapshots(session: AsyncSession, instrument_id: uuid.UUID, limit: int = 2) -> list[FundamentalSnapshot]:
    stmt = (
        select(FundamentalSnapshot)
        .where(FundamentalSnapshot.instrument_id == instrument_id)
        .order_by(FundamentalSnapshot.period_end.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def score_fundamentals(
    session: AsyncSession, instrument: Instrument, evidence_builder: EvidenceBuilder, now: datetime
) -> tuple[ComponentResult, SignalPairs, FundamentalSnapshot | None]:
    """The Research Score's "fundamentals" component.

    Calls `packages.scoring.signals.compute_fundamental_score` - the
    exact same function `apps/api/routes/fundamentals.py::get_fundamentals`
    calls to build the standalone `fundamental_score` block - so this
    component's score and that endpoint's `fundamental_score.overall` can
    never silently disagree for the same instrument/snapshot (SCORING.md
    "Fundamental Score", single-source-of-truth guarantee; see
    `tests/unit/scoring/test_fundamental_score.py::test_single_source_of_truth_*`).
    """
    snapshots = await _latest_fundamental_snapshots(session, instrument.id, limit=2)
    if not snapshots:
        return _unavailable("fundamentals", "no_fundamental_data"), [], None

    latest = snapshots[0]
    previous = snapshots[1] if len(snapshots) > 1 else None

    sub_scores = compute_fundamental_score(
        revenue_growth_yoy=growth_yoy(_f(latest.revenue), _f(previous.revenue) if previous else None),
        pat_growth_yoy=growth_yoy(_f(latest.pat), _f(previous.pat) if previous else None),
        eps_growth_yoy=growth_yoy(_f(latest.eps), _f(previous.eps) if previous else None),
        roe=roe(_f(latest.pat), _f(latest.equity)),
        roce=roce_simplified(_f(latest.ebit), _f(latest.equity), _f(latest.total_debt)),
        roa=return_on_assets(_f(latest.pat), _f(latest.total_assets)),
        net_profit_margin=net_profit_margin(_f(latest.pat), _f(latest.revenue)),
        debt_to_equity=debt_to_equity(_f(latest.total_debt), _f(latest.equity)),
        net_debt_to_ebitda=net_debt_to_ebitda(_f(latest.total_debt), _f(latest.cash), _f(latest.ebitda)),
        interest_coverage=interest_coverage(_f(latest.ebit), _f(latest.interest_expense)),
        current_ratio=current_ratio(_f(latest.current_assets), _f(latest.current_liabilities)),
        asset_turnover=asset_turnover(_f(latest.revenue), _f(latest.total_assets)),
    )
    signals = list(sub_scores.signals)
    if not signals or sub_scores.overall is None:
        return _unavailable("fundamentals", "fundamental_data_insufficient"), [], latest
    score = sub_scores.overall

    pairs = _emit_evidence(
        evidence_builder,
        evidence_type="fundamentals",
        signals=signals,
        source_name=latest.source,
        observed_at=now,
        source_timestamp=latest.source_timestamp,
    )
    age_days = fundamentals_data_age_days(latest.period_end, now.date())
    freshness = fundamentals_freshness_score(age_days)
    result = ComponentResult(
        name="fundamentals",
        weight=COMPONENT_WEIGHTS["fundamentals"],
        score=score,
        available=True,
        reason=None,
        freshness=freshness,
        evidence_ids=tuple(str(eid) for _, eid in pairs),
    )
    return result, pairs, latest


def _percentile_cheaper(self_value: float, population: dict[str, float], min_population: int = MIN_VALUATION_PEER_POPULATION) -> float | None:
    """% of `population` that is more expensive than `self_value` (higher = cheaper = better).

    `None` (never a fabricated percentile) if the population is too small
    to rank against meaningfully.
    """
    values = list(population.values())
    if len(values) < min_population:
        return None
    cheaper_than_count = sum(1 for v in values if v > self_value)
    return cheaper_than_count / len(values) * 100.0


UniverseValuation = dict[str, dict[str, float]]

# PERFORMANCE (SPEC.md section 81 rule 24 "prefer simple deterministic
# implementations", applied to caching too): `_universe_valuation_values`
# below scans every active EQUITY instrument's latest fundamentals + OHLCV
# to build the P/E, P/B, EV/EBITDA peer population used for percentile
# ranking. Computing this once per instrument scored (the original
# behavior) is O(N^2) in the number of active instruments - fine for
# ~117, far too slow for ~750 (see SCORING.md and apps/worker/jobs.py).
#
# Caching strategy (two call paths, same underlying function, same
# methodology/output - see tests/unit/scoring/test_valuation_cache.py for
# proof the cached and naive paths return identical percentiles):
#
# 1. Batch path (`compute_all_scores_job`): computes the universe once
#    up front and passes it into every `compute_research_score` call via
#    `precomputed_universe_valuation` - O(N) total, no cache/TTL
#    involved, so there is no raciness to reason about for a batch run.
# 2. On-demand path (`GET /stocks/{symbol}/score`, and any other caller
#    that doesn't pass a precomputed value): falls back to
#    `_get_cached_universe_valuation_values`, a module-level,
#    process-local cache with a short TTL (`_VALUATION_CACHE_TTL`). A
#    single on-demand call still gets a fresh-enough universe snapshot
#    (worst case `_VALUATION_CACHE_TTL` stale) without re-scanning ~750
#    instruments on every request - acceptable because the valuation
#    peer population changes slowly (fundamentals refresh at most daily).
_VALUATION_CACHE_TTL = timedelta(minutes=15)
_valuation_cache: dict[str, Any] = {"computed_at": None, "values": None}


async def _universe_valuation_values(session: AsyncSession, as_of: datetime) -> UniverseValuation:
    """P/E, P/B, EV/EBITDA for every active seeded EQUITY instrument with computable valuation.

    This is the uncached, full-rescan computation. See the module-level
    comment above for how callers avoid paying its O(N) cost N times.
    """
    stmt = select(Instrument).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
    instruments = (await session.execute(stmt)).scalars().all()

    pe_values: dict[str, float] = {}
    pb_values: dict[str, float] = {}
    ev_ebitda_values: dict[str, float] = {}

    for inst in instruments:
        snaps = await _latest_fundamental_snapshots(session, inst.id, limit=1)
        if not snaps:
            continue
        snap = snaps[0]
        df = await load_ohlcv_dataframe(session, inst.id)
        if df.empty:
            continue
        close = float(df["adjusted_close"].iloc[-1])
        val = compute_valuation_metrics(
            close_price=close,
            period_end=snap.period_end,
            as_of=as_of.date(),
            eps=_f(snap.eps),
            equity=_f(snap.equity),
            shares_outstanding=_f(snap.shares_outstanding),
            revenue=_f(snap.revenue),
            ebitda=_f(snap.ebitda),
            total_debt=_f(snap.total_debt),
            cash=_f(snap.cash),
            free_cash_flow=_f(snap.free_cash_flow),
            dividend_yield=_f(snap.dividend_yield),
        )
        if val.pe is not None:
            pe_values[inst.symbol] = val.pe
        if val.pb is not None:
            pb_values[inst.symbol] = val.pb
        if val.ev_ebitda is not None:
            ev_ebitda_values[inst.symbol] = val.ev_ebitda

    return {"pe": pe_values, "pb": pb_values, "ev_ebitda": ev_ebitda_values}


async def compute_universe_valuation_values(session: AsyncSession, as_of: datetime) -> UniverseValuation:
    """Public entry point for callers that want a fresh, uncached universe scan.

    Used by `apps/worker/jobs.py::compute_all_scores_job` to compute the
    valuation peer population exactly once per batch run (see the
    module-level comment above `_VALUATION_CACHE_TTL`). On-demand callers
    should use `get_cached_universe_valuation_values` instead.
    """
    return await _universe_valuation_values(session, as_of)


async def get_cached_universe_valuation_values(session: AsyncSession, as_of: datetime) -> UniverseValuation:
    """TTL-cached wrapper around `_universe_valuation_values` for the on-demand path.

    Process-local, module-level cache (not Redis - this project has no
    existing cross-process cache layer for scoring, and a single API
    process's in-memory cache is sufficient to collapse N on-demand
    `/score` calls within `_VALUATION_CACHE_TTL` into one universe scan).
    Not used by the batch job (`compute_all_scores_job`), which computes
    the universe exactly once per run and passes it explicitly - see the
    module-level comment above `_VALUATION_CACHE_TTL`.
    """
    cached_at: datetime | None = _valuation_cache["computed_at"]
    if cached_at is not None:
        age = as_of - cached_at
        # Guard against a non-monotonic `as_of` (e.g. test suites that pass
        # a fixed historical timestamp) being misread as "fresh" - a
        # negative age must never be treated as within the TTL window.
        if timedelta(0) <= age < _VALUATION_CACHE_TTL:
            return _valuation_cache["values"]

    values = await _universe_valuation_values(session, as_of)
    _valuation_cache["computed_at"] = as_of
    _valuation_cache["values"] = values
    return values


async def score_valuation(
    session: AsyncSession,
    instrument: Instrument,
    latest_snapshot: FundamentalSnapshot | None,
    full_df: pd.DataFrame,
    evidence_builder: EvidenceBuilder,
    now: datetime,
    precomputed_universe_valuation: UniverseValuation | None = None,
) -> tuple[ComponentResult, SignalPairs]:
    """Score the valuation component.

    `precomputed_universe_valuation`: pass this when the caller already
    computed the universe-wide valuation peer population once for the
    whole batch (SPEC.md section 81 rule 24 - avoid recomputing the same
    thing N times) - see `compute_all_scores_job` in `apps/worker/jobs.py`.
    When omitted (the on-demand `/score` endpoint's call path),
    `get_cached_universe_valuation_values` is used instead, which still
    avoids a full rescan on every single request via a short-TTL cache.
    Both paths call the exact same `_universe_valuation_values` and
    `_percentile_cheaper` functions - only *when*/*how often* that scan
    runs differs, never the methodology (see
    tests/unit/scoring/test_valuation_cache.py).
    """
    if latest_snapshot is None or full_df.empty:
        return _unavailable("valuation", "no_fundamental_data"), []

    close = float(full_df["adjusted_close"].iloc[-1])
    val = compute_valuation_metrics(
        close_price=close,
        period_end=latest_snapshot.period_end,
        as_of=now.date(),
        eps=_f(latest_snapshot.eps),
        equity=_f(latest_snapshot.equity),
        shares_outstanding=_f(latest_snapshot.shares_outstanding),
        revenue=_f(latest_snapshot.revenue),
        ebitda=_f(latest_snapshot.ebitda),
        total_debt=_f(latest_snapshot.total_debt),
        cash=_f(latest_snapshot.cash),
        free_cash_flow=_f(latest_snapshot.free_cash_flow),
        dividend_yield=_f(latest_snapshot.dividend_yield),
    )

    universe = (
        precomputed_universe_valuation
        if precomputed_universe_valuation is not None
        else await get_cached_universe_valuation_values(session, now)
    )
    percentiles: dict[str, float] = {}
    if val.pe is not None:
        p = _percentile_cheaper(val.pe, universe["pe"])
        if p is not None:
            percentiles["pe_percentile"] = p
    if val.pb is not None:
        p = _percentile_cheaper(val.pb, universe["pb"])
        if p is not None:
            percentiles["pb_percentile"] = p
    if val.ev_ebitda is not None:
        p = _percentile_cheaper(val.ev_ebitda, universe["ev_ebitda"])
        if p is not None:
            percentiles["ev_ebitda_percentile"] = p

    if not percentiles:
        return _unavailable("valuation", "valuation_metrics_unavailable"), []

    score, signals = score_valuation_points(percentiles)
    pairs = _emit_evidence(
        evidence_builder,
        evidence_type="valuation",
        signals=signals,
        source_name="valuation_engine",
        observed_at=now,
        source_timestamp=latest_snapshot.source_timestamp,
        interpretation_suffix=f" (valuation_universe_size={len(universe.get('pe', {}))})",
    )
    age_days = fundamentals_data_age_days(latest_snapshot.period_end, now.date())
    freshness = fundamentals_freshness_score(age_days)
    result = ComponentResult(
        name="valuation",
        weight=COMPONENT_WEIGHTS["valuation"],
        score=score,
        available=True,
        reason=None,
        freshness=freshness,
        evidence_ids=tuple(str(eid) for _, eid in pairs),
    )
    return result, pairs


async def score_sector_relative_strength(
    session: AsyncSession, instrument: Instrument, evidence_builder: EvidenceBuilder, now: datetime
) -> tuple[ComponentResult, SignalPairs]:
    rs_result = await compute_relative_strength(session, instrument)
    horizon_metric = rs_result.metrics.get("3M")
    if horizon_metric is None or horizon_metric.relative_strength_pct is None:
        reason = horizon_metric.reason if horizon_metric is not None else "insufficient_peer_universe"
        return _unavailable("sector_relative_strength", reason or "insufficient_peer_universe"), []

    score, signal = score_sector_relative_strength_points(horizon_metric.relative_strength_pct)
    pairs = _emit_evidence(
        evidence_builder,
        evidence_type="sector_relative_strength",
        signals=[signal],
        source_name="relative_strength_engine",
        observed_at=now,
        source_timestamp=now,
        interpretation_suffix=f" (sector={rs_result.sector}, peer_universe=seeded_sector_peers)",
    )
    result = ComponentResult(
        name="sector_relative_strength",
        weight=COMPONENT_WEIGHTS["sector_relative_strength"],
        score=score,
        available=True,
        reason=None,
        freshness=100.0,
        evidence_ids=tuple(str(eid) for _, eid in pairs),
    )
    return result, pairs


async def score_market_regime(
    session: AsyncSession, evidence_builder: EvidenceBuilder, now: datetime
) -> tuple[ComponentResult, SignalPairs]:
    regime_row = await get_latest_regime(session)
    if regime_row is None:
        return _unavailable("market_regime", "market_regime_not_computed"), []

    signal = market_regime_signal(regime_row.regime.value, regime_row.date.isoformat())
    score = clamp_score(50.0 + signal.delta)
    age_days = (now.date() - regime_row.date).days
    freshness = max(0.0, 100.0 - age_days * REGIME_FRESHNESS_DECAY_PER_DAY)

    regime_timestamp = datetime.combine(regime_row.date, time.min, tzinfo=UTC)
    pairs = _emit_evidence(
        evidence_builder,
        evidence_type="market_regime",
        signals=[signal],
        source_name="regime_engine",
        observed_at=now,
        source_timestamp=regime_timestamp,
    )
    result = ComponentResult(
        name="market_regime",
        weight=COMPONENT_WEIGHTS["market_regime"],
        score=score,
        available=True,
        reason=None,
        freshness=freshness,
        evidence_ids=tuple(str(eid) for _, eid in pairs),
    )
    return result, pairs



