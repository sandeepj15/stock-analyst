"""TradingView Technical Analysis Signals & Multi-Timeframe Momentum Flags.

Fetches 1D (daily) and 1W (weekly) technical recommendation indicators
from TradingView's India equity scanner (Recommend.All and Recommend.All|1W).
Translates continuous indicator values [-1.0 to 1.0] into institutional
recommendations (STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL) and produces
a combined momentum flag:
- 'STRONG_BUY_BOTH': 1D + 1W both show STRONG_BUY (high-conviction momentum confluence)
- 'STRONG_BUY_1D': 1D shows STRONG_BUY (daily momentum impulse)
- 'STRONG_BUY_1W': 1W shows STRONG_BUY (macro weekly trend strength)
- 'STRONG_SELL_BOTH': 1D + 1W both show STRONG_SELL (severe bearish confluence)
- 'STRONG_SELL_1D': 1D shows STRONG_SELL (daily breakdown)
- 'STRONG_SELL_1W': 1W shows STRONG_SELL (macro weekly breakdown)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
import httpx
import requests

from packages.common import cache

logger = logging.getLogger(__name__)

TRADINGVIEW_SCAN_URL = "https://scanner.tradingview.com/india/scan"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
TV_SIGNALS_CACHE_KEY = "tradingview_signals:v1"
TV_SIGNALS_CACHE_TTL = 3600  # 1 hour


def to_recommendation_label(val: float | None) -> str | None:
    """Map TradingView continuous recommendation score [-1.0, 1.0] to standard category."""
    if val is None:
        return None
    if val < -0.5:
        return "STRONG_SELL"
    if val < -0.1:
        return "SELL"
    if val <= 0.1:
        return "NEUTRAL"
    if val <= 0.5:
        return "BUY"
    return "STRONG_BUY"


def to_analyst_rating_label(mark: float | None) -> str | None:
    """Map TradingView consensus analyst recommendation mark [1.0 to 3.0] to TradingView's 4 signals."""
    if mark is None:
        return None
    if mark < 1.25:
        return "STRONG_BUY"
    if mark < 2.25:
        return "BUY"
    if mark < 2.75:
        return "SELL"
    return "STRONG_SELL"


def compute_momentum_flag(r1d: str | None, r1w: str | None) -> str | None:
    """Combine 1D and 1W technical recommendations into a momentum flag."""
    if r1d == "STRONG_BUY" and r1w == "STRONG_BUY":
        return "STRONG_BUY_BOTH"
    if r1d == "STRONG_SELL" and r1w == "STRONG_SELL":
        return "STRONG_SELL_BOTH"
    if r1d == "STRONG_BUY":
        return "STRONG_BUY_1D"
    if r1w == "STRONG_BUY":
        return "STRONG_BUY_1W"
    if r1d == "STRONG_SELL":
        return "STRONG_SELL_1D"
    if r1w == "STRONG_SELL":
        return "STRONG_SELL_1W"
    return None


def _parse_tradingview_response_data(
    data: dict[str, Any], tv_symbol_to_sym: dict[str, str], results: dict[str, dict[str, Any]]
) -> None:
    for item in data.get("data", []):
        tv_key = item.get("s")
        sym = tv_symbol_to_sym.get(tv_key)
        if not sym:
            continue
        d = item.get("d", [])
        v1d = d[0] if len(d) > 0 and d[0] is not None else None
        v1w = d[1] if len(d) > 1 and d[1] is not None else None
        v_rec = d[2] if len(d) > 2 and d[2] is not None else None

        r1d = to_recommendation_label(v1d)
        r1w = to_recommendation_label(v1w)
        flag = compute_momentum_flag(r1d, r1w)
        r_analyst = to_analyst_rating_label(v_rec)

        results[sym] = {
            "tv_signal_1d": r1d,
            "tv_signal_1w": r1w,
            "tv_momentum_flag": flag,
            "tv_score_1d": round(v1d, 4) if v1d is not None else None,
            "tv_score_1w": round(v1w, 4) if v1w is not None else None,
            "tv_analyst_rating": r_analyst,
            "tv_analyst_mark": round(v_rec, 4) if v_rec is not None else None,
        }


async def fetch_live_tradingview_signals_async(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch 1D, 1W technical indicators and analyst rating in parallel with async HTTP."""
    if not symbols:
        return {}

    tv_symbol_to_sym: dict[str, str] = {}
    tickers: list[str] = []
    for s in symbols:
        sanitized = s.upper().replace("-", "_")
        tv_sym = f"NSE:{sanitized}"
        tv_symbol_to_sym[tv_sym] = s.upper()
        tickers.append(tv_sym)

    cols = ["Recommend.All", "Recommend.All|1W", "recommendation_mark"]
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    results: dict[str, dict[str, Any]] = {}
    chunk_size = 500

    chunks = [tickers[i : i + chunk_size] for i in range(0, len(tickers), chunk_size)]

    async with httpx.AsyncClient(timeout=10.0) as client:
        async def fetch_chunk(chunk: list[str]) -> None:
            payload = {"symbols": {"tickers": chunk}, "columns": cols}
            try:
                resp = await client.post(TRADINGVIEW_SCAN_URL, json=payload, headers=headers)
                if resp.status_code == 200:
                    _parse_tradingview_response_data(resp.json(), tv_symbol_to_sym, results)
                else:
                    logger.warning(f"TradingView scanner returned HTTP {resp.status_code}")
            except Exception as exc:
                logger.warning(f"Failed to fetch TradingView signals chunk: {exc}")

        await asyncio.gather(*[fetch_chunk(c) for c in chunks])

    return results


def fetch_live_tradingview_signals(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch 1D, 1W technical indicators and analyst rating from TradingView scanner synchronously."""
    if not symbols:
        return {}

    tv_symbol_to_sym: dict[str, str] = {}
    tickers: list[str] = []
    for s in symbols:
        sanitized = s.upper().replace("-", "_")
        tv_sym = f"NSE:{sanitized}"
        tv_symbol_to_sym[tv_sym] = s.upper()
        tickers.append(tv_sym)

    cols = ["Recommend.All", "Recommend.All|1W", "recommendation_mark"]
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    results: dict[str, dict[str, Any]] = {}
    chunk_size = 500

    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        payload = {"symbols": {"tickers": chunk}, "columns": cols}
        try:
            resp = requests.post(TRADINGVIEW_SCAN_URL, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                _parse_tradingview_response_data(resp.json(), tv_symbol_to_sym, results)
            else:
                logger.warning(f"TradingView scanner returned HTTP {resp.status_code}")
        except Exception as exc:
            logger.warning(f"Failed to fetch TradingView signals chunk: {exc}")

    return results


async def get_universe_tradingview_signals(
    symbols: list[str] | None = None, force_refresh: bool = False
) -> dict[str, dict[str, Any]]:
    """Retrieve universe TradingView signals with Redis caching and parallel async fetch."""
    if not force_refresh:
        cached = await cache.get_json(TV_SIGNALS_CACHE_KEY)
        if cached is not None and isinstance(cached, dict):
            return cached

    if symbols is None:
        from sqlalchemy import select
        from packages.common.db import session_scope
        from packages.common.models import Instrument

        async with session_scope() as session:
            stmt = select(Instrument.symbol).where(Instrument.active.is_(True), Instrument.instrument_type == "EQUITY")
            symbols = (await session.execute(stmt)).scalars().all()

    fresh_signals = await fetch_live_tradingview_signals_async(symbols)
    if fresh_signals:
        await cache.set_json(TV_SIGNALS_CACHE_KEY, fresh_signals, TV_SIGNALS_CACHE_TTL)

    return fresh_signals


async def get_single_tradingview_signal(symbol: str) -> dict[str, Any]:
    """Retrieve TradingView signal for a single symbol with fast path."""
    sym_clean = symbol.upper()
    cached_univ = await cache.get_json(TV_SIGNALS_CACHE_KEY)
    if cached_univ and isinstance(cached_univ, dict) and sym_clean in cached_univ:
        return cached_univ[sym_clean]

    single_key = f"tradingview_signal:single:{sym_clean}"
    cached_single = await cache.get_json(single_key)
    if cached_single and isinstance(cached_single, dict):
        return cached_single

    try:
        fresh = await asyncio.wait_for(fetch_live_tradingview_signals_async([sym_clean]), timeout=1.5)
        sig = fresh.get(sym_clean, {})
        if sig:
            await cache.set_json(single_key, sig, TV_SIGNALS_CACHE_TTL)
        return sig
    except Exception as exc:
        logger.warning(f"Timeout or failure fetching live TV signal for {sym_clean}: {exc}")
        return {}

