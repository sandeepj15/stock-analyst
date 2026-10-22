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

from sqlalchemy import ColumnElement, and_, case, func, select, Numeric, text
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
    return (
        select(
            ResearchScore.instrument_id.label("instrument_id"),
            ResearchScore.score.label("score"),
            ResearchScore.confidence.label("confidence"),
            ResearchScore.components.label("components"),
            ResearchScore.computed_at.label("computed_at"),
        )
        .distinct(ResearchScore.instrument_id)
        .order_by(ResearchScore.instrument_id, ResearchScore.computed_at.desc())
        .subquery()
    )


def latest_momentum_subquery() -> Subquery:
    """One row per instrument: its most recently persisted `momentum_scans`
    row at the default SMA200-trend lookback (see
    `apps/api/routes/instruments.py`'s docstring for why the lookback is
    pinned rather than "whatever a user queried most recently")."""
    return (
        select(
            MomentumScan.instrument_id.label("instrument_id"),
            MomentumScan.passed.label("passed"),
            MomentumScan.distance_from_52w_high_pct.label("distance_from_52w_high_pct"),
            MomentumScan.computed_at.label("computed_at"),
        )
        .where(MomentumScan.sma200_trend_lookback_days == DEFAULT_SMA200_TREND_LOOKBACK_DAYS)
        .distinct(MomentumScan.instrument_id)
        .order_by(MomentumScan.instrument_id, MomentumScan.computed_at.desc())
        .subquery()
    )


def latest_price_change_subquery() -> Subquery:
    """One row per instrument: latest persisted close + return % for various timeframes.

    A single window-function scan (never an N+1 per-instrument lookup). 
    `row_number` picks the latest bar per instrument; `lead` reads offsets for
    1D (1), 1W (5), 1M (21), 3M (63), 6M (126), and 1Y (252) trading days.
    """
    ranked = (
        select(
            OHLCVDaily.instrument_id.label("instrument_id"),
            OHLCVDaily.close.label("close"),
            OHLCVDaily.adjusted_close.label("adjusted_close"),
            func.row_number()
            .over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc())
            .label("rn"),
            func.lead(OHLCVDaily.adjusted_close, 1).over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc()).label("prev_1d"),
            func.lead(OHLCVDaily.adjusted_close, 5).over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc()).label("prev_1w"),
            func.lead(OHLCVDaily.adjusted_close, 21).over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc()).label("prev_1m"),
            func.lead(OHLCVDaily.adjusted_close, 63).over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc()).label("prev_3m"),
            func.lead(OHLCVDaily.adjusted_close, 126).over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc()).label("prev_6m"),
            func.lead(OHLCVDaily.adjusted_close, 252).over(partition_by=OHLCVDaily.instrument_id, order_by=OHLCVDaily.trading_date.desc()).label("prev_1y"),
        )
        .where(OHLCVDaily.trading_date >= text("CURRENT_DATE - INTERVAL '18 months'"))
    ).subquery()
    
    def pct_expr(prev_col):
        return case(
            (
                and_(prev_col.isnot(None), prev_col != 0),
                (ranked.c.adjusted_close - prev_col) / prev_col * 100.0,
            ),
            else_=None,
        )

    return (
        select(
            ranked.c.instrument_id, 
            ranked.c.close.label("latest_close"), 
            pct_expr(ranked.c.prev_1d).label("day_change_pct"),
            pct_expr(ranked.c.prev_1w).label("return_1w_pct"),
            pct_expr(ranked.c.prev_1m).label("return_1m_pct"),
            pct_expr(ranked.c.prev_3m).label("return_3m_pct"),
            pct_expr(ranked.c.prev_6m).label("return_6m_pct"),
            pct_expr(ranked.c.prev_1y).label("return_1y_pct"),
        )
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

def latest_ml_forecast_subquery() -> Subquery:
    from packages.common.models import MLForecast
    
    # Extract the forecasted close from the latest JSON trajectory and cast to Numeric
    forecast_close = func.cast(MLForecast.trajectory.op('->')(-1).op('->>')('close'), Numeric)

    return (
        select(
            MLForecast.instrument_id.label("instrument_id"),
            forecast_close.label("ml_forecast_close"),
            MLForecast.created_at.label("created_at"),
        )
        .distinct(MLForecast.instrument_id)
        .order_by(MLForecast.instrument_id, MLForecast.created_at.desc())
        .subquery()
    )


def latest_vcp_subquery() -> Subquery:
    from packages.strategy.models import VcpScan
    return (
        select(
            VcpScan.instrument_id.label("instrument_id"),
            VcpScan.is_vcp_setup.label("is_vcp_setup"),
            VcpScan.computed_at.label("computed_at"),
        )
        .distinct(VcpScan.instrument_id)
        .order_by(VcpScan.instrument_id, VcpScan.computed_at.desc())
        .subquery()
    )


def latest_institutional_holdings_subquery() -> Subquery:
    """One row per instrument: latest FII, DII, and promoter holdings and QoQ changes."""
    from packages.fundamentals.models import InstitutionalHolding
    return (
        select(
            InstitutionalHolding.instrument_id.label("instrument_id"),
            InstitutionalHolding.latest_quarter.label("latest_quarter"),
            InstitutionalHolding.fii_current.label("fii_current"),
            InstitutionalHolding.fii_qoq_change.label("fii_qoq_change"),
            InstitutionalHolding.dii_current.label("dii_current"),
            InstitutionalHolding.dii_qoq_change.label("dii_qoq_change"),
            InstitutionalHolding.promoter_current.label("promoter_current"),
            InstitutionalHolding.promoter_qoq_change.label("promoter_qoq_change"),
            InstitutionalHolding.public_current.label("public_current"),
        )
        .subquery()
    )

