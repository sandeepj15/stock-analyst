import asyncio
import json
import logging
import re
from packages.common.db import get_engine
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_top_ratios")

def parse_top_ratios(html: str) -> dict:
    top_ratios_match = re.search(r'<ul id="top-ratios">([\s\S]*?)</ul>', html)
    if not top_ratios_match:
        return {}
    
    items = re.findall(r'<span class="name">\s*([^<]+?)\s*</span>[\s\S]*?<span class="number">\s*([^<]+?)\s*</span>', top_ratios_match.group(1))
    raw = {}
    for name, val in items:
        clean_name = re.sub(r'[\+\s]+', ' ', name).strip()
        raw[clean_name] = val.strip().replace(',', '')
    
    res = {}
    if 'Market Cap' in raw:
        try: res['market_cap_cr'] = float(raw['Market Cap'])
        except ValueError: pass
    if 'Stock P/E' in raw:
        try: res['stock_pe'] = float(raw['Stock P/E'])
        except ValueError: pass
    if 'Book Value' in raw:
        try: res['book_value'] = float(raw['Book Value'])
        except ValueError: pass
    if 'Dividend Yield' in raw:
        try: res['dividend_yield_pct'] = float(raw['Dividend Yield'])
        except ValueError: pass
    if 'ROCE' in raw:
        try: res['roce_pct'] = float(raw['ROCE'])
        except ValueError: pass
    if 'ROE' in raw:
        try: res['roe_pct'] = float(raw['ROE'])
        except ValueError: pass
    if 'Face Value' in raw:
        try: res['face_value'] = float(raw['Face Value'])
        except ValueError: pass
    return res

async def main():
    engine = get_engine()
    logger.info("Fetching structured_provider_data and raw_provider_scrapes...")
    async with engine.begin() as conn:
        res = await conn.execute(text('''
            SELECT DISTINCT ON (spd.id) spd.id, rps.html_content 
            FROM structured_provider_data spd
            JOIN raw_provider_scrapes rps ON (rps.id = spd.source_scrape_id OR rps.instrument_id = spd.instrument_id)
            ORDER BY spd.id, rps.scraped_at DESC;
        '''))
        rows = res.fetchall()
        logger.info(f"Loaded {len(rows)} records to inspect.")

        updates = []
        for spd_id, html_content in rows:
            top_ratios = parse_top_ratios(html_content)
            if top_ratios:
                updates.append((spd_id, json.dumps({"top_ratios": top_ratios})))

        logger.info(f"Parsed top_ratios for {len(updates)} records. Updating database...")
        
        # Batch update
        batch_size = 200
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i + batch_size]
            for spd_id, tr_json in batch:
                await conn.execute(text('''
                    UPDATE structured_provider_data 
                    SET data = data || CAST(:tr_json AS jsonb) 
                    WHERE id = :spd_id
                '''), {"spd_id": spd_id, "tr_json": tr_json})
            logger.info(f"Updated {min(i + batch_size, len(updates))} / {len(updates)}")

    logger.info("Successfully updated structured_provider_data with top_ratios!")

if __name__ == "__main__":
    asyncio.run(main())
