"""Smart Money Flow and Institutional Ownership Dynamics.

Extracts multi-quarter shareholding trends for FIIs, DIIs, Promoters, and Retail,
and evaluates smart money accumulation vs. distribution patterns.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.fundamentals.models import StructuredProviderData

logger = logging.getLogger(__name__)


def parse_num(val: Any) -> float | None:
    if val is None:
        return None
    val_str = str(val).replace(",", "").replace("%", "").strip()
    if not val_str or val_str in ("-", "—", "None", "null", ""):
        return None
    try:
        return float(val_str)
    except ValueError:
        return None


def parse_int(val: Any) -> int | None:
    if val is None:
        return None
    val_str = str(val).replace(",", "").strip()
    if not val_str or val_str in ("-", "—", "None", "null", ""):
        return None
    try:
        return int(float(val_str))
    except ValueError:
        return None


def parse_quarter_key(k: str) -> datetime | None:
    k_clean = k.strip()
    for fmt in ("%b %Y", "%B %Y"):
        try:
            return datetime.strptime(k_clean, fmt)
        except ValueError:
            continue
    return None


class ShareholdingQuarter(BaseModel):
    quarter: str
    promoter: float | None
    fii: float | None
    dii: float | None
    public: float | None
    government: float | None
    shareholders_count: int | None


class ShareholdingFlowResult(BaseModel):
    has_data: bool
    latest_quarter: str | None
    fii_current: float | None
    fii_qoq_change: float | None
    fii_yoy_change: float | None
    dii_current: float | None
    dii_qoq_change: float | None
    dii_yoy_change: float | None
    promoter_current: float | None
    promoter_qoq_change: float | None
    promoter_yoy_change: float | None
    public_current: float | None
    shareholders_count_current: int | None
    shareholders_count_qoq_change: int | None
    institutional_holding_current: float | None
    institutional_holding_qoq_change: float | None
    smart_money_verdict: str
    smart_money_description: str
    quarters_history: list[ShareholdingQuarter]


async def compute_shareholding_flow(
    session: AsyncSession,
    instrument_id: uuid.UUID,
) -> ShareholdingFlowResult:
    """Compute institutional accumulation and shareholding trends."""
    stmt = (
        select(StructuredProviderData)
        .where(StructuredProviderData.instrument_id == instrument_id)
        .order_by(StructuredProviderData.parsed_at.desc())
        .limit(1)
    )
    spd = (await session.execute(stmt)).scalars().first()
    if not spd or not spd.data or "shareholding" not in spd.data:
        return ShareholdingFlowResult(
            has_data=False,
            latest_quarter=None,
            fii_current=None,
            fii_qoq_change=None,
            fii_yoy_change=None,
            dii_current=None,
            dii_qoq_change=None,
            dii_yoy_change=None,
            promoter_current=None,
            promoter_qoq_change=None,
            promoter_yoy_change=None,
            public_current=None,
            shareholders_count_current=None,
            shareholders_count_qoq_change=None,
            institutional_holding_current=None,
            institutional_holding_qoq_change=None,
            smart_money_verdict="Unavailable",
            smart_money_description="No shareholding records available.",
            quarters_history=[],
        )

    sh_data = spd.data["shareholding"]
    fii_row = sh_data.get("FIIs", {})
    dii_row = sh_data.get("DIIs", {})
    prom_row = sh_data.get("Promoters", {})
    pub_row = sh_data.get("Public", {})
    govt_row = sh_data.get("Government", {})
    count_row = sh_data.get("No. of Shareholders", {})

    # Collect and sort all valid quarter keys
    all_keys: set[str] = set()
    for row in (fii_row, dii_row, prom_row, pub_row):
        if isinstance(row, dict):
            for k in row.keys():
                if parse_quarter_key(k) is not None:
                    all_keys.add(k)

    sorted_quarters = sorted(list(all_keys), key=lambda x: parse_quarter_key(x) or datetime.min)
    if not sorted_quarters:
        return ShareholdingFlowResult(
            has_data=False,
            latest_quarter=None,
            fii_current=None,
            fii_qoq_change=None,
            fii_yoy_change=None,
            dii_current=None,
            dii_qoq_change=None,
            dii_yoy_change=None,
            promoter_current=None,
            promoter_qoq_change=None,
            promoter_yoy_change=None,
            public_current=None,
            shareholders_count_current=None,
            shareholders_count_qoq_change=None,
            institutional_holding_current=None,
            institutional_holding_qoq_change=None,
            smart_money_verdict="Unavailable",
            smart_money_description="No parsed quarter dates found.",
            quarters_history=[],
        )

    # Build chronological quarters history
    history: list[ShareholdingQuarter] = []
    for q in sorted_quarters:
        history.append(
            ShareholdingQuarter(
                quarter=q,
                promoter=parse_num(prom_row.get(q)) if isinstance(prom_row, dict) else None,
                fii=parse_num(fii_row.get(q)) if isinstance(fii_row, dict) else None,
                dii=parse_num(dii_row.get(q)) if isinstance(dii_row, dict) else None,
                public=parse_num(pub_row.get(q)) if isinstance(pub_row, dict) else None,
                government=parse_num(govt_row.get(q)) if isinstance(govt_row, dict) else None,
                shareholders_count=parse_int(count_row.get(q)) if isinstance(count_row, dict) else None,
            )
        )

    latest_q = history[-1]
    prev_q = history[-2] if len(history) >= 2 else None
    yoy_q = history[-5] if len(history) >= 5 else None

    # Calculate current values and changes
    fii_cur = latest_q.fii
    fii_qoq = round(latest_q.fii - prev_q.fii, 2) if (latest_q.fii is not None and prev_q and prev_q.fii is not None) else None
    fii_yoy = round(latest_q.fii - yoy_q.fii, 2) if (latest_q.fii is not None and yoy_q and yoy_q.fii is not None) else None

    dii_cur = latest_q.dii
    dii_qoq = round(latest_q.dii - prev_q.dii, 2) if (latest_q.dii is not None and prev_q and prev_q.dii is not None) else None
    dii_yoy = round(latest_q.dii - yoy_q.dii, 2) if (latest_q.dii is not None and yoy_q and yoy_q.dii is not None) else None

    prom_cur = latest_q.promoter
    prom_qoq = round(latest_q.promoter - prev_q.promoter, 2) if (latest_q.promoter is not None and prev_q and prev_q.promoter is not None) else None
    prom_yoy = round(latest_q.promoter - yoy_q.promoter, 2) if (latest_q.promoter is not None and yoy_q and yoy_q.promoter is not None) else None

    count_cur = latest_q.shareholders_count
    count_qoq = (latest_q.shareholders_count - prev_q.shareholders_count) if (latest_q.shareholders_count is not None and prev_q and prev_q.shareholders_count is not None) else None

    inst_cur = round((fii_cur or 0.0) + (dii_cur or 0.0), 2) if (fii_cur is not None or dii_cur is not None) else None
    inst_prev = ((prev_q.fii or 0.0) + (prev_q.dii or 0.0)) if prev_q and (prev_q.fii is not None or prev_q.dii is not None) else None
    inst_qoq = round(inst_cur - inst_prev, 2) if (inst_cur is not None and inst_prev is not None) else None

    # Determine Smart Money verdict
    if inst_qoq is not None and inst_qoq >= 0.5:
        if count_qoq is not None and count_qoq < 0:
            verdict = "Strong Institutional Accumulation"
            desc = f"Smart money (FIIs/DIIs) increased holding by {inst_qoq:+.2f}% while retail shareholder count decreased, confirming institutional absorption."
        else:
            verdict = "Institutional Inflows"
            desc = f"Institutions increased combined stake by {inst_qoq:+.2f}% in the latest quarter."
    elif inst_qoq is not None and inst_qoq <= -0.5:
        if count_qoq is not None and count_qoq > 0:
            verdict = "Retail Distribution Alert"
            desc = f"Institutions trimmed {abs(inst_qoq):.2f}% while retail shareholder count jumped, indicating institutional distribution into public hands."
        else:
            verdict = "Institutional Outflows"
            desc = f"Institutions reduced combined holding by {abs(inst_qoq):.2f}% in the latest quarter."
    else:
        verdict = "Stable Ownership"
        desc = "Institutional and promoter holdings remained balanced with minimal turnover."

    return ShareholdingFlowResult(
        has_data=True,
        latest_quarter=latest_q.quarter,
        fii_current=fii_cur,
        fii_qoq_change=fii_qoq,
        fii_yoy_change=fii_yoy,
        dii_current=dii_cur,
        dii_qoq_change=dii_qoq,
        dii_yoy_change=dii_yoy,
        promoter_current=prom_cur,
        promoter_qoq_change=prom_qoq,
        promoter_yoy_change=prom_yoy,
        public_current=latest_q.public,
        shareholders_count_current=count_cur,
        shareholders_count_qoq_change=count_qoq,
        institutional_holding_current=inst_cur,
        institutional_holding_qoq_change=inst_qoq,
        smart_money_verdict=verdict,
        smart_money_description=desc,
        quarters_history=history[-8:],  # Return up to the latest 8 quarters
    )


async def sync_all_institutional_holdings(session: AsyncSession) -> int:
    """Extract shareholding metrics for all instruments from structured_provider_data
    and upsert into institutional_holdings table.
    """
    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import insert
    from packages.fundamentals.models import InstitutionalHolding

    stmt = (
        select(StructuredProviderData.instrument_id, StructuredProviderData.data)
        .distinct(StructuredProviderData.instrument_id)
        .order_by(StructuredProviderData.instrument_id, StructuredProviderData.parsed_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    records = []
    for inst_id, data in rows:
        if not data or "shareholding" not in data:
            continue
        sh_data = data["shareholding"]
        fii_row = sh_data.get("FIIs", {})
        dii_row = sh_data.get("DIIs", {})
        prom_row = sh_data.get("Promoters", {})
        pub_row = sh_data.get("Public", {})

        all_keys: set[str] = set()
        for r in (fii_row, dii_row, prom_row, pub_row):
            if isinstance(r, dict):
                for k in r.keys():
                    if parse_quarter_key(k) is not None:
                        all_keys.add(k)
        sorted_qs = sorted(list(all_keys), key=lambda x: parse_quarter_key(x) or datetime.min)
        if not sorted_qs:
            continue

        latest_q = sorted_qs[-1]
        prev_q = sorted_qs[-2] if len(sorted_qs) >= 2 else None

        fii_cur = parse_num(fii_row.get(latest_q)) if isinstance(fii_row, dict) else None
        fii_prev = parse_num(fii_row.get(prev_q)) if (prev_q and isinstance(fii_row, dict)) else None
        fii_qoq = round(fii_cur - fii_prev, 2) if (fii_cur is not None and fii_prev is not None) else None

        dii_cur = parse_num(dii_row.get(latest_q)) if isinstance(dii_row, dict) else None
        dii_prev = parse_num(dii_row.get(prev_q)) if (prev_q and isinstance(dii_row, dict)) else None
        dii_qoq = round(dii_cur - dii_prev, 2) if (dii_cur is not None and dii_prev is not None) else None

        prom_cur = parse_num(prom_row.get(latest_q)) if isinstance(prom_row, dict) else None
        prom_prev = parse_num(prom_row.get(prev_q)) if (prev_q and isinstance(prom_row, dict)) else None
        prom_qoq = round(prom_cur - prom_prev, 2) if (prom_cur is not None and prom_prev is not None) else None

        pub_cur = parse_num(pub_row.get(latest_q)) if isinstance(pub_row, dict) else None

        records.append({
            "instrument_id": inst_id,
            "latest_quarter": latest_q,
            "fii_current": fii_cur,
            "fii_qoq_change": fii_qoq,
            "dii_current": dii_cur,
            "dii_qoq_change": dii_qoq,
            "promoter_current": prom_cur,
            "promoter_qoq_change": prom_qoq,
            "public_current": pub_cur,
        })

    if not records:
        return 0

    insert_stmt = insert(InstitutionalHolding).values(records)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[InstitutionalHolding.instrument_id],
        set_={
            "latest_quarter": insert_stmt.excluded.latest_quarter,
            "fii_current": insert_stmt.excluded.fii_current,
            "fii_qoq_change": insert_stmt.excluded.fii_qoq_change,
            "dii_current": insert_stmt.excluded.dii_current,
            "dii_qoq_change": insert_stmt.excluded.dii_qoq_change,
            "promoter_current": insert_stmt.excluded.promoter_current,
            "promoter_qoq_change": insert_stmt.excluded.promoter_qoq_change,
            "public_current": insert_stmt.excluded.public_current,
            "updated_at": func.now(),
        }
    )
    await session.execute(upsert_stmt)
    await session.commit()
    return len(records)
