"""NSE equity universe fetch - "top ~750" via NSE's own published index files.

SPEC.md section 9 (instrument master) wants a real, broad NSE universe
rather than a hand-maintained ~100-symbol list; SPEC.md section 81 rule
25 ("do not add dependencies without justification") and rule 23
("expose limitations, never fabricate") both apply here, so this module
is deliberately built on a free, public, no-API-key, officially-published
source rather than scraping/guessing.

## Source and why it's safe to rely on

Primary source: NSE's own "Nifty Total Market Index" constituent CSV,
published at:

    https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv

The Nifty Total Market Index is NSE Indices Ltd's (NSE's index
subsidiary) broad-market benchmark - it is *defined* as the top ~750
NSE-listed companies by free-float market cap (Nifty 500 + Nifty
Microcap 250, deduplicated). NSE Indices publishes this constituent file
on its own public website, refreshed periodically (index reconstitution
is semi-annual; the file itself is kept current between reconstitutions
for corporate actions), with no authentication, no API key, and no rate
limit beyond "don't hammer it" - exactly the kind of source SPEC.md
section 8/105 wants for local development. Verified live (Oct 2026): the
file returns ~755 rows with `Company Name`, `Industry`, `Symbol`,
`Series`, and `ISIN Code` columns, and it already reflects very recent
corporate actions (e.g. ZOMATO -> ETERNAL, LTIM -> LTM, the Tata Motors
demerger into TMPV/TMCV - see `packages/market_data/corporate_actions.py`),
which is exactly the kind of up-to-date reference list this project
needs.

## Fallback and provenance

This is the same *style* of source the sibling reference project
(`laya-stock-intelligence/ai_stock_agent_1d_1w.py::get_nse_tickers_fast`)
uses - it fetches `ind_nifty500list.csv` + `ind_niftymicrocap250_list.csv`
from the same `niftyindices.com` host and unions them (deduplicated via
`set()`) to approximate the same ~750-name universe. That two-file
combination is used here as the documented *fallback* if the single
`ind_niftytotalmarket_list.csv` file is ever unavailable, since it is a
strictly more conservative, already-proven version of the same
technique (same host, same free/public/no-key properties, same project
author's own prior work - not a third party's).

Both approaches are the officially-published index-constituent files;
neither scrapes, screen-scrapes, or infers a universe from an unofficial
screener.
"""
from __future__ import annotations

import csv
import io
import logging

import requests
from pydantic import BaseModel, ConfigDict

from packages.common.rate_limit import RetryPolicy, call_with_retry

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT_SECONDS = 30.0

NIFTY_TOTAL_MARKET_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"
NIFTY_500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
NIFTY_MICROCAP_250_URL = "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv"


class UniverseInstrument(BaseModel):
    """One NSE-listed equity from the published index-constituent universe.

    `sector` is left `None` - NSE's constituent files publish an
    `Industry` classification (NSE's own sector/industry taxonomy), not a
    GICS-style sector label, and this project must never invent a
    sector/industry mapping that wasn't actually provided (SPEC.md
    section 81 rule 2/8). `industry` carries that raw NSE classification
    instead.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    company_name: str
    industry: str | None = None
    isin: str | None = None


def _fetch_csv_rows(url: str, *, retry_policy: RetryPolicy) -> list[dict[str, str]]:
    """Fetch and parse one NSE index-constituent CSV, with retry-with-backoff.

    SPEC.md section 59: every external call has a timeout (`timeout=`)
    and a retry policy (`call_with_retry`). Raises on exhausted retries -
    callers decide whether that's fatal (see `fetch_nse_universe`'s
    primary/fallback logic).
    """

    def _do_request() -> list[dict[str, str]]:
        response = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=_REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        if not rows:
            raise ValueError(f"NSE index-constituent CSV at {url} parsed to zero rows")
        return rows

    return call_with_retry(
        _do_request,
        policy=retry_policy,
        retry_on=(requests.RequestException, ValueError),
        on_retry=lambda attempt, exc: logger.warning(
            "universe: retrying NSE CSV fetch", extra={"url": url, "attempt": attempt, "error": str(exc)}
        ),
    )


def _rows_to_instruments(rows: list[dict[str, str]]) -> list[UniverseInstrument]:
    instruments: list[UniverseInstrument] = []
    for row in rows:
        symbol = (row.get("Symbol") or "").strip().upper()
        company_name = (row.get("Company Name") or "").strip()
        if not symbol or not company_name:
            continue  # malformed row - never fabricate a symbol/name, just skip it
        instruments.append(
            UniverseInstrument(
                symbol=symbol,
                company_name=company_name,
                industry=(row.get("Industry") or "").strip() or None,
                isin=(row.get("ISIN Code") or "").strip() or None,
            )
        )
    return instruments


def fetch_nse_universe(*, retry_policy: RetryPolicy | None = None) -> list[UniverseInstrument]:
    """Return the ~750-symbol NSE "Nifty Total Market" equity universe.

    Tries the single combined `ind_niftytotalmarket_list.csv` file first.
    If that fails after retries (network issue, NSE Indices site down,
    file temporarily missing), falls back to fetching and deduplicating
    `ind_nifty500list.csv` + `ind_niftymicrocap250_list.csv` - the same
    technique the sibling `laya-stock-intelligence` project uses for the
    same purpose. If *both* fail, raises rather than returning a
    fabricated/partial/stale universe (SPEC.md section 81 rule 23) -
    callers (the seed script) must surface that honestly.
    """
    policy = retry_policy or RetryPolicy(max_attempts=3, base_delay_seconds=2.0, max_delay_seconds=8.0)

    try:
        rows = _fetch_csv_rows(NIFTY_TOTAL_MARKET_URL, retry_policy=policy)
        instruments = _rows_to_instruments(rows)
        logger.info("universe: fetched Nifty Total Market list", extra={"count": len(instruments)})
        return instruments
    except Exception as exc:
        logger.warning(
            "universe: ind_niftytotalmarket_list.csv fetch failed, falling back to "
            "nifty500 + microcap250 union",
            extra={"error": str(exc)},
        )

    nifty500_rows = _fetch_csv_rows(NIFTY_500_URL, retry_policy=policy)
    try:
        microcap_rows = _fetch_csv_rows(NIFTY_MICROCAP_250_URL, retry_policy=policy)
    except Exception as exc:
        logger.warning(
            "universe: microcap250 fetch failed, continuing with nifty500 only",
            extra={"error": str(exc)},
        )
        microcap_rows = []

    merged_by_symbol: dict[str, dict[str, str]] = {}
    for row in (*nifty500_rows, *microcap_rows):
        symbol = (row.get("Symbol") or "").strip().upper()
        if symbol:
            merged_by_symbol.setdefault(symbol, row)

    instruments = _rows_to_instruments(list(merged_by_symbol.values()))
    logger.info(
        "universe: fetched fallback nifty500+microcap250 union",
        extra={"count": len(instruments), "nifty500_rows": len(nifty500_rows), "microcap_rows": len(microcap_rows)},
    )
    return instruments
