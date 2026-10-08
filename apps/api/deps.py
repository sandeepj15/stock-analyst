"""Shared FastAPI route helpers (SPEC.md section 48).

Factored out of `apps/api/routes/instruments.py` so the new
`apps/api/routes/stocks.py` endpoints resolve symbols the same way
instead of re-implementing the lookup.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.models import Instrument, InstrumentAlias


class InstrumentNotFoundError(Exception):
    """Raised by `resolve_instrument` - routes translate this to a 404."""

    def __init__(self, symbol: str, exchange: str) -> None:
        self.symbol = symbol
        self.exchange = exchange
        super().__init__(f"Instrument {exchange}:{symbol} not found")


async def resolve_instrument(session: AsyncSession, symbol: str, exchange: str = "NSE") -> Instrument:
    """Look up an `Instrument` by (symbol, exchange), case-insensitively on symbol/exchange.

    Falls back to `instrument_aliases` (SPEC.md section 45) when there is
    no direct match - this is what makes a renamed instrument (SPEC.md
    section 11 "symbol changes", see
    `packages/market_data/corporate_actions.py`) still resolve under its
    old symbol, e.g. `ZOMATO` still finds the instrument now listed as
    `ETERNAL`.

    Raises `InstrumentNotFoundError` (never returns `None`) so callers
    can't accidentally forget the 404 check.
    """
    stmt = select(Instrument).where(Instrument.symbol == symbol.upper(), Instrument.exchange == exchange.upper())
    result = await session.execute(stmt)
    instrument = result.scalar_one_or_none()
    if instrument is not None:
        return instrument

    alias_stmt = select(InstrumentAlias).where(
        InstrumentAlias.symbol == symbol.upper(), InstrumentAlias.exchange == exchange.upper()
    )
    alias = (await session.execute(alias_stmt)).scalar_one_or_none()
    if alias is not None:
        aliased = await session.get(Instrument, alias.instrument_id)
        if aliased is not None:
            return aliased

    raise InstrumentNotFoundError(symbol, exchange)


async def resolve_instrument_or_404(session: AsyncSession, symbol: str, exchange: str = "NSE") -> Instrument:
    """Same as `resolve_instrument`, but raises `HTTPException(404)` directly.

    New Phase 3 route modules (`fundamentals.py`, `market.py`, `scoring.py`)
    use this instead of each re-implementing the try/except
    `InstrumentNotFoundError` -> `HTTPException` translation that
    `apps/api/routes/stocks.py` does inline.
    """
    try:
        return await resolve_instrument(session, symbol, exchange)
    except InstrumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
