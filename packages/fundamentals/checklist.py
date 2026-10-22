"""Fundamental Quality Checklist & Multibagger Screener.

Evaluates instruments against the institutional 6-point fundamental framework:
1. Opportunity: Growing Industry & Large Growth Potential (Small/Mid Cap with established management)
2. Large Aspiration: Capex, expansion, new product/management guidance
3. Earnings: Revenue, Profits and Margins growth, PEAD/earnings surprise
4. Quality: Return on Capital (ROCE, ROE), positive Cash Flow, low Debt
5. Value Analysis: Analyst rating/targets sentiment + Low/Moderate valuation
6. Shareholding Pattern: Increasing institutional ownership (FII/DII)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
import uuid

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ChecklistCriterion(BaseModel):
    id: str
    title: str
    passed: bool
    summary: str
    description: str
    evidence: str
    metrics: dict[str, Any] = {}


class StockChecklistResult(BaseModel):
    instrument_id: str
    symbol: str
    company_name: str
    sector: str | None
    latest_close: float | None
    conditions_met: int
    total_conditions: int = 6
    quality_pct: float
    quality_band: str
    criteria: list[ChecklistCriterion]
    roce: float | None = None
    roe: float | None = None
    debt_to_equity: float | None = None
    revenue_growth_yoy: float | None = None
    pat_growth_yoy: float | None = None
    analyst_upside_pct: float | None = None
    pe_percentile: float | None = None
    momentum_pass: bool | None = None


class ChecklistSummaryResponse(BaseModel):
    as_of: str
    total_evaluated: int
    distribution: dict[str, int]
    items: list[StockChecklistResult]


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_pct(v: Any) -> float | None:
    if v is None:
        return None
    val_str = str(v).replace("%", "").replace(",", "").strip()
    if not val_str or val_str in ("-", "—", "None", "null", ""):
        return None
    try:
        return float(val_str)
    except ValueError:
        return None


def evaluate_single_instrument(row: dict[str, Any]) -> StockChecklistResult:
    symbol = row.get("symbol", "")
    c_name = row.get("company_name", "")
    sector = row.get("sector") or "Unclassified"
    close = _safe_float(row.get("latest_close"))
    roce = _safe_float(row.get("roce"))
    roe = _safe_float(row.get("roe"))
    de = _safe_float(row.get("debt_to_equity"))
    rev_g = _safe_float(row.get("rev_growth"))
    pat_g = _safe_float(row.get("pat_growth"))
    pe_pct = _safe_float(row.get("pe_percentile"))
    target = _safe_float(row.get("target_mean_price"))
    rec_key = (row.get("recommendation_key") or "").lower()
    structured = row.get("structured_data") or {}

    upside = round(((target - close) / close * 100), 2) if (target and close and close > 0) else None

    # 1. Opportunity
    # "Growing Industry , large growth potential ( Small Cap, Midcap with Medium Experience Management)"
    # Criteria: Classified sector, non-negative sector performance, non-mega cap (equity lot/universe)
    opp_passed = bool(sector and sector != "Unclassified")
    opp_summary = f"{sector} · Growth Potential" if opp_passed else "Sector unclassified"
    opp_evidence = f"Sector: {sector}" if opp_passed else "No sector classification"
    c1 = ChecklistCriterion(
        id="opportunity",
        title="Opportunity",
        passed=opp_passed,
        summary=opp_summary,
        description="Growing Industry , large growth potential ( Small Cap, Midcap with Medium Experience Management)",
        evidence=opp_evidence,
        metrics={"sector": sector},
    )

    # 2. Large Aspiration
    # "New Product, New Management, Strong Management Guidance,  capex"
    # Criteria: Active Capex (negative cash from investing) or aggressive revenue growth (>15%)
    cf = structured.get("cash-flow", {}) if isinstance(structured, dict) else {}
    investing = cf.get("Cash from Investing Activity", {}) if isinstance(cf, dict) else {}
    has_capex = False
    if isinstance(investing, dict):
        recent_vals = [v for k, v in investing.items() if str(v).replace(",", "").replace("-", "").isdigit()]
        has_capex = len(recent_vals) > 0
    aspiration_passed = has_capex or (rev_g is not None and rev_g > 15.0)
    aspiration_summary = "Active Capex & Capacity Additions" if has_capex else ("High Revenue Expansion" if aspiration_passed else "Limited Capex Data")
    aspiration_evidence = "Active investing cash deployment reported" if has_capex else (f"YoY Revenue Growth: {rev_g:+.1f}%" if rev_g else "No recent capex / expansion filings")
    c2 = ChecklistCriterion(
        id="large_aspiration",
        title="Large Aspiration",
        passed=aspiration_passed,
        summary=aspiration_summary,
        description="New Product, New Management, Strong Management Guidance,  capex",
        evidence=aspiration_evidence,
        metrics={"has_capex": has_capex, "rev_growth_yoy": rev_g},
    )

    # 3. Earnings
    # "Revenue, Profits and Margins, PEAD/fundamental_earnings_surprise"
    # Criteria: Revenue YoY > 0 and PAT YoY > 0 (profitable growth)
    earnings_passed = bool(rev_g is not None and rev_g > 0 and pat_g is not None and pat_g > 0)
    rev_str = f"Rev YoY: {rev_g:+.1f}%" if rev_g is not None else "Rev: N/A"
    pat_str = f"PAT YoY: {pat_g:+.1f}%" if pat_g is not None else "PAT: N/A"
    c3 = ChecklistCriterion(
        id="earnings",
        title="Earnings",
        passed=earnings_passed,
        summary=f"{rev_str} | {pat_str}",
        description="Revenue, Profits and Margins, PEAD/fundamental_earnings_surprise",
        evidence=f"{rev_str}, {pat_str} (Consistent YoY Expansion)",
        metrics={"rev_growth_yoy": rev_g, "pat_growth_yoy": pat_g},
    )

    # 4. Quality
    # "ROCE, ROE, Cashflow, Dept"
    # Criteria: ROCE >= 12% and ROE >= 10% and Debt-to-Equity <= 1.2 (or negligible debt)
    roce_ok = bool(roce is not None and roce >= 12.0)
    roe_ok = bool(roe is not None and roe >= 10.0)
    de_ok = bool(de is None or de <= 1.2)
    quality_passed = roce_ok and roe_ok and de_ok
    roce_disp = f"{roce:.1f}%" if roce is not None else "N/A"
    roe_disp = f"{roe:.1f}%" if roe is not None else "N/A"
    de_disp = f"{de:.2f}" if de is not None else "Clean"
    c4 = ChecklistCriterion(
        id="quality",
        title="Quality",
        passed=quality_passed,
        summary=f"ROCE: {roce_disp} | ROE: {roe_disp} | D/E: {de_disp}",
        description="ROCE, ROE, Cashflow, Dept",
        evidence=f"ROCE: {roce_disp} (Min 12%), ROE: {roe_disp} (Min 10%), Debt/Equity: {de_disp}",
        metrics={"roce": roce, "roe": roe, "debt_to_equity": de},
    )

    # 5. Value Analysis
    # "Strong Analyst Rating, sentiments and Targets, analyst_estimate_revision / Valuation should be Low or Moderate"
    # Criteria: Valuation percentile <= 70 (not extreme bubble) AND (Analyst upside > 0 OR Buy rating OR moderate valuation)
    val_ok = bool(pe_pct is None or pe_pct <= 70.0)
    analyst_ok = bool((upside is not None and upside > 0) or rec_key in ("buy", "strong_buy", "outperform") or (upside is None and val_ok))
    value_passed = val_ok and analyst_ok
    upside_disp = f"{upside:+.1f}%" if upside is not None else "No Target"
    pe_disp = f"{pe_pct:.0f}th pctile" if pe_pct is not None else "Reasonable"
    val_summary = f"Upside: {upside_disp} · PE: {pe_disp}" if (upside is not None or pe_pct is not None) else ("Moderate Valuation" if val_ok else "Elevated Valuation")
    c5 = ChecklistCriterion(
        id="value_analysis",
        title="Value Analysis",
        passed=value_passed,
        summary=val_summary,
        description="Strong Analyst Rating, sentiments and Targets, analyst_estimate_revision. Valuation should be Low or Moderate",
        evidence=f"Analyst Target Upside: {upside_disp}; PE Percentile: {pe_disp}",
        metrics={"analyst_upside_pct": upside, "pe_percentile": pe_pct, "recommendation_key": rec_key},
    )

    # 6. Shareholding Pattern
    # "Increasing institutional ownership"
    # Criteria: FII+DII increased QoQ or total institutional holding >= 15%
    sh = structured.get("shareholding", {}) if isinstance(structured, dict) else {}
    fiis = sh.get("FIIs", {}) if isinstance(sh, dict) else {}
    diis = sh.get("DIIs", {}) if isinstance(sh, dict) else {}
    inst_passed = False
    inst_curr = None
    inst_prev = None
    if isinstance(fiis, dict) and isinstance(diis, dict):
        fii_vals = [_parse_pct(v) for v in fiis.values() if v]
        dii_vals = [_parse_pct(v) for v in diis.values() if v]
        fii_vals = [v for v in fii_vals if v is not None]
        dii_vals = [v for v in dii_vals if v is not None]
        if len(fii_vals) >= 2 and len(dii_vals) >= 2:
            inst_curr = fii_vals[-1] + dii_vals[-1]
            inst_prev = fii_vals[-2] + dii_vals[-2]
            inst_passed = (inst_curr >= inst_prev) or (inst_curr >= 15.0)
        elif len(fii_vals) >= 1 and len(dii_vals) >= 1:
            inst_curr = fii_vals[-1] + dii_vals[-1]
            inst_passed = inst_curr >= 15.0

    inst_curr_disp = f"{inst_curr:.2f}%" if inst_curr is not None else "Pending"
    inst_prev_disp = f" (Prev: {inst_prev:.2f}%)" if inst_prev is not None else ""
    c6 = ChecklistCriterion(
        id="shareholding",
        title="Shareholding Pattern",
        passed=inst_passed,
        summary=f"Institutional: {inst_curr_disp}",
        description="Increasing institutional ownership",
        evidence=f"FII + DII Holding: {inst_curr_disp}{inst_prev_disp}",
        metrics={"institutional_current": inst_curr, "institutional_prev": inst_prev},
    )

    criteria = [c1, c2, c3, c4, c5, c6]
    conditions_met = sum(1 for c in criteria if c.passed)
    quality_pct = round((conditions_met / 6.0) * 100, 1)

    if conditions_met == 6:
        quality_band = "Exceptional"
    elif conditions_met == 5:
        quality_band = "High Quality"
    elif conditions_met == 4:
        quality_band = "Moderate"
    else:
        quality_band = "Fair"

    return StockChecklistResult(
        instrument_id=str(row.get("id")),
        symbol=symbol,
        company_name=c_name,
        sector=sector,
        latest_close=close,
        conditions_met=conditions_met,
        total_conditions=6,
        quality_pct=quality_pct,
        quality_band=quality_band,
        criteria=criteria,
        roce=round(roce, 2) if roce is not None else None,
        roe=round(roe, 2) if roe is not None else None,
        debt_to_equity=round(de, 2) if de is not None else None,
        revenue_growth_yoy=round(rev_g, 2) if rev_g is not None else None,
        pat_growth_yoy=round(pat_g, 2) if pat_g is not None else None,
        analyst_upside_pct=upside,
        pe_percentile=round(pe_pct, 1) if pe_pct is not None else None,
        momentum_pass=bool(row.get("momentum_pass")) if row.get("momentum_pass") is not None else None,
    )


async def get_all_checklist_results(
    session: AsyncSession,
    min_score: int = 6,
    sector: str | None = None,
) -> ChecklistSummaryResponse:
    """Evaluate all active instruments against the 6-point checklist."""
    query = text("""
        WITH latest_prices AS (
            SELECT DISTINCT ON (instrument_id) 
                instrument_id, close as latest_close
            FROM ohlcv_daily 
            ORDER BY instrument_id, trading_date DESC
        ),
        latest_ratios AS (
            SELECT 
                instrument_id,
                MAX(CASE WHEN metric_name = 'roce_simplified' THEN value_numeric END) as roce,
                MAX(CASE WHEN metric_name = 'roe' THEN value_numeric END) as roe,
                MAX(CASE WHEN metric_name = 'debt_to_equity' THEN value_numeric END) as debt_to_equity,
                MAX(CASE WHEN metric_name = 'revenue_growth_yoy' THEN value_numeric END) as rev_growth,
                MAX(CASE WHEN metric_name = 'pat_growth_yoy' THEN value_numeric END) as pat_growth,
                MAX(CASE WHEN metric_name = 'pe_percentile' THEN value_numeric END) as pe_percentile
            FROM (
                SELECT instrument_id, metric_name, value_numeric,
                       ROW_NUMBER() OVER (PARTITION BY instrument_id, metric_name ORDER BY observed_at DESC) as rn
                FROM evidence_items
                WHERE metric_name IN ('roce_simplified', 'roe', 'debt_to_equity', 'revenue_growth_yoy', 'pat_growth_yoy', 'pe_percentile')
            ) t
            WHERE rn = 1
            GROUP BY instrument_id
        ),
        latest_estimates AS (
            SELECT instrument_id, target_mean_price, recommendation_key
            FROM analyst_estimates
        ),
        latest_structured AS (
            SELECT DISTINCT ON (instrument_id)
                instrument_id, data
            FROM structured_provider_data
            ORDER BY instrument_id, parsed_at DESC
        ),
        latest_momentum AS (
            SELECT DISTINCT ON (instrument_id)
                instrument_id, passed as momentum_pass
            FROM momentum_scans
            ORDER BY instrument_id, computed_at DESC
        )
        SELECT 
            i.id,
            i.symbol,
            i.company_name,
            i.sector,
            p.latest_close,
            r.roce,
            r.roe,
            r.debt_to_equity,
            r.rev_growth,
            r.pat_growth,
            r.pe_percentile,
            e.target_mean_price,
            e.recommendation_key,
            s.data as structured_data,
            m.momentum_pass
        FROM instruments i
        LEFT JOIN latest_prices p ON i.id = p.instrument_id
        LEFT JOIN latest_ratios r ON i.id = r.instrument_id
        LEFT JOIN latest_estimates e ON i.id = e.instrument_id
        LEFT JOIN latest_structured s ON i.id = s.instrument_id
        LEFT JOIN latest_momentum m ON i.id = m.instrument_id
        WHERE i.active = true AND i.symbol != 'NIFTY50';
    """)
    res = await session.execute(query)
    rows = [dict(r) for r in res.mappings().all()]

    all_evaluated = [evaluate_single_instrument(r) for r in rows]

    distribution = {
        "6_of_6": len([x for x in all_evaluated if x.conditions_met == 6]),
        "5_of_6": len([x for x in all_evaluated if x.conditions_met == 5]),
        "4_of_6": len([x for x in all_evaluated if x.conditions_met == 4]),
        "3_of_6": len([x for x in all_evaluated if x.conditions_met == 3]),
        "under_3": len([x for x in all_evaluated if x.conditions_met < 3]),
    }

    filtered = [x for x in all_evaluated if x.conditions_met >= min_score]
    if sector and sector.lower() != "all":
        filtered = [x for x in filtered if x.sector and x.sector.lower() == sector.lower()]

    # Sort descending by conditions_met, quality_pct, pat_growth_yoy, roce
    filtered.sort(
        key=lambda x: (
            x.conditions_met,
            x.quality_pct,
            x.pat_growth_yoy or -999,
            x.roce or -999,
        ),
        reverse=True,
    )

    return ChecklistSummaryResponse(
        as_of=datetime.now(timezone.utc).isoformat(),
        total_evaluated=len(all_evaluated),
        distribution=distribution,
        items=filtered,
    )
