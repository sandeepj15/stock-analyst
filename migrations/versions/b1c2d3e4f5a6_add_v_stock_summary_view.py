"""add_v_stock_summary_view

Revision ID: b1c2d3e4f5a6
Revises: adf2bb95b124
Create Date: 2026-10-13 17:35:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'adf2bb95b124'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VIEW_SQL = """
DROP VIEW IF EXISTS v_stock_summary;
CREATE VIEW v_stock_summary AS
SELECT 
    i.symbol,
    i.company_name,
    i.sector,
    i.industry,
    i.active,
    ls.score AS research_score,
    ls.confidence AS research_confidence,
    lm.passed AS stage2_passed,
    lm.rs_rank AS momentum_rs_rank,
    lm.distance_from_52w_high_pct,
    COALESCE(lv.is_vcp_setup, false) AS is_vcp_setup,
    lp.close AS current_price,
    ROUND(lpc.day_change_pct::numeric, 2) AS day_change_pct,
    ROUND(lpc.return_1m_pct::numeric, 2) AS return_1m_pct,
    ROUND(lpc.return_1y_pct::numeric, 2) AS return_1y_pct,
    ROUND((lfg.revenue_growth_yoy * 100)::numeric, 1) AS rev_growth_yoy_pct,
    ROUND((lfg.pat_growth_yoy * 100)::numeric, 1) AS pat_growth_yoy_pct,
    ROUND(((lmf.ml_forecast_close - lp.close) / NULLIF(lp.close, 0) * 100)::numeric, 2) AS ml_forecast_5d_pct,
    ROUND((lp.close / NULLIF(lf.eps, 0))::numeric, 2) AS pe_ratio,
    lf.eps,
    ROUND((lf.shares_outstanding * lp.close / 10000000)::numeric, 1) AS market_cap_cr,
    lf.revenue AS annual_revenue,
    lf.pat AS annual_pat,
    ROUND((lf.pat / NULLIF(lf.equity, 0) * 100)::numeric, 2) AS roe_pct,
    ROUND((lf.ebit / NULLIF(lf.equity + lf.total_debt, 0) * 100)::numeric, 2) AS roce_pct,
    ROUND((lf.total_debt / NULLIF(lf.equity, 0))::numeric, 2) AS debt_to_equity,
    ae.target_mean_price,
    ROUND(((ae.target_mean_price - lp.close) / NULLIF(lp.close, 0) * 100)::numeric, 1) AS analyst_upside_pct,
    ae.recommendation_key AS analyst_rating
FROM instruments i
LEFT JOIN LATERAL (
    SELECT score, confidence 
    FROM research_scores 
    WHERE instrument_id = i.id 
    ORDER BY computed_at DESC 
    LIMIT 1
) ls ON TRUE
LEFT JOIN LATERAL (
    SELECT passed, rs_rank, distance_from_52w_high_pct 
    FROM momentum_scans 
    WHERE instrument_id = i.id 
    ORDER BY scan_date DESC 
    LIMIT 1
) lm ON TRUE
LEFT JOIN LATERAL (
    SELECT is_vcp_setup
    FROM vcp_scans
    WHERE instrument_id = i.id
    ORDER BY computed_at DESC
    LIMIT 1
) lv ON TRUE
LEFT JOIN LATERAL (
    SELECT close 
    FROM ohlcv_daily 
    WHERE instrument_id = i.id 
    ORDER BY trading_date DESC 
    LIMIT 1
) lp ON TRUE
LEFT JOIN LATERAL (
    SELECT 
        (c.close - p1.close) / NULLIF(p1.close, 0) * 100.0 AS day_change_pct,
        (c.close - p21.close) / NULLIF(p21.close, 0) * 100.0 AS return_1m_pct,
        (c.close - p252.close) / NULLIF(p252.close, 0) * 100.0 AS return_1y_pct
    FROM (
        SELECT close, trading_date FROM ohlcv_daily WHERE instrument_id = i.id ORDER BY trading_date DESC LIMIT 1
    ) c
    LEFT JOIN LATERAL (
        SELECT close FROM ohlcv_daily WHERE instrument_id = i.id ORDER BY trading_date DESC OFFSET 1 LIMIT 1
    ) p1 ON TRUE
    LEFT JOIN LATERAL (
        SELECT close FROM ohlcv_daily WHERE instrument_id = i.id ORDER BY trading_date DESC OFFSET 21 LIMIT 1
    ) p21 ON TRUE
    LEFT JOIN LATERAL (
        SELECT close FROM ohlcv_daily WHERE instrument_id = i.id ORDER BY trading_date DESC OFFSET 252 LIMIT 1
    ) p252 ON TRUE
) lpc ON TRUE
LEFT JOIN LATERAL (
    SELECT 
        (curr.revenue - prev.revenue) / NULLIF(prev.revenue, 0) AS revenue_growth_yoy,
        (curr.pat - prev.pat) / NULLIF(ABS(prev.pat), 0) AS pat_growth_yoy
    FROM (
        SELECT revenue, pat, period_end 
        FROM fundamental_snapshots 
        WHERE instrument_id = i.id AND period_type = 'Q' 
        ORDER BY period_end DESC LIMIT 1
    ) curr
    LEFT JOIN LATERAL (
        SELECT revenue, pat 
        FROM fundamental_snapshots 
        WHERE instrument_id = i.id AND period_type = 'Q' 
          AND period_end <= curr.period_end - 340 
          AND period_end >= curr.period_end - 390
        ORDER BY period_end DESC LIMIT 1
    ) prev ON TRUE
) lfg ON TRUE
LEFT JOIN LATERAL (
    SELECT ((trajectory->-1)->>'close')::numeric AS ml_forecast_close
    FROM ml_forecasts
    WHERE instrument_id = i.id
    ORDER BY created_at DESC LIMIT 1
) lmf ON TRUE
LEFT JOIN LATERAL (
    SELECT eps, pat, revenue, equity, total_debt, ebit, shares_outstanding 
    FROM fundamental_snapshots 
    WHERE instrument_id = i.id AND period_type != 'Q'
    ORDER BY period_end DESC 
    LIMIT 1
) lf ON TRUE
LEFT JOIN LATERAL (
    SELECT target_mean_price, recommendation_key 
    FROM analyst_estimates 
    WHERE instrument_id = i.id 
    ORDER BY ingested_at DESC 
    LIMIT 1
) ae ON TRUE
WHERE i.active = true;
"""


def upgrade() -> None:
    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_stock_summary;")
