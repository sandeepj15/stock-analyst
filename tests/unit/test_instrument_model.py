"""Instrument master constraint tests (SPEC.md section 9)."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from packages.common.models import Instrument


@pytest.mark.asyncio
async def test_exchange_symbol_unique_constraint(db_session):
    db_session.add(Instrument(symbol="TCS", exchange="NSE", company_name="Tata Consultancy Services Ltd"))
    await db_session.commit()

    db_session.add(Instrument(symbol="TCS", exchange="NSE", company_name="Duplicate TCS"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_same_symbol_different_exchange_is_allowed(db_session):
    db_session.add(Instrument(symbol="TCS", exchange="NSE", company_name="Tata Consultancy Services Ltd"))
    db_session.add(Instrument(symbol="TCS", exchange="BSE", company_name="Tata Consultancy Services Ltd"))
    await db_session.commit()  # must not raise


@pytest.mark.asyncio
async def test_isin_unique_when_present(db_session):
    db_session.add(
        Instrument(symbol="TCS", exchange="NSE", company_name="TCS", isin="INE467B01029")
    )
    await db_session.commit()

    db_session.add(
        Instrument(symbol="TCS2", exchange="NSE", company_name="Fake Dup", isin="INE467B01029")
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
