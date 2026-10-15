"""Populate Company Profiles, AI Summaries, Key Points, Websites, and Missing Sectors.

Extracts rich company overview data from the raw Screener.in scrapes in `raw_provider_scrapes`,
synthesizes plain-English AI business summaries, extracts business segments & key points,
website links, and updates missing Sector/Industry classifications on `instruments`.
"""
import asyncio
import logging
import re
from bs4 import BeautifulSoup
from sqlalchemy import select, text
from packages.common.db import session_scope
from packages.common.models import Instrument

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("populate_profiles")

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove footnote markers like [1], [2], etc.
    text = re.sub(r'\[\d+\]', '', text)
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_sector_industry(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    peers = soup.find(id="peers")
    if not peers:
        return None, None
    links = [
        a.get_text(strip=True) 
        for a in peers.find_all("a") 
        if any(k in a.get("href", "") for k in ("/market/", "/sector/", "/industry/"))
    ]
    if not links:
        links = []
        for a in peers.find_all("a"):
            txt = a.get_text(strip=True)
            href = a.get("href", "")
            if "edit-columns" in href or "export" in href:
                continue
            if any(idx in txt.lower() for idx in ("bse", "nifty", "sensex", "indices")):
                continue
            links.append(txt)
    
    sector = links[0] if len(links) > 0 else None
    industry = links[2] if len(links) > 2 else (links[1] if len(links) > 1 else None)
    return sector, industry

def distill_simple_ai_summary(company_name: str, symbol: str, sector: str | None, industry: str | None, about_raw: str) -> str:
    short_name = re.sub(r'\s+(Limited|Ltd\.?|Corporation|Corp\.?|Industries|Company)$', '', company_name, flags=re.IGNORECASE).strip()
    
    if not about_raw:
        sec = f"in the {sector} ({industry})" if (sector and industry) else f"in the {sector}" if sector else "in Indian equities"
        return f"{short_name} is an established publicly traded enterprise operating {sec}."
    
    # Clean text
    text_clean = clean_text(about_raw)
    
    # Strip common incorporation boilerplate
    text_clean = re.sub(
        r'^(Incorporated in (\w+ )?\d{4},?|Founded in (\w+ )?\d{4},?|Established in (\w+ )?\d{4},?|Promoted in (\w+ )?\d{4},?)\s*',
        '',
        text_clean,
        flags=re.IGNORECASE
    )
    text_clean = re.sub(r'^(Part of the [^,;]+[,;])\s*', '', text_clean, flags=re.IGNORECASE)
    
    # Split sentences
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text_clean) if s.strip()]
    if not sentences:
        return text_clean[:250]
    
    first_two = " ".join(sentences[:2]).strip()
    
    # Plain English transformations
    first_two = re.sub(r'\b(is engaged in the business of providing|is primarily engaged in providing|is in the business of providing)\b', 'provides', first_two, flags=re.IGNORECASE)
    first_two = re.sub(r'\b(is engaged in the business of|is in the business of|is primarily engaged in the business of|is engaged in)\b', 'specializes in', first_two, flags=re.IGNORECASE)
    first_two = re.sub(r'\b(is engaged in the manufacture and sale of|is engaged in manufacturing and trading of)\b', 'manufactures and distributes', first_two, flags=re.IGNORECASE)
    first_two = re.sub(r'\b(is engaged in the manufacture of|is engaged in manufacturing of)\b', 'manufactures', first_two, flags=re.IGNORECASE)
    first_two = re.sub(r'\b(is engaged in providing)\b', 'provides', first_two, flags=re.IGNORECASE)
    first_two = re.sub(r'\b(operates in the business of)\b', 'operates in', first_two, flags=re.IGNORECASE)

    # Clean double spaces
    first_two = re.sub(r'\s+', ' ', first_two).strip()
    
    # Ensure capitalization and period
    if first_two:
        first_two = first_two[0].upper() + first_two[1:]
    if not first_two.endswith('.'):
        first_two += '.'
        
    return first_two

async def populate_all():
    logger.info("Starting company profile and AI summary population...")
    
    async with session_scope() as session:
        # Load all instruments with their latest raw scrape
        stmt = text("""
            SELECT 
                i.id,
                i.symbol,
                i.company_name,
                i.sector,
                i.industry,
                r.html_content
            FROM instruments i
            LEFT JOIN LATERAL (
                SELECT html_content 
                FROM raw_provider_scrapes 
                WHERE instrument_id = i.id 
                ORDER BY scraped_at DESC 
                LIMIT 1
            ) r ON true;
        """)
        
        result = await session.execute(stmt)
        rows = result.fetchall()
        logger.info(f"Loaded {len(rows)} instruments from database.")
        
        updated_count = 0
        sector_updated_count = 0
        
        for inst_id, symbol, name, cur_sector, cur_industry, html in rows:
            about_text = ""
            key_points = ""
            website_url = None
            new_sector = cur_sector
            new_industry = cur_industry
            
            if html:
                soup = BeautifulSoup(html, "html.parser")
                
                # 1. About Description
                about_div = soup.find("div", class_="about")
                if about_div:
                    about_text = clean_text(about_div.get_text(separator=" ", strip=True))
                if not about_text:
                    box = soup.find("div", class_="show-more-box")
                    if box:
                        about_text = clean_text(box.get_text(separator=" ", strip=True))
                
                # 2. Key Points / Segments
                commentary = soup.find("div", class_="commentary")
                if commentary:
                    raw_kp = commentary.get_text(separator="\n", strip=True)
                    raw_kp = clean_text(raw_kp)
                    lines = [
                        l.strip() 
                        for l in raw_kp.splitlines() 
                        if l.strip() and not l.strip().lower() in ("key points", "read more")
                    ]
                    key_points = "\n".join(lines[:12])
                
                # 3. Website Link
                profile = soup.find(class_="company-profile") or soup.find(class_="company-links")
                if profile:
                    for a in profile.find_all("a", href=True):
                        if "website" in a.get_text().lower():
                            website_url = a["href"].strip()
                            break
                            
                # 4. Sector & Industry if missing
                if not cur_sector or cur_sector == "Unclassified":
                    sec, ind = extract_sector_industry(soup)
                    if sec:
                        new_sector = sec
                        if ind and not cur_industry:
                            new_industry = ind
                        sector_updated_count += 1
            
            # Synthesize AI summary
            ai_summary = distill_simple_ai_summary(name, symbol, new_sector, new_industry, about_text)
            
            # Update instrument row
            upd_stmt = (
                text("""
                    UPDATE instruments
                    SET description = :desc,
                        ai_summary = :ai_sum,
                        key_points = :kp,
                        website_url = :web,
                        sector = :sec,
                        industry = :ind,
                        updated_at = NOW()
                    WHERE id = :id;
                """)
            )
            await session.execute(
                upd_stmt,
                {
                    "desc": about_text if about_text else None,
                    "ai_sum": ai_summary if ai_summary else None,
                    "kp": key_points if key_points else None,
                    "web": website_url if website_url else None,
                    "sec": new_sector if new_sector else None,
                    "ind": new_industry if new_industry else None,
                    "id": inst_id,
                }
            )
            updated_count += 1
            
            if updated_count % 200 == 0:
                logger.info(f"Processed {updated_count}/{len(rows)} instruments...")
        
        logger.info(f"Successfully updated {updated_count} instruments! (Backfilled {sector_updated_count} sectors).")

if __name__ == "__main__":
    asyncio.run(populate_all())
