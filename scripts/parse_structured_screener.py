import argparse
import asyncio
import logging
from datetime import datetime, UTC

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.common.config import get_settings
from packages.common.db import session_scope
from packages.common.logging import configure_logging
from packages.fundamentals.models import RawProviderScrape, StructuredProviderData

logger = logging.getLogger(__name__)

def parse_screener_html(html_content: str) -> dict:
    soup = BeautifulSoup(html_content, "html.parser")
    structured_data = {}
    
    sections = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios", "shareholding"]
    
    for sec_id in sections:
        section = soup.find("section", id=sec_id)
        if not section:
            continue
        
        table = section.find("table", class_="data-table")
        if not table:
            continue
            
        thead = table.find("thead")
        tbody = table.find("tbody")
        
        if not thead or not tbody:
            continue
            
        # Get headers, typically periods like "Mar 2023", "Mar 2024"
        headers = [th.get_text(strip=True) for th in thead.find_all("th")][1:]
        
        table_data = {}
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
                
            metric_name = tds[0].get_text(strip=True).strip("+- \n\t")
            if not metric_name:
                continue
                
            values = [td.get_text(strip=True) for td in tds[1:]]
            table_data[metric_name] = dict(zip(headers, values))
            
        structured_data[sec_id] = table_data
        
    return structured_data

async def main(batch_size: int = 100):
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)
    
    logger.info("Starting Silver Layer parsing for screener_in raw HTML")
    
    async with session_scope() as session:
        # We find raw scrapes that don't have a corresponding structured_provider_data entry 
        # or just parse all of them for now. Let's do a simple approach: parse all latest scrapes.
        
        # Actually, let's just grab all raw scrapes and UPSERT to structured_provider_data.
        stmt = select(RawProviderScrape).where(RawProviderScrape.provider == "screener_in")
        
        result = await session.execute(stmt)
        scrapes = result.scalars().all()
        
        logger.info(f"Found {len(scrapes)} raw scrapes to parse.")
        
        success_count = 0
        for scrape in scrapes:
            try:
                parsed_data = parse_screener_html(scrape.html_content)
                if not parsed_data:
                    logger.warning(f"No structured data found for scrape id {scrape.id}")
                    continue
                
                stmt_insert = pg_insert(StructuredProviderData).values(
                    instrument_id=scrape.instrument_id,
                    provider="screener_in",
                    data=parsed_data,
                    parsed_at=datetime.now(UTC),
                    source_scrape_id=scrape.id
                )
                
                # If we run this multiple times, we might want to update the data if it exists.
                # However, there's no unique constraint on (instrument_id, provider) currently 
                # in the model that prevents multiple rows, but we probably want a clean append 
                # or just insert. For now, we just insert. We can clean up old ones or just keep history.
                await session.execute(stmt_insert)
                success_count += 1
                
            except Exception as e:
                logger.error(f"Error parsing scrape id {scrape.id}: {e}")
        
        await session.commit()
        logger.info(f"Finished parsing. Successfully inserted {success_count} structured records.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(main(args.batch_size))
