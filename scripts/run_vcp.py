import asyncio
from sqlalchemy import select, text
from packages.common.db import session_scope
from packages.common.models import Instrument
from packages.momentum.vcp import evaluate_vcp
import pandas as pd
from datetime import datetime, UTC
import json

async def run_all_vcp():
    async with session_scope() as session:
        stmt = select(Instrument).where(Instrument.active == True)
        instruments = (await session.execute(stmt)).scalars().all()
        
        print(f"Evaluating VCP for {len(instruments)} instruments...")
        
        insert_stmt = text("""
            INSERT INTO vcp_scans 
            (id, instrument_id, scan_date, is_vcp_setup, pivot_price, stop_loss_price, risk_reward_pct, num_contractions, contractions_depth, vdu_flag, reason, computed_at)
            VALUES (gen_random_uuid(), :instrument_id, :scan_date, :is_vcp_setup, :pivot_price, :stop_loss_price, :risk_reward_pct, :num_contractions, :contractions_depth, :vdu_flag, :reason, :computed_at)
        """)
        
        query = text("""
            SELECT trading_date as date, open, high, low, close, volume 
            FROM ohlcv_daily 
            WHERE instrument_id = :iid 
            ORDER BY trading_date ASC
        """)
        
        for inst in instruments:
            rows = (await session.execute(query, {"iid": inst.id})).all()
            if len(rows) < 260:
                continue
                
            df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['volume'] = df['volume'].astype(float)
            
            res = evaluate_vcp(df)
            await session.execute(insert_stmt, {
                "instrument_id": inst.id,
                "scan_date": df.iloc[-1]['date'],
                "is_vcp_setup": res["is_vcp_setup"],
                "pivot_price": res.get("pivot_price"),
                "stop_loss_price": res.get("stop_loss_price"),
                "risk_reward_pct": res.get("risk_reward_pct"),
                "num_contractions": res.get("num_contractions"),
                "contractions_depth": json.dumps(res.get("contractions_depth", [])),
                "vdu_flag": res.get("vdu_flag"),
                "reason": res.get("reason"),
                "computed_at": datetime.now(UTC)
            })
        await session.commit()
        print("VCP calculation complete!")

if __name__ == "__main__":
    asyncio.run(run_all_vcp())
