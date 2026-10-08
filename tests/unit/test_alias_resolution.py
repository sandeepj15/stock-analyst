"""Instrument-alias resolution tests (SPEC.md sections 11, 45).

Proves that a renamed instrument (e.g. ZOMATO -> ETERNAL) can still be
found by searching its old symbol - the whole point of
`instrument_aliases` and `apps.api.deps.resolve_instrument`'s alias
fallback. Also exercises `packages.market_data.corporate_actions.
apply_known_symbol_renames` end to end, DB-backed, no network.
"""
from __future__ import annotations

import pytest

from apps.api.deps import InstrumentNotFoundError, resolve_instrument
from packages.common.models import Instrument, InstrumentAlias
from packages.market_data.corporate_actions import apply_known_symbol_renames


@pytest.mark.asyncio
async def test_resolve_instrument_finds_direct_symbol_match(db_session):
    db_session.add(Instrument(symbol="TCS", exchange="NSE", company_name="Tata Consultancy Services Ltd"))
    await db_session.commit()

    instrument = await resolve_instrument(db_session, "TCS", "NSE")
    assert instrument.symbol == "TCS"


@pytest.mark.asyncio
async def test_resolve_instrument_falls_back_to_alias(db_session):
    renamed = Instrument(symbol="ETERNAL", exchange="NSE", company_name="Eternal Ltd")
    db_session.add(renamed)
    await db_session.flush()
    db_session.add(InstrumentAlias(symbol="ZOMATO", exchange="NSE", instrument_id=renamed.id))
    await db_session.commit()

    # Searching the OLD symbol must still resolve to the renamed instrument.
    found = await resolve_instrument(db_session, "ZOMATO", "NSE")
    assert found.id == renamed.id
    assert found.symbol == "ETERNAL"

    # The new symbol must also resolve directly (not just via alias).
    found_direct = await resolve_instrument(db_session, "ETERNAL", "NSE")
    assert found_direct.id == renamed.id


@pytest.mark.asyncio
async def test_resolve_instrument_raises_when_neither_symbol_nor_alias_exists(db_session):
    with pytest.raises(InstrumentNotFoundError):
        await resolve_instrument(db_session, "NOPE", "NSE")


@pytest.mark.asyncio
async def test_apply_known_symbol_renames_repoints_existing_row_and_adds_alias(db_session):
    """Case 1: the DB has the old-symbol row (as an older seed run would) - rename in place."""
    old = Instrument(symbol="ZOMATO", exchange="NSE", company_name="Zomato Ltd")
    db_session.add(old)
    await db_session.flush()
    old_id = old.id

    outcomes = await apply_known_symbol_renames(db_session)

    zomato_outcome = next(o for o in outcomes if o.old_symbol == "ZOMATO")
    assert zomato_outcome.applied is True

    renamed = await db_session.get(Instrument, old_id)
    assert renamed.symbol == "ETERNAL"
    assert renamed.company_name == "Eternal Ltd"

    found = await resolve_instrument(db_session, "ZOMATO", "NSE")
    assert found.id == old_id


@pytest.mark.asyncio
async def test_apply_known_symbol_renames_is_idempotent(db_session):
    old = Instrument(symbol="LTIM", exchange="NSE", company_name="LTIMindtree Ltd")
    db_session.add(old)
    await db_session.flush()

    first = await apply_known_symbol_renames(db_session)
    second = await apply_known_symbol_renames(db_session)

    ltim_first = next(o for o in first if o.old_symbol == "LTIM")
    ltim_second = next(o for o in second if o.old_symbol == "LTIM")
    assert ltim_first.applied is True
    assert ltim_second.applied is True  # still "applied" (alias confirmed present), not an error

    # Exactly one alias row, not duplicated across the two runs.
    from sqlalchemy import select

    aliases = (
        await db_session.execute(select(InstrumentAlias).where(InstrumentAlias.symbol == "LTIM"))
    ).scalars().all()
    assert len(aliases) == 1


@pytest.mark.asyncio
async def test_apply_known_symbol_renames_on_fresh_db_seeded_with_new_symbol_only(db_session):
    """Case 2: a brand-new DB seeded straight from the universe already has TMPV, never TATAMOTORS."""
    fresh = Instrument(symbol="TMPV", exchange="NSE", company_name="Tata Motors Passenger Vehicles Ltd")
    db_session.add(fresh)
    await db_session.flush()
    fresh_id = fresh.id

    outcomes = await apply_known_symbol_renames(db_session)
    outcome = next(o for o in outcomes if o.old_symbol == "TATAMOTORS")
    assert outcome.applied is True

    # Old symbol now resolves via the alias to the already-correct row.
    found = await resolve_instrument(db_session, "TATAMOTORS", "NSE")
    assert found.id == fresh_id
    assert found.symbol == "TMPV"


@pytest.mark.asyncio
async def test_apply_known_symbol_renames_noop_when_neither_symbol_present(db_session):
    outcomes = await apply_known_symbol_renames(db_session)
    outcome = next(o for o in outcomes if o.old_symbol == "ZOMATO")
    assert outcome.applied is False
    assert outcome.reason == "neither_symbol_present_yet"
