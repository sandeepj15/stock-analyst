"""Load persisted OHLCV rows into a `pandas.DataFrame` (read side).

This is deliberately separate from `ingestion.py` (the write side) and
from any provider: it is pure DB -> DataFrame plumbing with zero
knowledge of yfinance or any other upstream source, used by the
analytics/indicators API routes (`apps/api/routes/stocks.py`).
"""
from __future__ import annotations

import time
import uuid

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.market_data.models import OHLCVDaily

OHLCV_COLUMNS = ("trading_date", "open", "high", "low", "close", "adjusted_close", "volume")

# In-memory cache to prevent multiple concurrent endpoints (/price, /technicals,
# /momentum-scan, /diagnostic, /analyst-rating) from redundantly querying Postgres
# and rebuilding identical DataFrames for the same stock. 60-second TTL is safe for daily data.
_OHLCV_CACHE: dict[uuid.UUID, tuple[float, pd.DataFrame]] = {}
_OHLCV_CACHE_TTL = 60.0


async def load_ohlcv_dataframe(session: AsyncSession, instrument_id: uuid.UUID) -> pd.DataFrame:
    """Return the full daily OHLCV history for one instrument, ascending by date.

    If a trading_date has bars from more than one `source` (not expected
    with only `yfinance_dev` configured today, but the schema allows it -
    SPEC.md section 10), the most recently ingested row for that date
    wins; this never averages or otherwise fabricates a blended bar.
    Returns an empty DataFrame (with the expected columns) if there are
    no rows - callers must check `.empty` and return a clear API error
    rather than feeding it to the indicator engine (SPEC.md section 81
    rule 23).
    """
    now = time.monotonic()
    cached = _OHLCV_CACHE.get(instrument_id)
    if cached is not None and (now - cached[0]) < _OHLCV_CACHE_TTL:
        return cached[1].copy()

    stmt = (
        select(OHLCVDaily)
        .where(OHLCVDaily.instrument_id == instrument_id)
        .order_by(OHLCVDaily.trading_date.asc(), OHLCVDaily.ingested_at.asc())
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    data = []
    for row in rows:
        c = float(row.close)
        ac = float(row.adjusted_close)
        ratio = ac / c if c else 1.0
        data.append(
            {
                "trading_date": row.trading_date,
                "open": float(row.open) * ratio,
                "high": float(row.high) * ratio,
                "low": float(row.low) * ratio,
                "close": ac,
                "adjusted_close": ac,
                "volume": int(row.volume),
                "ingested_at": row.ingested_at,
            }
        )
    df = pd.DataFrame(data)
    # Keep the most-recently-ingested row per trading_date (see docstring).
    df = df.sort_values("ingested_at").drop_duplicates(subset=["trading_date"], keep="last")
    df = df.sort_values("trading_date").reset_index(drop=True)
    res_df = df[list(OHLCV_COLUMNS)]

    _OHLCV_CACHE[instrument_id] = (now, res_df)
    if len(_OHLCV_CACHE) > 500:
        oldest_id = min(_OHLCV_CACHE.keys(), key=lambda k: _OHLCV_CACHE[k][0])
        _OHLCV_CACHE.pop(oldest_id, None)

    return res_df.copy()
