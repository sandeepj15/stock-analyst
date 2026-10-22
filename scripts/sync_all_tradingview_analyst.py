"""Sync all TradingView analyst estimates and ratings into PostgreSQL."""
import asyncio
import logging
from datetime import UTC, datetime
import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.common.db import session_scope
from packages.common.models import Instrument
from packages.analyst_estimates.models import AnalystEstimate
from packages.analyst_estimates.providers.tradingview_analyst_provider import to_recommendation_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sync_tv_analyst")

TRADINGVIEW_SCAN_URL = "https://scanner.tradingview.com/india/scan"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


def safe_float(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


async def sync_all():
    cols = [
        "name",
        "price_target_average",
        "price_target_median",
        "price_target_high",
        "price_target_low",
        "recommendation_mark",
    ]
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    payload = {
        "filter": [
            {
                "left": "recommendation_mark",
                "operation": "nempty"
            }
        ],
        "columns": cols,
        "range": [0, 2500],
    }

    logger.info("Fetching TradingView analyst estimates...")
    resp = requests.post(TRADINGVIEW_SCAN_URL, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data", [])
    logger.info(f"Received {len(data)} items from TradingView scanner.")

    # Map symbol -> parsed values
    tv_data: dict[str, dict] = {}
    for item in data:
        s = item.get("s", "")
        # s is e.g. 'NSE:RELIANCE' or 'BSE:RELIANCE'
        sym = s.split(":")[-1].replace("_", "-").upper()
        d = item.get("d", [])
        if not sym or len(d) < 6:
            continue
        
        target_mean = safe_float(d[1])
        target_med = safe_float(d[2])
        target_hi = safe_float(d[3])
        target_lo = safe_float(d[4])
        rec_mark = safe_float(d[5])

        if sym not in tv_data or s.startswith("NSE:"):
            tv_data[sym] = {
                "target_mean_price": target_mean,
                "target_median_price": target_med,
                "target_high_price": target_hi,
                "target_low_price": target_lo,
                "recommendation_mean": rec_mark,
                "recommendation_key": to_recommendation_key(rec_mark),
            }

    async with session_scope() as session:
        instruments = (await session.execute(
            select(Instrument).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
        )).scalars().all()

        logger.info(f"Found {len(instruments)} active equity instruments in database.")
        matched = 0
        now = datetime.now(UTC)

        for inst in instruments:
            sym = inst.symbol.upper().replace("_", "-")
            info = tv_data.get(sym)
            if not info or (info["target_mean_price"] is None and info["recommendation_mean"] is None):
                continue

            field_sources = {
                k: "tradingview_ta" for k, v in info.items() if v is not None
            }

            stmt = (
                pg_insert(AnalystEstimate)
                .values(
                    instrument_id=inst.id,
                    target_mean_price=info["target_mean_price"],
                    target_high_price=info["target_high_price"],
                    target_low_price=info["target_low_price"],
                    target_median_price=info["target_median_price"],
                    recommendation_mean=info["recommendation_mean"],
                    recommendation_key=info["recommendation_key"],
                    source="tradingview_ta",
                    source_timestamp=now,
                    field_sources=field_sources,
                )
                .on_conflict_do_update(
                    index_elements=[AnalystEstimate.instrument_id],
                    set_={
                        "target_mean_price": info["target_mean_price"],
                        "target_high_price": info["target_high_price"],
                        "target_low_price": info["target_low_price"],
                        "target_median_price": info["target_median_price"],
                        "recommendation_mean": info["recommendation_mean"],
                        "recommendation_key": info["recommendation_key"],
                        "source": "tradingview_ta",
                        "source_timestamp": now,
                        "field_sources": field_sources,
                    },
                )
            )
            await session.execute(stmt)
            matched += 1

        await session.commit()
        logger.info(f"Successfully upserted analyst estimates and ratings for {matched} instruments.")


if __name__ == "__main__":
    asyncio.run(sync_all())
