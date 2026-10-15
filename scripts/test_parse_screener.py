import asyncio
import json
from bs4 import BeautifulSoup
from sqlalchemy import select
from packages.common.db import session_scope
from packages.fundamentals.models import RawProviderScrape

async def test_parse():
    async with session_scope() as session:
        stmt = select(RawProviderScrape).limit(1)
        result = await session.execute(stmt)
        scrape = result.scalar_one_or_none()
        
        if not scrape:
            print("No scrape data found.")
            return

        soup = BeautifulSoup(scrape.html_content, "html.parser")
        
        structured_data = {}
        
        # Sections usually have id corresponding to the table name
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
                
            headers = [th.get_text(strip=True) for th in thead.find_all("th")][1:] # Skip first empty/metric header
            
            table_data = {}
            for tr in tbody.find_all("tr"):
                tds = tr.find_all("td")
                if not tds:
                    continue
                    
                # The first td often has a button or just text. Get text recursively.
                metric_name = tds[0].get_text(strip=True)
                # Remove any "+" or "-" expansion characters often found in screener
                metric_name = metric_name.strip("+- \n\t")
                
                if not metric_name:
                    continue
                    
                values = [td.get_text(strip=True) for td in tds[1:]]
                
                # Pair with headers
                row_data = dict(zip(headers, values))
                table_data[metric_name] = row_data
                
            structured_data[sec_id] = table_data
            
        print(json.dumps(structured_data, indent=2))

if __name__ == "__main__":
    asyncio.run(test_parse())
