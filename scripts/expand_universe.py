import asyncio
import pandas as pd
import requests
import io
import yfinance as yf
from sqlalchemy import select
from packages.common.db import session_scope
from packages.common.models import Instrument
import sys

async def main():
    print("Fetching EQUITY_L.csv...")
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    res.raise_for_status()
    
    df = pd.read_csv(io.StringIO(res.text))
    # Filter for EQ series
    df = df[df[' SERIES'].str.strip() == 'EQ']
    symbols = df['SYMBOL'].str.strip().tolist()
    names = df['NAME OF COMPANY'].str.strip().tolist()
    symbol_to_name = dict(zip(symbols, names))
    print(f"Found {len(symbols)} EQ stocks.")
    
    yf_symbols = [f"{sym}.NS" for sym in symbols]
    print("Bulk downloading recent 5d data from Yahoo Finance to sort by turnover...")
    
    chunk_size = 50
    all_close = []
    all_volume = []
    for i in range(0, len(yf_symbols), chunk_size):
        chunk = yf_symbols[i:i+chunk_size]
        try:
            print(f"Downloading chunk {i//chunk_size + 1}/{(len(yf_symbols)+chunk_size-1)//chunk_size}...")
            data = yf.download(chunk, period="5d", threads=True, progress=False)
            if 'Close' in data and 'Volume' in data:
                all_close.append(data['Close'])
                all_volume.append(data['Volume'])
        except Exception as e:
            print(f"Error downloading chunk {i}: {e}")
            
    if all_close and all_volume:
        close_df = pd.concat(all_close, axis=1)
        volume_df = pd.concat(all_volume, axis=1)
        
        turnover = close_df * volume_df
        median_turnover = turnover.median()
        
        # Sort by median turnover
        sorted_symbols = median_turnover.sort_values(ascending=False).index.tolist()
        
        # Strip .NS
        sorted_nse_symbols = [sym.replace('.NS', '') for sym in sorted_symbols if pd.notna(median_turnover[sym])]
        
        top_1500 = sorted_nse_symbols[:1500]
        print(f"Selected top {len(top_1500)} stocks by turnover.")
        
        # Add to database
        async with session_scope() as session:
            # existing
            stmt = select(Instrument).where(Instrument.exchange == "NSE")
            existing = (await session.execute(stmt)).scalars().all()
            existing_symbols = {inst.symbol for inst in existing}
            
            new_instruments = []
            for sym in top_1500:
                if sym not in existing_symbols:
                    new_instruments.append(Instrument(
                        symbol=sym,
                        company_name=symbol_to_name.get(sym, sym),
                        exchange="NSE",
                        instrument_type="EQUITY",
                        active=True
                    ))
            
            if new_instruments:
                session.add_all(new_instruments)
                print(f"Added {len(new_instruments)} new instruments to the database.")
            else:
                print("No new instruments to add.")
    else:
        print("Failed to download data.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
