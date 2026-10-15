import os
os.environ["DATABASE_URL"] = "postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge"

import asyncio
from datetime import datetime, UTC
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from apps.api.main import app
from packages.common.db import session_scope
from packages.common.models import Instrument
from packages.market_data.models import OHLCVDaily
from packages.strategy.vcp import evaluate_vcp
from packages.strategy.models import VcpScan

async def run_vcp_scans():
    print("Starting VCP scans for all active NSE instruments...")
    
    # 1. Fetch all instrument IDs first
    async with session_scope() as session:
        stmt = select(Instrument.id, Instrument.symbol).where(
            Instrument.exchange == "NSE",
            Instrument.active == True,
            Instrument.instrument_type == "EQUITY"
        ).order_by(Instrument.symbol)
        result = await session.execute(stmt)
        instruments = result.all()
        
    print(f"Found {len(instruments)} active NSE instruments.")
    
    # 2. Process each instrument in its own short-lived session
    for idx, (inst_id, symbol) in enumerate(instruments):
        async with session_scope() as session:
            # Fetch OHLCV data
            ohlcv_stmt = select(OHLCVDaily).where(
                OHLCVDaily.instrument_id == inst_id
            ).order_by(OHLCVDaily.trading_date.asc())
            
            ohlcv_result = await session.execute(ohlcv_stmt)
            bars = ohlcv_result.scalars().all()
            
            if len(bars) < 260:
                print(f"[{idx+1}/{len(instruments)}] Skipping {symbol}: Insufficient history ({len(bars)} < 260 days)")
                continue
                
            # Create DataFrame
            df = pd.DataFrame([{
                'date': b.trading_date,
                'open': float(b.open),
                'high': float(b.high),
                'low': float(b.low),
                'close': float(b.close),
                'volume': float(b.volume)
            } for b in bars])
            
            # Evaluate VCP
            try:
                result_dict = evaluate_vcp(df)
            except Exception as e:
                print(f"[{idx+1}/{len(instruments)}] Error evaluating {symbol}: {e}")
                continue
            
            scan = VcpScan(
                instrument_id=inst_id,
                scan_date=df.iloc[-1]['date'],
                is_vcp_setup=result_dict.get('is_vcp_setup', False),
                pivot_price=result_dict.get('pivot_price'),
                stop_loss_price=result_dict.get('stop_loss_price'),
                risk_reward_pct=result_dict.get('risk_reward_pct'),
                num_contractions=result_dict.get('num_contractions'),
                contractions_depth=result_dict.get('contractions_depth'),
                vdu_flag=result_dict.get('vdu_flag'),
                reason=result_dict.get('reason'),
                computed_at=datetime.now(UTC)
            )
            
            session.add(scan)
            is_setup = "YES" if scan.is_vcp_setup else f"NO ({scan.reason})"
            print(f"[{idx+1}/{len(instruments)}] {symbol}: VCP Setup? {is_setup}")

    print("Done. VCP scans persisted.")

if __name__ == "__main__":
    import os
    os.environ['DATABASE_URL'] = "postgresql+asyncpg://signalforge:signalforge@localhost:5432/signalforge"
    asyncio.run(run_vcp_scans())
