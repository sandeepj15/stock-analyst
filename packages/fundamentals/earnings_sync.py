"""Automated earnings detection and ingestion via BSE Financial Results Feed.

Periodically inspects the official BSE Financial Results RSS feed
(https://www.bseindia.com/Data/XML/FinancialResultsFeed.aspx).
When an instrument in our active universe publishes new quarterly results:
1. Checks if the quarterly snapshot is already present in `fundamental_snapshots`.
   If already present: skips immediately.
2. Checks if the new quarter is actually published on Screener.in's quarterly table.
   If not yet reflected on Screener: skips (prevents inserting premature or stale data).
3. If new quarter is properly verified on Screener:
   - Updates `raw_provider_scrapes` (Bronze layer)
   - Updates `structured_provider_data` (Silver layer)
   - Upserts `fundamental_snapshots` (Gold layer)
   - Recomputes the research score for that instrument
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.models import Instrument
from packages.fundamentals.models import FundamentalSnapshot, RawProviderScrape, StructuredProviderData
from packages.fundamentals.providers.screener_in_provider import (
    SOURCE_NAME,
    _parse_quarterly_table,
    _fetch_soup,
)
from packages.scoring.engine import compute_research_score

logger = logging.getLogger(__name__)

BSE_FEED_URL = "https://www.bseindia.com/Data/XML/FinancialResultsFeed.aspx"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


@dataclass
class BseAnnouncement:
    company_name: str
    clean_name: str
    bse_code: str
    period_end: date | None


def fetch_bse_financial_results_feed() -> list[BseAnnouncement]:
    """Fetch and parse live BSE corporate financial results feed."""
    req = urllib.request.Request(
        BSE_FEED_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/xml, text/xml, */*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_bytes = resp.read()
    except Exception as exc:
        logger.warning(f"Failed to fetch BSE Financial Results feed: {exc}")
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        logger.warning(f"Failed to parse BSE XML feed: {exc}")
        return []

    announcements: list[BseAnnouncement] = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        desc = item.findtext("description") or ""

        m_code = re.search(r"\((\d+)\)", title)
        m_date = re.search(r"PERIOD END DATE\s*:\s*(\d{2})-(\d{2})-(\d{4})", desc)
        if not m_code:
            continue

        bse_code = m_code.group(1)
        raw_company = title.split("(")[0].strip()
        clean_company = re.sub(r"\b(Ltd|Limited|LTD)\b\.?", "", raw_company).strip()

        period_end = None
        if m_date:
            try:
                period_end = date(int(m_date.group(3)), int(m_date.group(2)), int(m_date.group(1)))
            except ValueError:
                pass

        announcements.append(
            BseAnnouncement(
                company_name=raw_company,
                clean_name=clean_company,
                bse_code=bse_code,
                period_end=period_end,
            )
        )

    return announcements


def fetch_live_screener_soup(symbol: str) -> tuple[BeautifulSoup | None, str | None, str | None, bool]:
    """Fetch live HTML from Screener.in for a symbol, trying consolidated first then standalone.
    
    Returns (soup, html_text, final_url, is_rate_limited)
    """
    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        for path in (f"/company/{symbol.upper()}/consolidated/", f"/company/{symbol.upper()}/"):
            url = f"https://www.screener.in{path}"
            try:
                resp = client.get(url, headers={"User-Agent": USER_AGENT})
                if resp.status_code == 429:
                    logger.warning(f"Screener rate-limited (429) on {url}")
                    return None, None, None, True
                if resp.status_code == 200:
                    text = resp.text
                    # Check if quarters table exists with period headers
                    if 'id="quarters"' in text:
                        return BeautifulSoup(text, "html.parser"), text, url, False
            except Exception as exc:
                logger.warning(f"Failed to fetch {url}: {exc}")
    return None, None, None, False


async def sync_recent_earnings(session: AsyncSession) -> dict[str, Any]:
    """Identify new earnings declarations from BSE feed and ingest if verified on Screener."""
    feed_items = fetch_bse_financial_results_feed()
    if not feed_items:
        return {"status": "no_feed_items", "updated": [], "skipped": []}

    # Fetch active instruments
    stmt = select(Instrument).where(Instrument.active == True, Instrument.instrument_type == "EQUITY")
    instruments = (await session.execute(stmt)).scalars().all()

    # Build lookup map by clean company name and symbol
    inst_lookup: dict[str, Instrument] = {}
    for inst in instruments:
        clean = re.sub(r"\b(Ltd|Limited|LTD)\b\.?", "", inst.company_name).strip().lower()
        inst_lookup[clean] = inst
        inst_lookup[inst.symbol.lower()] = inst

    # Match feed items
    matches: list[tuple[Instrument, date]] = []
    seen_pairs: set[tuple[str, date]] = set()

    for item in feed_items:
        if not item.period_end:
            continue

        matched_inst = None
        key = item.clean_name.lower()
        if key in inst_lookup:
            matched_inst = inst_lookup[key]
        else:
            # Substring matching for longer names
            for ik, iv in inst_lookup.items():
                if len(key) >= 6 and (key in ik or ik in key):
                    matched_inst = iv
                    break

        if matched_inst:
            pair_key = (matched_inst.symbol, item.period_end)
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                matches.append((matched_inst, item.period_end))

    logger.info(f"BSE feed matched {len(matches)} announcements to active equity universe.")

    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for inst, expected_period_end in matches:
        # Step 1: Check if DB already has this quarterly snapshot
        exists_stmt = select(FundamentalSnapshot.id).where(
            FundamentalSnapshot.instrument_id == inst.id,
            FundamentalSnapshot.period_end == expected_period_end,
            FundamentalSnapshot.period_type == "Q",
        ).limit(1)
        existing_id = (await session.execute(exists_stmt)).scalar_one_or_none()

        if existing_id is not None:
            skipped.append({
                "symbol": inst.symbol,
                "period_end": str(expected_period_end),
                "reason": "already_up_to_date_in_db",
            })
            continue

        # Step 2: Fetch live Screener.in page to verify if new quarter has actually been published
        logger.info(f"Checking live Screener.in for {inst.symbol} to verify new quarter {expected_period_end}...")
        soup, html_text, final_url, is_rate_limited = fetch_live_screener_soup(inst.symbol)
        if is_rate_limited:
            logger.warning("Pausing earnings sync due to rate limit. Will retry on next scheduled run.")
            break

        await asyncio.sleep(random.uniform(2.5, 4.5))

        if not soup or not html_text:
            skipped.append({
                "symbol": inst.symbol,
                "period_end": str(expected_period_end),
                "reason": "screener_page_not_found",
            })
            continue

        quarters_sec = soup.find("section", id="quarters")
        if not quarters_sec:
            skipped.append({
                "symbol": inst.symbol,
                "period_end": str(expected_period_end),
                "reason": "quarters_section_missing_on_screener",
            })
            continue

        # Parse quarterly rows
        parsed_rows = _parse_quarterly_table(quarters_sec)
        matching_qtr = next((r for r in parsed_rows if r["period_end"] == expected_period_end), None)

        if not matching_qtr:
            # Quarter not yet updated on Screener! Skip to avoid inserting old data.
            logger.info(
                f"Skipping {inst.symbol}: Screener has not published {expected_period_end} yet. Will recheck later."
            )
            skipped.append({
                "symbol": inst.symbol,
                "period_end": str(expected_period_end),
                "reason": "screener_not_published_yet",
            })
            continue

        # Step 3: Verified! Insert snapshot, update data lake, and refresh research score
        logger.info(f"Verified new quarter {expected_period_end} for {inst.symbol} on Screener! Ingesting...")
        now = datetime.now(UTC)

        # Ingest all available quarterly snapshots from this fresh scrape
        inserted_count = 0
        for q_row in parsed_rows:
            p_end = q_row["period_end"]
            stmt_snap = pg_insert(FundamentalSnapshot).values(
                instrument_id=inst.id,
                period_end=p_end,
                period_type="Q",
                revenue=q_row.get("revenue"),
                ebitda=q_row.get("ebit"),
                ebit=q_row.get("ebit"),
                pat=q_row.get("pat"),
                eps=q_row.get("eps"),
                operating_cash_flow=None,
                free_cash_flow=None,
                total_assets=None,
                total_liabilities=None,
                total_debt=None,
                cash=None,
                equity=None,
                shares_outstanding=None,
                dividend_yield=None,
                interest_expense=q_row.get("interest_expense"),
                current_assets=None,
                current_liabilities=None,
                source=SOURCE_NAME,
                source_timestamp=now,
            ).on_conflict_do_update(
                constraint="uq_fundamental_snapshot_period_source",
                set_={
                    "revenue": q_row.get("revenue"),
                    "pat": q_row.get("pat"),
                    "eps": q_row.get("eps"),
                    "source_timestamp": now,
                },
            )
            await session.execute(stmt_snap)
            inserted_count += 1

        # Also store raw scrape HTML (Bronze Layer) and structured tables (Silver Layer)
        try:
            raw_scrape = RawProviderScrape(
                instrument_id=inst.id,
                provider=SOURCE_NAME,
                url=final_url or f"https://www.screener.in/company/{inst.symbol.upper()}/consolidated/",
                html_content=html_text,
                scraped_at=now,
            )
            session.add(raw_scrape)
            await session.flush()

            from scripts.parse_structured_screener import parse_screener_html
            structured_data = parse_screener_html(html_text)
            if structured_data:
                stmt_silver = pg_insert(StructuredProviderData).values(
                    instrument_id=inst.id,
                    provider=SOURCE_NAME,
                    data=structured_data,
                    parsed_at=now,
                    source_scrape_id=raw_scrape.id,
                )
                await session.execute(stmt_silver)
        except Exception as exc:
            logger.warning(f"Failed to update data lake for {inst.symbol}: {exc}")

        await session.commit()

        # Recalculate research score for this instrument with the new quarterly fundamentals
        try:
            score = await compute_research_score(session, inst)
            logger.info(f"Recomputed research score for {inst.symbol}: {score.score:.1f}")
        except Exception as exc:
            logger.warning(f"Could not recompute score for {inst.symbol}: {exc}")

        updated.append({
            "symbol": inst.symbol,
            "period_end": str(expected_period_end),
            "revenue": matching_qtr.get("revenue"),
            "pat": matching_qtr.get("pat"),
            "snapshots_synced": inserted_count,
        })

    logger.info(
        f"Earnings sync complete: {len(updated)} stocks updated with verified new quarters, {len(skipped)} skipped."
    )
    return {"status": "success", "updated": updated, "skipped": skipped}
