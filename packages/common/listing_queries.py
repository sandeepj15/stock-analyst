"""Shared "latest row per instrument" subquery builders.

Factored out of `apps/api/routes/instruments.py` (UI/UX "Market Pulse"
dashboard task) so the new `GET /api/v1/market/score-distribution` and
`GET /api/v1/market/sectors` endpoints (`apps/api/routes/market.py`)
reuse the exact same efficient, single-grouped-query/window-function SQL
instead of re-deriving it - every one of these helpers is already proven
at the ~750-instrument scale by the instrument listing endpoint, and any
drift between two hand-written copies of "latest row per group" logic
would be its own bug class.

Every function here returns a bare `Subquery`/column `expression` for
the caller to `outerjoin`/`select`/`group_by` itself - this module has
no opinion about which instruments are in scope (exchange/active_only
filtering stays the caller's responsibility, same as before this
refactor).
"""
from __future__ import annotations

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.sql.selectable import Subquery

from packages.market_data.models import OHLCVDaily
from packages.momentum.models import MomentumScan
from packages.momentum.scanner import DEFAULT_SMA200_TREND_LOOKBACK_DAYS
from packages.scoring.bands import SCORE_BAND_THRESHOLDS, VERY_STRONG_LABEL
from packages.scoring.models import ResearchScore


def latest_research_score_subquery() -> Subquery:
    """One row per instrument: its most recently *persisted* `research_scores` row.

    Standard "rank every row for an instrument_id by computed_at
    descending, keep rank 1" pattern - cheaper than a correlated
    subquery per instrument, never N+1.
    """
    ranked = (
        select(
            ResearchScore.instrument_id.label("instrument_id"),
            ResearchScore.score.label("score"),
            ResearchScore.confidence.label("confidence"),
            func.row_number()
            .over(partition_by=ResearchScore.instrument_id, order_by=ResearchScore.computed_at.desc())
            .label("rn"),
        )
    ).subquery()
    return select(ranked.c.instrument_id, ranked.c.score, ranked.c.confidence).where(ranked.c.rn == 1).subquery()


def latest_momentum_subquery() -> Subquery:
    """One row per instrument: its most recently persisted `momentum_scans`
    row at the default SMA200-trend lookback (see
    `apps/api/routes/instruments.py`'s docstring for why the lookback is
    pinned rather than "whatever a user queried most recently")."""
    ranked = (
        select(
            MomentumScan.instrument_id.label("instrument_id"),
            MomentumScan.passed.label("passed"),
            MomentumScan.distance_from_52w_high_pct.label("distance_from_52w_high_pct"),
            func.row_number()
            .over(partition_by=MomentumScan.instrument_id, order_by=MomentumScan.computed_at.desc())
            .label("rn"),
        ).where(MomentumScan.sma200_trend_lookback_days == DEFAULT_SMA200_TREND_LOOKBACK_DAYS)
    ).subquery()
    return (
        select(ranked.c.instrument_id, ranked.c.passed, ranked.c.distance_from_52w_high_pct)
        .where(ranked.c.rn == 1)
        .subquery()
    )


def latest_price_change_subquery() -> Subquery:
    """One row per instrument: latest persisted close + day-over-day % change.

    A single window-function scan (never an N+1 per-instrument lookup -
    SPEC.md section 59, the same lesson already learned for valuation/
    RS-rank percentiles elsewhere in this codebase). `row_number` picks
    the latest bar per instrument; `lead(..., 1)` over the same
    DESC-ordered partition reads the *next* row in that ordering - i.e.
    the second-most-recent bar (yesterday's close) - directly alongside
    it, so both closes come out of one scan per instrument, not two.
    `day_change_pct` is `NULL` (never a crash or a fabricated 0) whenever
    an instrument has fewer than two OHLCV bars ever ingested.
    """
    ranked = (
        select(
            OHLCVDaily.instrument_id.label("instrument_id"),
            OHLCVDaily.close.label("close"),
            OHLCVDaily.adjusted_close.label("adjusted_close"),
            func.row_number()
            .over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc())
            .label("rn"),
            func.lead(OHLCVDaily.adjusted_close, 1)
            .over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc())
            .label("prev_adj_close"),
        )
    ).subquery()
    day_change_expr = case(
        (
            and_(ranked.c.prev_adj_close.isnot(None), ranked.c.prev_adj_close != 0),
            (ranked.c.adjusted_close - ranked.c.prev_adj_close) / ranked.c.prev_adj_close * 100.0,
        ),
        else_=None,
    )
    return (
        select(ranked.c.instrument_id, ranked.c.close.label("latest_close"), day_change_expr.label("day_change_pct"))
        .where(ranked.c.rn == 1)
        .subquery()
    )


def score_band_case(score_column: ColumnElement) -> ColumnElement:
    """SQL `CASE` expression mirroring `packages.scoring.bands.score_band` exactly.

    Built directly from `SCORE_BAND_THRESHOLDS` (never a hand-duplicated
    copy of the band cutoffs) so a grouped SQL query's band buckets can
    never drift from the single Python source of truth every other band
    label in this codebase already uses. `NULL` in -> `NULL` out (an
    unscored instrument is never counted into "Very Weak" or any other
    band - SPEC.md section 81 rule 8).
    """
    # `NULL < threshold` evaluates to SQL NULL (neither true nor false)
    # in Postgres, which would otherwise silently fall through to the
    # `else_` branch below - the explicit `IS NULL` check first keeps an
    # unscored instrument's band genuinely `NULL`, never miscounted into
    # "Very Strong".
    whens: list[tuple[ColumnElement[bool], str | None]] = [(score_column.is_(None), None)]
    whens += [(score_column < threshold, label) for threshold, label in SCORE_BAND_THRESHOLDS]
    return case(*whens, else_=VERY_STRONG_LABEL)


def latest_fundamental_growth_subquery() -> Subquery:
    """One row per instrument: latest Q revenue and PAT YoY growth.
    
    Comparisons are made between the latest quarter and the quarter ~365 days prior.
    """
    from packages.fundamentals.models import FundamentalSnapshot

    fs = FundamentalSnapshot
    latest = (
        select(
            fs.instrument_id.label("instrument_id"),
            fs.period_end.label("period_end"),
            fs.revenue.label("revenue"),
            fs.pat.label("pat"),
            func.row_number()
            .over(partition_by=fs.instrument_id, order_by=fs.period_end.desc())
            .label("rn"),
        )
        .where(fs.period_type == "Q")
    ).subquery()
    
    latest_only = select(latest).where(latest.c.rn == 1).subquery("latest_only")
    
    prev = (
        select(
            fs.instrument_id,
            fs.revenue.label("prev_revenue"),
            fs.pat.label("prev_pat"),
            func.row_number()
            .over(
                partition_by=fs.instrument_id,
                order_by=func.abs(latest_only.c.period_end - fs.period_end - 365)
            )
            .label("rn_prev")
        )
        .select_from(latest_only)
        .join(fs, and_(
            fs.instrument_id == latest_only.c.instrument_id,
            fs.period_type == "Q",
            fs.period_end <= latest_only.c.period_end - 340,
            fs.period_end >= latest_only.c.period_end - 390,
        ))
    ).subquery("prev")
    
    prev_only = select(prev).where(prev.c.rn_prev == 1).subquery("prev_only")
    
    rev_growth_expr = case(
        (
            and_(prev_only.c.prev_revenue.isnot(None), prev_only.c.prev_revenue != 0),
            (latest_only.c.revenue - prev_only.c.prev_revenue) / func.abs(prev_only.c.prev_revenue),
        ),
        else_=None,
    )
    pat_growth_expr = case(
        (
            and_(prev_only.c.prev_pat.isnot(None), prev_only.c.prev_pat != 0),
            (latest_only.c.pat - prev_only.c.prev_pat) / func.abs(prev_only.c.prev_pat),
        ),
        else_=None,
    )
    
    return (
        select(
            latest_only.c.instrument_id,
            rev_growth_expr.label("revenue_growth_yoy"),
            pat_growth_expr.label("pat_growth_yoy")
        )
        .select_from(latest_only)
        .outerjoin(prev_only, prev_only.c.instrument_id == latest_only.c.instrument_id)
        .subquery()
    )
