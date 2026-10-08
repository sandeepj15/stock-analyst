"""Known NSE symbol-change corporate actions (SPEC.md section 11, 45).

SPEC.md section 11 lists "symbol changes" as a corporate-action type the
data-quality layer must detect, and section 45 lists `instrument_aliases`
as a core table for exactly this reason: a renamed instrument must keep
its history/evidence/scores attached to the *same* `instruments.id` row,
while the old symbol must still resolve for anyone searching it.

This module hardcodes the small, specific set of renames discovered and
verified (live, against real yfinance/Yahoo Finance data, and
cross-checked against NSE's own published Nifty Total Market constituent
file - see `packages/market_data/universe.py`) while root-causing why
TATAMOTORS/LTIM/ZOMATO had zero ingested OHLCV. This is deliberately NOT
a general corporate-action detector (that would require a licensed
corporate-actions feed to do properly, SPEC.md section 8) - it is a
documented, evidence-backed patch for three specific, confirmed renames.

## What was verified (live, Oct 2026) and why

- **ZOMATO -> ETERNAL**: `ZOMATO.NS` 404s on Yahoo Finance's chart
  endpoint. `ETERNAL.NS` resolves with `longName="Eternal Limited"` and
  continuous daily history. This is the well-known 2024 Zomato Ltd ->
  Eternal Ltd corporate rename. Confirmed again independently via NSE's
  own `ind_niftytotalmarket_list.csv`, which lists `ETERNAL` (not
  `ZOMATO`) with ISIN `INE758T01015`.

- **LTIM -> LTM**: `LTIM.NS` 404s on Yahoo Finance (both the chart
  endpoint and the finance search endpoint return zero results for
  "LTIMindtree"/"Mindtree" - this is not a transient/network issue, it
  is a clean "this symbol no longer exists" response). Yahoo Finance's
  search index resolves `LTM.NS` ("LTM Limited") with `prevName:
  "Larsen & Toubro Infotech Limited"` and ~10 years of continuous daily
  history (2016-2026) at the correct price scale for the former
  LTIMindtree. NSE's own constituent file independently lists `LTM`
  (ISIN `INE214T01019`, the same ISIN L&T Infotech/LTIMindtree has
  always traded under) instead of `LTIM`. This is a straightforward
  rename, not a demerger.

- **TATAMOTORS -> TMPV (not a simple rename - a demerger)**: `TATAMOTORS.NS`
  404s on Yahoo Finance. Yahoo's search index shows **two** successor
  tickers: `TMPV.NS` ("Tata Motors Passenger Vehicles Limited",
  `prevName: "Tata Motors Limited"`, ~35 years of continuous daily
  history 1991-2026 at the correct price scale/continuity for the
  original Tata Motors entity) and `TMCV.NS` ("Tata Motors Limited" -
  yes, the *new* entity kept the old brand name - with only ~10 months
  of history (first bar 2025-11-12 per the actual backfill, consistent
  with Indian demerger practice where the new entity trades
  "when-issued" for a period before full listing), i.e. a recently-
  listed company with genuinely limited history, not 2 years). NSE's
  constituent file confirms both are now independently listed: `TMPV`
  under ISIN `INE155A01022` (the pre-existing Tata Motors ISIN) and
  `TMCV` under a brand-new ISIN `INE1TAE01010`. Conclusion: the demerger
  split the original listed entity into (a) the passenger-vehicles
  business, which **kept the original listing/ISIN/history** and was
  simply renamed+re-ticker'd to TMPV, and (b) a **newly incorporated and
  listed** commercial-vehicles entity, TMCV, which has no prior history
  to backfill under any free source. This fix therefore repoints the
  existing `TATAMOTORS` instrument row (preserving its 2 years of
  existing OHLCV/scores/evidence under the same `instruments.id`) to
  TMPV, and leaves TMCV to be seeded as a brand-new, separate instrument
  by the universe backfill (SPEC.md section 81 rule 23 - its lack of
  deep history is a genuine, honestly-reported gap, not something to
  paper over by pretending it is a continuation of TATAMOTORS).

None of the three were a transient ingestion failure - the original
seed run was correctly failing on all three because the symbols
genuinely no longer resolve on Yahoo Finance.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.common.models import Instrument, InstrumentAlias

logger = logging.getLogger(__name__)

EXCHANGE = "NSE"


@dataclass(frozen=True)
class SymbolChange:
    old_symbol: str
    new_symbol: str
    new_company_name: str
    note: str


# Verified live against Yahoo Finance + cross-checked against NSE's own
# ind_niftytotalmarket_list.csv (see module docstring above). Dates are
# approximate/best-known, not asserted with false precision.
KNOWN_SYMBOL_CHANGES: tuple[SymbolChange, ...] = (
    SymbolChange(
        old_symbol="ZOMATO",
        new_symbol="ETERNAL",
        new_company_name="Eternal Ltd",
        note="Zomato Ltd renamed to Eternal Ltd (2024 corporate rename, confirmed on NSE + Yahoo Finance).",
    ),
    SymbolChange(
        old_symbol="LTIM",
        new_symbol="LTM",
        new_company_name="LTM Ltd",
        note="LTIMindtree Ltd renamed to LTM Ltd (ticker LTIM -> LTM); same ISIN/listing continuity.",
    ),
    SymbolChange(
        old_symbol="TATAMOTORS",
        new_symbol="TMPV",
        new_company_name="Tata Motors Passenger Vehicles Ltd",
        note=(
            "Tata Motors demerger: the original listed entity (full price history, same ISIN) "
            "was renamed/re-ticker'd to TMPV (passenger vehicles). The commercial-vehicles "
            "demerged entity (TMCV) is a brand-new listing with no prior history - seeded "
            "separately as a new instrument, not treated as a TATAMOTORS alias."
        ),
    ),
)


@dataclass
class RenameOutcome:
    old_symbol: str
    new_symbol: str
    applied: bool
    reason: str


async def apply_known_symbol_renames(session: AsyncSession) -> list[RenameOutcome]:
    """Repoint any existing `TATAMOTORS`/`LTIM`/`ZOMATO` instrument rows to their
    current live ticker, preserving `instruments.id` (and therefore all
    existing OHLCV/fundamentals/scores/evidence), and record an
    `instrument_aliases` row so the old symbol still resolves.

    Idempotent and order-independent with respect to the universe seed
    (SPEC.md section 57): handles both orderings a seed run can hit -

    1. The old-symbol row already exists (e.g. this DB was originally
       seeded before the rename was known) - rename it in place and add
       the alias.
    2. Only the new-symbol row exists (e.g. a fresh DB seeded straight
       from `universe.py`, which already lists the current ticker) -
       nothing to rename, but still ensure the old-symbol alias exists so
       searching the pre-rename symbol works on a brand-new DB too.

    If neither row exists yet, this is a no-op for that entry (nothing
    to alias to) - the subsequent universe/legacy seed step will create
    the new-symbol instrument, and a second call to this function (e.g.
    next scheduled seed run) will then add the alias per case 2 above.
    """
    outcomes: list[RenameOutcome] = []

    for change in KNOWN_SYMBOL_CHANGES:
        old = (
            await session.execute(
                select(Instrument).where(Instrument.exchange == EXCHANGE, Instrument.symbol == change.old_symbol)
            )
        ).scalar_one_or_none()
        new = (
            await session.execute(
                select(Instrument).where(Instrument.exchange == EXCHANGE, Instrument.symbol == change.new_symbol)
            )
        ).scalar_one_or_none()

        if old is not None and new is not None and old.id != new.id:
            outcomes.append(
                RenameOutcome(
                    change.old_symbol,
                    change.new_symbol,
                    applied=False,
                    reason="both_old_and_new_symbol_exist_as_separate_instruments",
                )
            )
            continue

        target = new if new is not None else old
        if target is None:
            outcomes.append(
                RenameOutcome(change.old_symbol, change.new_symbol, applied=False, reason="neither_symbol_present_yet")
            )
            continue

        if new is None:
            # Case 1: only the old row exists - rename it in place.
            target.symbol = change.new_symbol
            target.company_name = change.new_company_name

        existing_alias = (
            await session.execute(
                select(InstrumentAlias).where(
                    InstrumentAlias.exchange == EXCHANGE, InstrumentAlias.symbol == change.old_symbol
                )
            )
        ).scalar_one_or_none()
        if existing_alias is None:
            session.add(InstrumentAlias(symbol=change.old_symbol, exchange=EXCHANGE, instrument_id=target.id))

        outcomes.append(RenameOutcome(change.old_symbol, change.new_symbol, applied=True, reason=change.note))
        logger.info(
            "corporate_actions: applied known symbol rename",
            extra={"old_symbol": change.old_symbol, "new_symbol": change.new_symbol},
        )

    await session.commit()
    return outcomes
