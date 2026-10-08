"""Sector relative strength computation (SPEC.md section 16).

Extracted from `apps/api/routes/stocks.py` so the Research Score engine
(SPEC.md section 17-18, `packages/scoring/components.py`) can reuse the
exact same computation instead of duplicating it, per the Phase 3 build
instructions ("reuse the existing /relative-strength computation
directly"). The API route is now a thin adapter over this function - see
`apps/api/routes/stocks.py::get_relative_strength`.

This is **not** a real sector index - "sector return" is the simple
average return of other seeded instruments sharing the same
`Instrument.sector`, within the ~117-instrument dev universe only. Every
result carries `peer_universe = "seeded_sector_peers"` so it is never
mistaken for a licensed sector benchmark (SPEC.md sections 2.3, 21, 81
rule 23).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.models import Instrument
from packages.market_data.history import load_ohlcv_dataframe

PEER_UNIVERSE_LABEL = "seeded_sector_peers"

RELATIVE_STRENGTH_LOOKBACKS: dict[str, int] = {
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
}


@dataclass(frozen=True)
class RelativeStrengthHorizonResult:
    stock_return_pct: float | None
    peer_avg_return_pct: float | None
    relative_strength_pct: float | None
    reason: str | None


@dataclass(frozen=True)
class RelativeStrengthResult:
    sector: str | None
    peer_universe: str
    peer_count: int
    peer_symbols: list[str]
    as_of_date: str | None
    metrics: dict[str, RelativeStrengthHorizonResult]
    stock_df: pd.DataFrame  # exposed so callers (e.g. the API route) can derive data_freshness without re-querying


def _return_over_bars(close: pd.Series, bars: int) -> float | None:
    """Percent return from `bars` trading days ago to the latest bar, or `None` if insufficient history."""
    if len(close) <= bars:
        return None
    latest = close.iloc[-1]
    base = close.iloc[-1 - bars]
    if base == 0:
        return None
    return float((latest / base - 1.0) * 100.0)


async def compute_relative_strength(session: AsyncSession, instrument: Instrument) -> RelativeStrengthResult:
    """Compute sector-relative-strength metrics for `instrument` across every horizon.

    Returns `stock_df` (the instrument's own OHLCV, already loaded) too,
    so callers don't have to issue a second query just to compute
    freshness/as-of-date.
    """
    stock_df = await load_ohlcv_dataframe(session, instrument.id)
    stock_close = stock_df["adjusted_close"] if not stock_df.empty else pd.Series(dtype=float)

    peer_symbols: list[str] = []
    peer_closes: dict[str, pd.Series] = {}

    if instrument.sector:
        peer_stmt = select(Instrument).where(
            Instrument.exchange == instrument.exchange,
            Instrument.sector == instrument.sector,
            Instrument.id != instrument.id,
            Instrument.active.is_(True),
        )
        peer_result = await session.execute(peer_stmt)
        peers = peer_result.scalars().all()
        peer_symbols = sorted(p.symbol for p in peers)

        for peer in peers:
            peer_df = await load_ohlcv_dataframe(session, peer.id)
            if not peer_df.empty:
                peer_closes[peer.symbol] = peer_df["adjusted_close"]

    insufficient_universe = instrument.sector is None or len(peer_symbols) < 2

    metrics: dict[str, RelativeStrengthHorizonResult] = {}
    for horizon, bars in RELATIVE_STRENGTH_LOOKBACKS.items():
        stock_return = _return_over_bars(stock_close, bars)

        if insufficient_universe:
            metrics[horizon] = RelativeStrengthHorizonResult(
                stock_return_pct=stock_return,
                peer_avg_return_pct=None,
                relative_strength_pct=None,
                reason="insufficient_peer_universe",
            )
            continue

        if stock_return is None:
            metrics[horizon] = RelativeStrengthHorizonResult(
                stock_return_pct=None,
                peer_avg_return_pct=None,
                relative_strength_pct=None,
                reason="insufficient_price_history",
            )
            continue

        peer_returns = [
            r for close in peer_closes.values() if (r := _return_over_bars(close, bars)) is not None
        ]
        if not peer_returns:
            metrics[horizon] = RelativeStrengthHorizonResult(
                stock_return_pct=stock_return,
                peer_avg_return_pct=None,
                relative_strength_pct=None,
                reason="insufficient_price_history",
            )
            continue

        peer_avg = sum(peer_returns) / len(peer_returns)
        metrics[horizon] = RelativeStrengthHorizonResult(
            stock_return_pct=stock_return,
            peer_avg_return_pct=peer_avg,
            relative_strength_pct=stock_return - peer_avg,
            reason=None,
        )

    return RelativeStrengthResult(
        sector=instrument.sector,
        peer_universe=PEER_UNIVERSE_LABEL,
        peer_count=len(peer_symbols),
        peer_symbols=peer_symbols,
        as_of_date=stock_df["trading_date"].iloc[-1].isoformat() if not stock_df.empty else None,
        metrics=metrics,
        stock_df=stock_df,
    )
