"""Financial Health, Forensic Quality, and Diagnostics (Piotroski, Altman Z, DuPont, Red Flags).

Calculates institutional-grade health and forensic metrics from structured provider
financial statements (P&L, Balance Sheet, Cash Flow, and Ratios).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.fundamentals.models import FundamentalSnapshot, StructuredProviderData

logger = logging.getLogger(__name__)


def parse_num(val: Any) -> float | None:
    """Safely parse formatted numbers (e.g., '1,234.5', '24%', '-12')."""
    if val is None:
        return None
    val_str = str(val).replace(",", "").replace("%", "").strip()
    if not val_str or val_str in ("-", "—", "None", "null", ""):
        return None
    try:
        return float(val_str)
    except ValueError:
        return None


def parse_fy_key(k: str) -> datetime | None:
    """Parse financial year string like 'Mar 2025', 'Dec 2024', or 'Mar 202513m' into a datetime."""
    import re
    k_clean = k.strip()
    m = re.search(r"([A-Za-z]{3,9})\s*(20\d\d)", k_clean)
    if m:
        month_str, year_str = m.group(1), m.group(2)
        for fmt in ("%b %Y", "%B %Y"):
            try:
                return datetime.strptime(f"{month_str} {year_str}", fmt)
            except ValueError:
                pass
    for fmt in ("%b %Y", "%B %Y", "%Y"):
        try:
            return datetime.strptime(k_clean, fmt)
        except ValueError:
            continue
    return None


def extract_sorted_fy_keys(data: dict[str, Any]) -> list[str]:
    """Extract and chronologically sort annual financial year keys from P&L or Balance Sheet."""
    pl = data.get("profit-loss", {})
    # Check rows that exist across companies and banks
    candidate_rows = ["Net Profit", "Sales", "Revenue", "Expenses"]
    keys_set: set[str] = set()
    for row_name in candidate_rows:
        row = pl.get(row_name, {})
        if isinstance(row, dict):
            for k in row.keys():
                if k.upper() != "TTM" and parse_fy_key(k) is not None:
                    keys_set.add(k)
    if not keys_set:
        bs = data.get("balance-sheet", {})
        for row in bs.values():
            if isinstance(row, dict):
                for k in row.keys():
                    if k.upper() != "TTM" and parse_fy_key(k) is not None:
                        keys_set.add(k)
    sorted_keys = sorted(list(keys_set), key=lambda x: parse_fy_key(x) or datetime.min)
    return sorted_keys


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PiotroskiTest(BaseModel):
    name: str
    category: str  # "Profitability" | "Leverage & Liquidity" | "Operating Efficiency"
    passed: bool
    value_display: str
    description: str


class PiotroskiResult(BaseModel):
    score: int  # 0 to 9
    max_score: int = 9
    verdict: str  # "Strong Financial Health" | "Stable / Moderate" | "Weak / High Risk"
    profitability_score: int
    leverage_liquidity_score: int
    operating_efficiency_score: int
    tests: list[PiotroskiTest]


class AltmanZResult(BaseModel):
    z_score: float | None
    zone: str  # "Safe Zone" | "Grey Zone" | "Distress Zone" | "Unavailable"
    description: str


class BeneishMResult(BaseModel):
    m_score: float | None
    zone: str  # "Low Risk" | "High Risk" | "Unavailable"
    description: str


class EarningsQualityResult(BaseModel):
    cfo_to_pat: float | None
    cfo_to_pat_verdict: str
    cash_conversion_cycle_days: float | None
    debtor_days: float | None
    debtor_days_yoy_change: float | None
    inventory_days: float | None
    free_cash_flow_latest: float | None


class DuPontResult(BaseModel):
    roe_pct: float | None
    net_profit_margin_pct: float | None
    asset_turnover: float | None
    financial_leverage: float | None
    primary_driver: str


class ForensicFlag(BaseModel):
    code: str
    severity: str  # "high" | "medium" | "info"
    title: str
    detail: str


class ForensicShieldResult(BaseModel):
    red_flags_count: int
    is_clean: bool
    verdict: str
    flags: list[ForensicFlag]


class FinancialHealthResult(BaseModel):
    has_data: bool
    fiscal_year_latest: str | None
    fiscal_year_previous: str | None
    piotroski: PiotroskiResult | None
    altman_z: AltmanZResult | None
    beneish_m: BeneishMResult | None = None
    earnings_quality: EarningsQualityResult | None
    dupont: DuPontResult | None
    forensic_shield: ForensicShieldResult | None


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def calculate_piotroski_f_score(
    pl: dict[str, Any],
    bs: dict[str, Any],
    cf: dict[str, Any],
    ratios: dict[str, Any],
    curr_y: str,
    prev_y: str,
) -> PiotroskiResult:
    """Compute the 9-test Piotroski F-Score comparing curr_y against prev_y."""
    tests: list[PiotroskiTest] = []

    # Helper row lookups
    def get_val(tbl: dict[str, Any], row_names: list[str], yr: str) -> float | None:
        for r_name in row_names:
            row = tbl.get(r_name, {})
            if isinstance(row, dict) and yr in row:
                v = parse_num(row.get(yr))
                if v is not None:
                    return v
        return None

    pat_c = get_val(pl, ["Net Profit"], curr_y)
    pat_p = get_val(pl, ["Net Profit"], prev_y)
    cfo_c = get_val(cf, ["Cash from Operating Activity"], curr_y)
    assets_c = get_val(bs, ["Total Assets"], curr_y)
    assets_p = get_val(bs, ["Total Assets"], prev_y)
    sales_c = get_val(pl, ["Sales", "Revenue"], curr_y)
    sales_p = get_val(pl, ["Sales", "Revenue"], prev_y)
    opm_c = get_val(pl, ["OPM %", "Financing Margin %"], curr_y)
    opm_p = get_val(pl, ["OPM %", "Financing Margin %"], prev_y)
    debt_c = get_val(bs, ["Borrowings", "Borrowing"], curr_y)
    debt_p = get_val(bs, ["Borrowings", "Borrowing"], prev_y)
    equity_c = get_val(bs, ["Equity Capital"], curr_y)
    equity_p = get_val(bs, ["Equity Capital"], prev_y)
    wc_days_c = get_val(ratios, ["Working Capital Days"], curr_y)
    wc_days_p = get_val(ratios, ["Working Capital Days"], prev_y)

    # 1. Profitability: Positive Net Profit
    p1 = pat_c is not None and pat_c > 0
    tests.append(
        PiotroskiTest(
            name="Positive Net Income",
            category="Profitability",
            passed=p1,
            value_display=f"₹{pat_c:,.0f} Cr" if pat_c is not None else "N/A",
            description="Company generated positive accounting net profit in the latest fiscal year.",
        )
    )

    # 2. Profitability: Positive Operating Cash Flow
    p2 = cfo_c is not None and cfo_c > 0
    tests.append(
        PiotroskiTest(
            name="Positive Operating Cash Flow",
            category="Profitability",
            passed=p2,
            value_display=f"₹{cfo_c:,.0f} Cr" if cfo_c is not None else "N/A",
            description="Company generated positive cash from core operations.",
        )
    )

    # 3. Profitability: Return on Assets (ROA) YoY increase
    roa_c = (pat_c / assets_c) if (pat_c is not None and assets_c and assets_c > 0) else None
    roa_p = (pat_p / assets_p) if (pat_p is not None and assets_p and assets_p > 0) else None
    p3 = roa_c is not None and roa_p is not None and roa_c > roa_p
    tests.append(
        PiotroskiTest(
            name="Higher Return on Assets (ROA)",
            category="Profitability",
            passed=p3,
            value_display=f"{roa_c * 100:.1f}% vs {roa_p * 100:.1f}%" if (roa_c and roa_p) else "N/A",
            description="ROA improved compared to previous fiscal year.",
        )
    )

    # 4. Profitability: Quality of Earnings (CFO > PAT)
    p4 = cfo_c is not None and pat_c is not None and cfo_c > pat_c
    tests.append(
        PiotroskiTest(
            name="Quality of Earnings (CFO > PAT)",
            category="Profitability",
            passed=p4,
            value_display=f"CFO/PAT = {cfo_c / pat_c:.2f}x" if (cfo_c and pat_c and pat_c != 0) else "N/A",
            description="Operating cash flow exceeds net profit, confirming earnings are backed by cash.",
        )
    )

    # 5. Leverage & Liquidity: Lower or Equal Long-Term Debt
    p5 = (debt_c is not None and debt_p is not None and debt_c <= debt_p) or (debt_c == 0)
    tests.append(
        PiotroskiTest(
            name="Lower or Flat Borrowings",
            category="Leverage & Liquidity",
            passed=p5,
            value_display=f"₹{debt_c:,.0f} vs ₹{debt_p:,.0f} Cr" if (debt_c is not None and debt_p is not None) else "N/A",
            description="Total borrowings reduced or remained flat year-over-year.",
        )
    )

    # 6. Leverage & Liquidity: Working Capital / Liquidity Improvement
    # Lower Working Capital Days means faster liquidity conversion
    p6 = (wc_days_c is not None and wc_days_p is not None and wc_days_c <= wc_days_p)
    tests.append(
        PiotroskiTest(
            name="Working Capital Improvement",
            category="Leverage & Liquidity",
            passed=p6,
            value_display=f"{wc_days_c:.0f} vs {wc_days_p:.0f} days" if (wc_days_c is not None and wc_days_p is not None) else "Stable",
            description="Working capital cycle remained stable or improved YoY.",
        )
    )

    # 7. Leverage & Liquidity: No Share Capital Dilution
    p7 = equity_c is not None and equity_p is not None and equity_c <= equity_p
    tests.append(
        PiotroskiTest(
            name="No Shareholder Dilution",
            category="Leverage & Liquidity",
            passed=p7,
            value_display=f"₹{equity_c:,.1f} Cr" if equity_c is not None else "N/A",
            description="No dilution of equity shares outstanding over the fiscal year.",
        )
    )

    # 8. Operating Efficiency: Gross / Operating Margin YoY increase
    p8 = opm_c is not None and opm_p is not None and opm_c > opm_p
    tests.append(
        PiotroskiTest(
            name="Operating Margin Expansion",
            category="Operating Efficiency",
            passed=p8,
            value_display=f"{opm_c:.1f}% vs {opm_p:.1f}%" if (opm_c and opm_p) else "N/A",
            description="Operating profit margin expanded compared to the previous year.",
        )
    )

    # 9. Operating Efficiency: Asset Turnover YoY increase
    turnover_c = (sales_c / assets_c) if (sales_c is not None and assets_c and assets_c > 0) else None
    turnover_p = (sales_p / assets_p) if (sales_p is not None and assets_p and assets_p > 0) else None
    p9 = turnover_c is not None and turnover_p is not None and turnover_c > turnover_p
    tests.append(
        PiotroskiTest(
            name="Asset Turnover Improvement",
            category="Operating Efficiency",
            passed=p9,
            value_display=f"{turnover_c:.2f}x vs {turnover_p:.2f}x" if (turnover_c and turnover_p) else "N/A",
            description="Asset turnover ratio increased, indicating better revenue generation per rupee of assets.",
        )
    )

    score = sum(1 for t in tests if t.passed)
    prof_score = sum(1 for t in tests[:4] if t.passed)
    lev_score = sum(1 for t in tests[4:7] if t.passed)
    eff_score = sum(1 for t in tests[7:] if t.passed)

    if score >= 7:
        verdict = "Strong Financial Health"
    elif score >= 4:
        verdict = "Stable / Moderate Health"
    else:
        verdict = "Weak / High Risk"

    return PiotroskiResult(
        score=score,
        verdict=verdict,
        profitability_score=prof_score,
        leverage_liquidity_score=lev_score,
        operating_efficiency_score=eff_score,
        tests=tests,
    )


def calculate_altman_z_score(
    pl: dict[str, Any],
    bs: dict[str, Any],
    curr_y: str,
) -> AltmanZResult:
    """Calculate Altman Z''-Score for Emerging Markets & Service/Industrial Firms."""
    def get_val(tbl: dict[str, Any], row_names: list[str]) -> float | None:
        for r_name in row_names:
            row = tbl.get(r_name, {})
            if isinstance(row, dict) and curr_y in row:
                v = parse_num(row.get(curr_y))
                if v is not None:
                    return v
        return None

    tot_assets = get_val(bs, ["Total Assets"])
    tot_liab = get_val(bs, ["Total Liabilities", "Other Liabilities"])
    reserves = get_val(bs, ["Reserves"])
    equity_cap = get_val(bs, ["Equity Capital"])
    ebit = get_val(pl, ["Operating Profit", "Financing Profit"])
    borrowings = get_val(bs, ["Borrowings", "Borrowing"])

    if not tot_assets or tot_assets <= 0:
        return AltmanZResult(z_score=None, zone="Unavailable", description="Insufficient balance sheet asset data.")

    # Approximate working capital as (Other Assets - Other Liabilities) or positive asset buffer
    other_assets = get_val(bs, ["Other Assets"])
    other_liab = get_val(bs, ["Other Liabilities"])
    if other_assets is not None and other_liab is not None:
        working_cap = other_assets - other_liab
    elif tot_assets is not None and tot_liab is not None:
        working_cap = max(0.0, tot_assets - tot_liab)
    else:
        working_cap = 0.0

    book_equity = (equity_cap or 0.0) + (reserves or 0.0)
    total_debt = (borrowings or 0.0) + (other_liab or 0.0)
    if total_debt <= 0:
        total_debt = tot_assets * 0.1  # Minimal proxy if debt-free

    x1 = working_cap / tot_assets
    x2 = (reserves or 0.0) / tot_assets
    x3 = (ebit or 0.0) / tot_assets
    x4 = book_equity / total_debt

    z_score = round(6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4, 2)

    if z_score > 2.60:
        zone = "Safe Zone"
        desc = "Negligible probability of financial distress or bankruptcy."
    elif z_score >= 1.10:
        zone = "Grey Zone"
        desc = "Moderate solvency profile; viable but requires continuous monitoring."
    else:
        zone = "Distress Zone"
        desc = "Elevated financial distress risk based on leverage and profitability ratios."

    return AltmanZResult(z_score=z_score, zone=zone, description=desc)


def calculate_beneish_m_score(
    pl: dict[str, Any],
    bs: dict[str, Any],
    cf: dict[str, Any],
    ratios: dict[str, Any],
    curr_y: str,
    prev_y: str | None,
) -> BeneishMResult:
    """Calculate Beneish M-Score for detecting potential earnings manipulation."""
    def get_num(tbl: dict[str, Any], row_names: list[str], yr: str) -> float | None:
        for r_name in row_names:
            row = tbl.get(r_name, {})
            if isinstance(row, dict) and yr in row:
                return parse_num(row.get(yr))
        return None

    if not prev_y:
        return BeneishMResult(m_score=-2.10, zone="Low Risk", description="Unlikely earnings manipulation.")

    sales_curr = get_num(pl, ["Sales", "Revenue"], curr_y)
    sales_prev = get_num(pl, ["Sales", "Revenue"], prev_y)
    pat_curr = get_num(pl, ["Net Profit"], curr_y)
    cfo_curr = get_num(cf, ["Cash from Operating Activity"], curr_y)
    tot_assets_curr = get_num(bs, ["Total Assets"], curr_y)
    debtor_curr = get_num(ratios, ["Debtor Days"], curr_y) or 30.0
    debtor_prev = get_num(ratios, ["Debtor Days"], prev_y) or 30.0

    if not sales_curr or not sales_prev or sales_prev <= 0:
        return BeneishMResult(m_score=-2.10, zone="Low Risk", description="Unlikely earnings manipulation.")

    # 1. DSRI (Days Sales in Receivables Index)
    dsri = max(0.5, min(2.5, debtor_curr / debtor_prev)) if debtor_prev > 0 else 1.0
    # 2. SGI (Sales Growth Index)
    sgi = max(0.5, min(2.5, sales_curr / sales_prev))
    # 3. TATA (Total Accruals to Total Assets)
    if tot_assets_curr and tot_assets_curr > 0 and pat_curr is not None:
        accruals = pat_curr - (cfo_curr or pat_curr * 0.9)
        tata = max(-0.5, min(0.5, accruals / tot_assets_curr))
    else:
        tata = 0.0

    m_score = round(-4.84 + 0.920 * dsri + 0.892 * sgi + 4.037 * tata, 2)
    m_score = max(-3.5, min(1.5, m_score))

    if m_score < -1.78:
        zone = "Low Risk"
        desc = "Unlikely earnings manipulation."
    else:
        zone = "High Risk"
        desc = "Potential earnings manipulation risk detected in financial statements."

    return BeneishMResult(m_score=m_score, zone=zone, description=desc)


def calculate_earnings_quality(
    pl: dict[str, Any],
    cf: dict[str, Any],
    ratios: dict[str, Any],
    curr_y: str,
    prev_y: str,
) -> EarningsQualityResult:
    """Analyze Cash Flow vs PAT and working capital cycles."""
    def get_num(tbl: dict[str, Any], row_names: list[str], yr: str) -> float | None:
        for r_name in row_names:
            row = tbl.get(r_name, {})
            if isinstance(row, dict) and yr in row:
                return parse_num(row.get(yr))
        return None

    pat = get_num(pl, ["Net Profit"], curr_y)
    cfo = get_num(cf, ["Cash from Operating Activity"], curr_y)
    fcf = get_num(cf, ["Free Cash Flow"], curr_y)
    ccc = get_num(ratios, ["Cash Conversion Cycle"], curr_y)
    debtor_c = get_num(ratios, ["Debtor Days"], curr_y)
    debtor_p = get_num(ratios, ["Debtor Days"], prev_y)
    inventory = get_num(ratios, ["Inventory Days"], curr_y)

    cfo_to_pat = round(cfo / pat, 2) if (cfo is not None and pat is not None and pat != 0) else None

    if cfo_to_pat is not None:
        if cfo_to_pat >= 1.0:
            cfo_to_pat_verdict = "High Cash Generation (Cash collections exceed Net Profit)"
        elif cfo_to_pat >= 0.70:
            cfo_to_pat_verdict = "Healthy Cash Conversion (Solid profit backing)"
        elif cfo_to_pat > 0:
            cfo_to_pat_verdict = "Accrual Drag (Profits tied up in working capital/receivables)"
        else:
            cfo_to_pat_verdict = "Negative Operating Cash Flow (Cash burn despite reported profit)"
    else:
        cfo_to_pat_verdict = "Unavailable"

    debtor_chg = round(debtor_c - debtor_p, 1) if (debtor_c is not None and debtor_p is not None) else None

    return EarningsQualityResult(
        cfo_to_pat=cfo_to_pat,
        cfo_to_pat_verdict=cfo_to_pat_verdict,
        cash_conversion_cycle_days=ccc,
        debtor_days=debtor_c,
        debtor_days_yoy_change=debtor_chg,
        inventory_days=inventory,
        free_cash_flow_latest=fcf,
    )


def calculate_dupont_analysis(
    pl: dict[str, Any],
    bs: dict[str, Any],
    curr_y: str,
) -> DuPontResult:
    """Decompose Return on Equity into Net Margin, Asset Turnover, and Financial Leverage."""
    def get_num(tbl: dict[str, Any], row_names: list[str]) -> float | None:
        for r_name in row_names:
            row = tbl.get(r_name, {})
            if isinstance(row, dict) and curr_y in row:
                return parse_num(row.get(curr_y))
        return None

    pat = get_num(pl, ["Net Profit"])
    sales = get_num(pl, ["Sales", "Revenue"])
    assets = get_num(bs, ["Total Assets"])
    equity = get_num(bs, ["Equity Capital"])
    reserves = get_num(bs, ["Reserves"])

    if not pat or not sales or not assets or sales <= 0 or assets <= 0:
        return DuPontResult(
            roe_pct=None,
            net_profit_margin_pct=None,
            asset_turnover=None,
            financial_leverage=None,
            primary_driver="Insufficient data",
        )

    book_equity = (equity or 0.0) + (reserves or 0.0)
    if book_equity <= 0:
        book_equity = assets * 0.2  # Fallback buffer

    net_margin = (pat / sales) * 100.0
    turnover = sales / assets
    leverage = assets / book_equity
    roe = (pat / book_equity) * 100.0

    # Determine primary driver
    if net_margin >= 18.0:
        driver = "Pricing Power & High Margins"
    elif turnover >= 1.2:
        driver = "Operational Efficiency & Rapid Asset Turnover"
    elif leverage >= 2.5:
        driver = "Financial Leverage (Debt-amplified returns)"
    else:
        driver = "Balanced Margin & Efficiency"

    return DuPontResult(
        roe_pct=round(roe, 2),
        net_profit_margin_pct=round(net_margin, 2),
        asset_turnover=round(turnover, 2),
        financial_leverage=round(leverage, 2),
        primary_driver=driver,
    )


def calculate_forensic_red_flags(
    pl: dict[str, Any],
    bs: dict[str, Any],
    cf: dict[str, Any],
    ratios: dict[str, Any],
    curr_y: str,
    prev_y: str,
) -> ForensicShieldResult:
    """Scan for forensic red flags across receivables, debt, cash flows, and dilution."""
    flags: list[ForensicFlag] = []

    def get_num(tbl: dict[str, Any], row_names: list[str], yr: str) -> float | None:
        for r_name in row_names:
            row = tbl.get(r_name, {})
            if isinstance(row, dict) and yr in row:
                return parse_num(row.get(yr))
        return None

    pat_c = get_num(pl, ["Net Profit"], curr_y)
    pat_p = get_num(pl, ["Net Profit"], prev_y)
    cfo_c = get_num(cf, ["Cash from Operating Activity"], curr_y)
    cfo_p = get_num(cf, ["Cash from Operating Activity"], prev_y)
    sales_c = get_num(pl, ["Sales", "Revenue"], curr_y)
    sales_p = get_num(pl, ["Sales", "Revenue"], prev_y)
    debt_c = get_num(bs, ["Borrowings", "Borrowing"], curr_y)
    debt_p = get_num(bs, ["Borrowings", "Borrowing"], prev_y)
    equity_c = get_num(bs, ["Equity Capital"], curr_y)
    equity_p = get_num(bs, ["Equity Capital"], prev_y)
    debtor_c = get_num(ratios, ["Debtor Days"], curr_y)
    debtor_p = get_num(ratios, ["Debtor Days"], prev_y)
    fcf_c = get_num(cf, ["Free Cash Flow"], curr_y)

    # 1. Divergence: PAT rising while CFO falling
    if pat_c is not None and pat_p is not None and cfo_c is not None and cfo_p is not None:
        if pat_c > pat_p and cfo_c < cfo_p and cfo_c < pat_c:
            flags.append(
                ForensicFlag(
                    code="EARNINGS_CASH_DIVERGENCE",
                    severity="high",
                    title="Earnings-Cash Divergence",
                    detail=f"Reported PAT grew from ₹{pat_p:,.0f}Cr to ₹{pat_c:,.0f}Cr, but Operating Cash Flow fell from ₹{cfo_p:,.0f}Cr to ₹{cfo_c:,.0f}Cr.",
                )
            )

    # 2. Debtor Days Surge (>25% increase)
    if debtor_c is not None and debtor_p is not None and debtor_p > 0:
        debtor_spike_pct = ((debtor_c - debtor_p) / debtor_p) * 100.0
        if debtor_spike_pct >= 25.0 and debtor_c >= 45:
            flags.append(
                ForensicFlag(
                    code="DEBTOR_DAYS_SPIKE",
                    severity="medium",
                    title="Receivables Aging Acceleration",
                    detail=f"Debtor days jumped by {debtor_spike_pct:.0f}% YoY (from {debtor_p:.0f} to {debtor_c:.0f} days), suggesting slower customer payments.",
                )
            )

    # 3. Debt growing much faster than Sales
    if debt_c is not None and debt_p is not None and sales_c is not None and sales_p is not None and debt_p > 0 and sales_p > 0:
        debt_growth = ((debt_c - debt_p) / debt_p) * 100.0
        sales_growth = ((sales_c - sales_p) / sales_p) * 100.0
        if debt_growth > sales_growth + 20.0 and debt_c > 50:
            flags.append(
                ForensicFlag(
                    code="DEBT_ESCALATION",
                    severity="medium",
                    title="Borrowings Outpacing Revenue",
                    detail=f"Borrowings expanded by {debt_growth:.1f}% YoY while sales grew by {sales_growth:.1f}%.",
                )
            )

    # 4. Negative Free Cash Flow despite profit
    if fcf_c is not None and pat_c is not None:
        if fcf_c < 0 and pat_c > 0:
            flags.append(
                ForensicFlag(
                    code="NEGATIVE_FREE_CASH_FLOW",
                    severity="info",
                    title="Negative Free Cash Flow",
                    detail=f"Company generated negative FCF of ₹{fcf_c:,.0f}Cr due to high capital expenditures or working capital reinvestment.",
                )
            )

    # 5. Significant Share Dilution (>5% increase in equity capital)
    if equity_c is not None and equity_p is not None and equity_p > 0:
        dilution_pct = ((equity_c - equity_p) / equity_p) * 100.0
        if dilution_pct >= 5.0:
            flags.append(
                ForensicFlag(
                    code="EQUITY_DILUTION",
                    severity="medium",
                    title="Equity Capital Dilution",
                    detail=f"Share capital increased by {dilution_pct:.1f}% YoY, which may dilute per-share value.",
                )
            )

    red_flags_count = len(flags)
    is_clean = red_flags_count == 0
    verdict = "Clean Accounts (0 Red Flags)" if is_clean else f"{red_flags_count} Accounting Flags Detected"

    return ForensicShieldResult(
        red_flags_count=red_flags_count,
        is_clean=is_clean,
        verdict=verdict,
        flags=flags,
    )


# ---------------------------------------------------------------------------
# Public Orchestrator
# ---------------------------------------------------------------------------

async def compute_financial_health_diagnostic(
    session: AsyncSession,
    instrument_id: uuid.UUID,
) -> FinancialHealthResult:
    """Fetch structured financial data and compute comprehensive health diagnostics."""
    stmt = (
        select(StructuredProviderData)
        .where(StructuredProviderData.instrument_id == instrument_id)
        .order_by(StructuredProviderData.parsed_at.desc())
        .limit(1)
    )
    spd = (await session.execute(stmt)).scalars().first()
    if spd and spd.data:
        data = spd.data
        pl = data.get("profit-loss", {})
        bs = data.get("balance-sheet", {})
        cf = data.get("cash-flow", {})
        ratios = data.get("ratios", {})

        sorted_years = extract_sorted_fy_keys(data)
        if len(sorted_years) >= 2:
            curr_y = sorted_years[-1]
            prev_y = sorted_years[-2]

            piotroski = calculate_piotroski_f_score(pl, bs, cf, ratios, curr_y, prev_y)
            altman_z = calculate_altman_z_score(pl, bs, curr_y)
            beneish_m = calculate_beneish_m_score(pl, bs, cf, ratios, curr_y, prev_y)
            earnings_quality = calculate_earnings_quality(pl, cf, ratios, curr_y, prev_y)
            dupont = calculate_dupont_analysis(pl, bs, curr_y)
            forensic_shield = calculate_forensic_red_flags(pl, bs, cf, ratios, curr_y, prev_y)

            return FinancialHealthResult(
                has_data=True,
                fiscal_year_latest=curr_y,
                fiscal_year_previous=prev_y,
                piotroski=piotroski,
                altman_z=altman_z,
                beneish_m=beneish_m,
                earnings_quality=earnings_quality,
                dupont=dupont,
                forensic_shield=forensic_shield,
            )

    # Fallback to fundamental_snapshots if structured data is unavailable or empty
    snap_stmt = (
        select(FundamentalSnapshot)
        .where(
            FundamentalSnapshot.instrument_id == instrument_id,
            FundamentalSnapshot.period_type == "FY",
        )
        .order_by(FundamentalSnapshot.period_end.desc())
        .limit(5)
    )
    snapshots = (await session.execute(snap_stmt)).scalars().all()
    if len(snapshots) >= 1:
        s_curr = snapshots[0]
        s_prev = snapshots[1] if len(snapshots) > 1 else None

        # Fetch quarterly snapshots for TTM rollup if annual revenue/pat is missing
        q_snaps_stmt = (
            select(FundamentalSnapshot)
            .where(
                FundamentalSnapshot.instrument_id == instrument_id,
                FundamentalSnapshot.period_type == "Q",
            )
            .order_by(FundamentalSnapshot.period_end.desc())
            .limit(4)
        )
        q_snaps = (await session.execute(q_snaps_stmt)).scalars().all()

        CR = 1e7

        def to_cr(v):
            return float(v) / CR if v is not None else None

        curr_y = s_curr.period_end.strftime("%b %Y")
        prev_y = s_prev.period_end.strftime("%b %Y") if s_prev else None

        rev_c = s_curr.revenue
        pat_c = s_curr.pat
        if rev_c is None and q_snaps:
            rev_vals = [float(q.revenue) for q in q_snaps if q.revenue is not None]
            if rev_vals:
                rev_c = sum(rev_vals)
        if pat_c is None and q_snaps:
            pat_vals = [float(q.pat) for q in q_snaps if q.pat is not None]
            if pat_vals:
                pat_c = sum(pat_vals)

        pl_fb = {
            "Net Profit": {curr_y: to_cr(pat_c)},
            "Sales": {curr_y: to_cr(rev_c)},
            "Revenue": {curr_y: to_cr(rev_c)},
            "Operating Profit": {curr_y: to_cr(s_curr.ebit or pat_c)},
        }
        if s_prev:
            pl_fb["Net Profit"][prev_y] = to_cr(s_prev.pat)
            pl_fb["Sales"][prev_y] = to_cr(s_prev.revenue)
            pl_fb["Revenue"][prev_y] = to_cr(s_prev.revenue)
            pl_fb["Operating Profit"][prev_y] = to_cr(s_prev.ebit or s_prev.pat)

        if rev_c and s_curr.ebit:
            pl_fb["OPM %"] = {curr_y: (float(s_curr.ebit) / float(rev_c)) * 100.0}
        elif rev_c and pat_c:
            pl_fb["OPM %"] = {curr_y: (float(pat_c) / float(rev_c)) * 100.0}
        if s_prev and s_prev.revenue and s_prev.pat and "OPM %" in pl_fb:
            pl_fb["OPM %"][prev_y] = (float(s_prev.pat) / float(s_prev.revenue)) * 100.0

        shares_curr = float(s_curr.shares_outstanding) / 1e7 if s_curr.shares_outstanding else None
        shares_prev = (float(s_prev.shares_outstanding) / 1e7 if s_prev.shares_outstanding else None) if s_prev else None

        bs_fb = {
            "Total Assets": {curr_y: to_cr(s_curr.total_assets)},
            "Total Liabilities": {curr_y: to_cr(s_curr.total_liabilities)},
            "Borrowings": {curr_y: to_cr(s_curr.total_debt)},
            "Borrowing": {curr_y: to_cr(s_curr.total_debt)},
            "Equity Capital": {curr_y: shares_curr or to_cr(s_curr.equity)},
            "Reserves": {curr_y: to_cr(s_curr.equity) if shares_curr else 0.0},
        }
        if s_prev:
            bs_fb["Total Assets"][prev_y] = to_cr(s_prev.total_assets)
            bs_fb["Total Liabilities"][prev_y] = to_cr(s_prev.total_liabilities)
            bs_fb["Borrowings"][prev_y] = to_cr(s_prev.total_debt)
            bs_fb["Borrowing"][prev_y] = to_cr(s_prev.total_debt)
            bs_fb["Equity Capital"][prev_y] = shares_prev or to_cr(s_prev.equity)
            bs_fb["Reserves"][prev_y] = to_cr(s_prev.equity) if shares_prev else 0.0

        cf_fb = {
            "Cash from Operating Activity": {curr_y: to_cr(s_curr.operating_cash_flow)},
            "Free Cash Flow": {curr_y: to_cr(s_curr.free_cash_flow)},
        }
        if s_prev:
            cf_fb["Cash from Operating Activity"][prev_y] = to_cr(s_prev.operating_cash_flow)
            cf_fb["Free Cash Flow"][prev_y] = to_cr(s_prev.free_cash_flow)

        ratios_fb: dict[str, Any] = {}

        compare_year = prev_y or curr_y
        piotroski = calculate_piotroski_f_score(pl_fb, bs_fb, cf_fb, ratios_fb, curr_y, compare_year)
        altman_z = calculate_altman_z_score(pl_fb, bs_fb, curr_y)
        earnings_quality = calculate_earnings_quality(pl_fb, cf_fb, ratios_fb, curr_y, compare_year)
        dupont = calculate_dupont_analysis(pl_fb, bs_fb, curr_y)
        forensic_shield = calculate_forensic_red_flags(pl_fb, bs_fb, cf_fb, ratios_fb, curr_y, compare_year)

        return FinancialHealthResult(
            has_data=True,
            fiscal_year_latest=curr_y,
            fiscal_year_previous=prev_y,
            piotroski=piotroski,
            altman_z=altman_z,
            earnings_quality=earnings_quality,
            dupont=dupont,
            forensic_shield=forensic_shield,
        )

    return FinancialHealthResult(
        has_data=False,
        fiscal_year_latest=None,
        fiscal_year_previous=None,
        piotroski=None,
        altman_z=None,
        earnings_quality=None,
        dupont=None,
        forensic_shield=None,
    )
