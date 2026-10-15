import asyncio
import os
import pandas as pd
from sqlalchemy import text
from packages.common.db import session_scope

async def extract_data():
    print("Connecting to database...")
    async with session_scope() as session:
        # Find top 150 most liquid NSE stocks (using max volume from latest history as a proxy)
        print("Finding top 150 liquid NSE stocks...")
        query = text("""
            SELECT i.id, i.symbol
            FROM instruments i
            JOIN (
                SELECT instrument_id, AVG(volume) as avg_vol
                FROM ohlcv_daily
                GROUP BY instrument_id
            ) as v ON i.id = v.instrument_id
            WHERE i.active = true AND i.exchange = 'NSE'
            ORDER BY v.avg_vol DESC
            LIMIT 150
        """)
        result = await session.execute(query)
        top_instruments = result.fetchall()
        
        symbols = [row.symbol for row in top_instruments]
        print(f"Found {len(symbols)} stocks. Extracting OHLCV data...")
        
        # Now fetch all OHLCV for these instruments
        all_data = []
        for row in top_instruments:
            instrument_id = row.id
            symbol = row.symbol
            
            ohlcv_query = text("""
                SELECT trading_date as timestamps, open, high, low, close, volume, adjusted_close
                FROM ohlcv_daily
                WHERE instrument_id = :instrument_id
                ORDER BY trading_date ASC
            """)
            ohlcv_result = await session.execute(ohlcv_query, {"instrument_id": instrument_id})
            records = ohlcv_result.fetchall()
            
            # Format to dicts
            for r in records:
                all_data.append({
                    "symbol": symbol,
                    "timestamps": r.timestamps,
                    "open": float(r.open),
                    "high": float(r.high),
                    "low": float(r.low),
                    "close": float(r.close),
                    "volume": float(r.volume),
                    "amount": 0.0, # Dummy column often needed
                })
                
        print(f"Total rows extracted: {len(all_data)}")
        
        df = pd.DataFrame(all_data)
        
        out_path = "packages/kronos/data/nse_top150_ohlcv.csv"
        df.to_csv(out_path, index=False)
        print(f"Data saved to {out_path}")

if __name__ == "__main__":
    asyncio.run(extract_data())
