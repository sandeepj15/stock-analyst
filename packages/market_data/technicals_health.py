"""Technical Health, Institutional Volume Flow, and Market Structure.

Computes multi-timeframe trend alignment, institutional Up/Down volume ratios,
volatility squeeze patterns, and 52-week price structure.
"""
from __future__ import annotations

import logging
import uuid
import numpy as np
import pandas as pd
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from packages.analytics import atr, ema, sma
from packages.market_data.history import load_ohlcv_dataframe

logger = logging.getLogger(__name__)


class TechnicalHealthResult(BaseModel):
    has_data: bool
    current_price: float | None
    ema_20: float | None
    sma_50: float | None
    sma_200: float | None
    trend_alignment_grade: str
    trend_summary: str
    price_vs_20ema_pct: float | None
    price_vs_50sma_pct: float | None
    price_vs_200sma_pct: float | None
    up_down_volume_ratio: float | None
    volume_flow_verdict: str
    accumulation_days_count_20d: int
    is_volatility_squeeze: bool
    volatility_state: str
    high_52w: float | None
    low_52w: float | None
    pct_from_52w_high: float | None
    pct_from_52w_low: float | None
    range_position_pct: float | None


async def compute_technical_health(
    session: AsyncSession,
    instrument_id: uuid.UUID,
) -> TechnicalHealthResult:
    """Evaluate technical structure, volume dynamics, and range position."""
    df = await load_ohlcv_dataframe(session, instrument_id)
    if df.empty or len(df) < 20:
        return TechnicalHealthResult(
            has_data=False,
            current_price=None,
            ema_20=None,
            sma_50=None,
            sma_200=None,
            trend_alignment_grade="Insufficient Data",
            trend_summary="Less than 20 daily price bars available.",
            price_vs_20ema_pct=None,
            price_vs_50sma_pct=None,
            price_vs_200sma_pct=None,
            up_down_volume_ratio=None,
            volume_flow_verdict="Unavailable",
            accumulation_days_count_20d=0,
            is_volatility_squeeze=False,
            volatility_state="Normal Volatility",
            high_52w=None,
            low_52w=None,
            pct_from_52w_high=None,
            pct_from_52w_low=None,
            range_position_pct=None,
        )

    close_series = df["adjusted_close"]
    vol_series = df["volume"]
    high_series = df["high"]
    low_series = df["low"]

    current_price = float(close_series.iloc[-1])

    # Moving averages
    ema_20_val = float(ema(close_series, 20).iloc[-1]) if len(close_series) >= 20 else None
    sma_50_val = float(sma(close_series, 50).iloc[-1]) if len(close_series) >= 50 else None
    sma_200_val = float(sma(close_series, 200).iloc[-1]) if len(close_series) >= 200 else None

    # Trend distances
    vs_20ema = round(((current_price / ema_20_val) - 1.0) * 100.0, 2) if ema_20_val else None
    vs_50sma = round(((current_price / sma_50_val) - 1.0) * 100.0, 2) if sma_50_val else None
    vs_200sma = round(((current_price / sma_200_val) - 1.0) * 100.0, 2) if sma_200_val else None

    # Multi-timeframe trend alignment
    if ema_20_val and sma_50_val and sma_200_val:
        if current_price > ema_20_val and ema_20_val > sma_50_val and sma_50_val > sma_200_val:
            grade = "Bullish Alignment (Strong Uptrend)"
            summary = "Price is leading above all key moving averages in a textbook upward stacking sequence."
        elif current_price < ema_20_val and current_price > sma_50_val and sma_50_val > sma_200_val:
            grade = "Constructive Pullback in Uptrend"
            summary = "Short-term pullback testing support, with primary medium- and long-term uptrends intact."
        elif current_price > sma_200_val and sma_50_val < sma_200_val:
            grade = "Base Building / Trend Reversal"
            summary = "Price has reclaimed 200 SMA while medium-term moving average is rounding up."
        elif current_price < sma_50_val and sma_50_val < sma_200_val:
            grade = "Bearish Alignment (Downtrend)"
            summary = "Price is trading below key moving averages in a defensive downward slope."
        else:
            grade = "Consolidation / Range-Bound"
            summary = "Price is oscillating between moving averages without clear directional trend."
    elif sma_50_val:
        if current_price > sma_50_val:
            grade = "Short-Term Uptrend"
            summary = "Trading above 50-day moving average."
        else:
            grade = "Short-Term Downtrend"
            summary = "Trading below 50-day moving average."
    else:
        grade = "Neutral"
        summary = "Building price history."

    # Up/Down Volume Ratio (last 50 bars)
    window = min(50, len(close_series) - 1)
    diff = close_series.diff().iloc[-window:]
    vols = vol_series.iloc[-window:]
    up_vols = vols[diff >= 0].sum()
    down_vols = vols[diff < 0].sum()

    if down_vols > 0:
        ud_ratio = round(float(up_vols / down_vols), 2)
    else:
        ud_ratio = 2.0 if up_vols > 0 else 1.0

    if ud_ratio >= 1.25:
        volume_verdict = "Constructive Accumulation (Up-day volume dominates)"
    elif ud_ratio <= 0.85:
        volume_verdict = "Distribution Pressure (Down-day volume dominates)"
    else:
        volume_verdict = "Balanced Volume Flow"

    # Accumulation Days in last 20 bars
    # Green bar with volume > 1.5x 20-day average volume
    recent_bars = min(20, len(close_series) - 1)
    avg_vol_20 = float(vol_series.iloc[-20:].mean()) if len(vol_series) >= 20 else 1.0
    accum_count = 0
    for i in range(-recent_bars, 0):
        is_green = close_series.iloc[i] >= close_series.iloc[i - 1]
        is_high_vol = vol_series.iloc[i] > (1.5 * avg_vol_20)
        if is_green and is_high_vol:
            accum_count += 1

    # Volatility Squeeze / Coiling (10 ATR vs 50 ATR)
    if len(close_series) >= 50:
        atr_10 = float(atr(high_series, low_series, close_series, 10).iloc[-1])
        atr_50 = float(atr(high_series, low_series, close_series, 50).iloc[-1])
        if atr_50 > 0 and (atr_10 / atr_50) < 0.70:
            is_squeeze = True
            vol_state = "Volatility Squeeze / Coiling (Pre-Breakout Setup)"
        else:
            is_squeeze = False
            vol_state = "Normal Volatility"
    else:
        is_squeeze = False
        vol_state = "Normal Volatility"

    # 52-Week High / Low & Range Position (up to 252 trading bars)
    bars_52w = df.tail(252)
    high_52w = float(bars_52w["high"].max())
    low_52w = float(bars_52w["low"].min())
    pct_from_high = round(((current_price / high_52w) - 1.0) * 100.0, 2) if high_52w > 0 else 0.0
    pct_from_low = round(((current_price / low_52w) - 1.0) * 100.0, 2) if low_52w > 0 else 0.0
    range_pos = round(((current_price - low_52w) / (high_52w - low_52w)) * 100.0, 1) if high_52w > low_52w else 50.0

    return TechnicalHealthResult(
        has_data=True,
        current_price=round(current_price, 2),
        ema_20=round(ema_20_val, 2) if ema_20_val else None,
        sma_50=round(sma_50_val, 2) if sma_50_val else None,
        sma_200=round(sma_200_val, 2) if sma_200_val else None,
        trend_alignment_grade=grade,
        trend_summary=summary,
        price_vs_20ema_pct=vs_20ema,
        price_vs_50sma_pct=vs_50sma,
        price_vs_200sma_pct=vs_200sma,
        up_down_volume_ratio=ud_ratio,
        volume_flow_verdict=volume_verdict,
        accumulation_days_count_20d=accum_count,
        is_volatility_squeeze=is_squeeze,
        volatility_state=vol_state,
        high_52w=round(high_52w, 2),
        low_52w=round(low_52w, 2),
        pct_from_52w_high=pct_from_high,
        pct_from_52w_low=pct_from_low,
        range_position_pct=range_pos,
    )
