"""screener.in HTML-backed `FundamentalDataProvider` (SPEC.md sections 8, 12).

**Why this exists**: yfinance's NSE coverage is thin for many balance-sheet
fields (see `yfinance_fundamental_provider.py`'s docstring) and its
`quarterly_income_stmt` typically exposes only ~5-6 trailing quarters.
screener.in's condensed annual/quarterly tables cover far more history and
are built specifically for Indian equities. This provider fills those gaps
as a `CompositeFundamentalProvider` fallback (annual) and primary
(quarterly) - see `packages/fundamentals/factory.py`.

**Scraping posture (personal research use, re-checked explicitly before
building this)**: `https://www.screener.in/robots.txt` disallows `/user/*`
and a handful of query-param/internal paths, but does **not** disallow
`/company/*` - the exact pages this provider reads. This provider is a
single lightweight GET per instrument (no JS, no auth bypass, no bulk
crawling), identifies itself via `User-Agent`, and syncs run only a
handful of times a year per instrument (see `sync_quarterly_fundamentals_job`/
`sync_fundamentals_job` docstrings - never part of the daily cron). screener.in's
full Terms of Service text was not independently reviewed beyond
robots.txt; this is a documented, deliberate choice for a personal/local
research tool, not a redistributed commercial product (same posture this
codebase already takes with yfinance's own non-commercial-redistribution
caveat - see that provider's docstring).

**Unit handling**: each screener.in table is explicitly labeled "Figures
in Rs. Crores" or "Rs. Lakhs" near its heading - this provider reads that
label per-section and multiplies by 1e7 (Crores) or 1e5 (Lakhs)
accordingly, never assuming a fixed unit. Cross-validated live (Oct 2026):
RELIANCE's screener.in Jun-2026 quarterly Sales of "309,468" (Rs. Crores)
x 1e7 == 3,094,680,000,000, which is exactly yfinance's own figure for
the same quarter.

**Scope, v1**: only `revenue`/`pat` (quarterly and annual) and
`equity`/`total_debt`/`total_liabilities`/`total_assets` (annual only,
from the balance sheet) are populated - these are the fields screener.in's
condensed tables expose unambiguously. `ebitda`/`ebit`/`eps`/cash-flow
fields and `current_assets`/`current_liabilities` are left `None`:
screener.in's "Operating Profit" row needs netting against Depreciation to
reach EBIT (not scraped here to avoid a half-correct mapping), and its
balance sheet - like yfinance's - has no current/non-current liability
split for Indian companies (a genuine reporting-format gap, not fixable by
switching providers; see DATA_SOURCES.md).
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime

import httpx
from bs4 import BeautifulSoup, Tag

from packages.fundamentals.base import FundamentalSnapshotData

logger = logging.getLogger(__name__)

SOURCE_NAME = "screener_in"
BASE_URL = "https://www.screener.in"
USER_AGENT = "SignalForge/1.0 (personal research tool, non-commercial)"
REQUEST_TIMEOUT_SECONDS = 15.0

_MONTH_END_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_UNIT_MULTIPLIER = {"crores": 1e7, "lakhs": 1e5}

_ONCLICK_LABEL_RE = re.compile(r"Company\.showSchedule\('([^']+)'")
_UNIT_RE = re.compile(r"Rs\.\s*(Crores|Lakhs)", re.IGNORECASE)


def _row_label(cell: Tag) -> str:
    """The row's canonical label - from the `showSchedule('<label>', ...)` button if present, else the cell's own text.

    The button-based label is exact and whitespace-independent; rows
    without an expandable schedule (e.g. "Total Assets") have no button,
    so this falls back to the cell's stripped text.
    """
    button = cell.find("button")
    if button is not None:
        m = _ONCLICK_LABEL_RE.search(button.get("onclick", ""))
        if m:
            return m.group(1)
    return cell.get_text(strip=True)


def _parse_number(text: str) -> float | None:
    """`"309,468"` -> `309468.0`; `"-"`/`""` (screener's own "no value" marker) -> `None`."""
    cleaned = text.strip().replace(",", "")
    if not cleaned or cleaned in ("-", "—"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _month_year_to_period_end(text: str) -> date | None:
    """`"Mar 2024"` -> `date(2024, 3, 31)`. `None` for anything else (e.g. the "TTM" column)."""
    parts = text.strip().split()
    if len(parts) != 2:
        return None
    month = _MONTH_NUM.get(parts[0].lower()[:3])
    if month is None:
        return None
    try:
        year = int(parts[1])
    except ValueError:
        return None
    return date(year, month, _MONTH_END_DAY[month])


def _section_unit_multiplier(section: Tag) -> float | None:
    """Read the "Figures in Rs. Crores"/"Rs. Lakhs" label - `None` if neither is found (never assume a unit)."""
    sub = section.find("p", class_="sub")
    text = sub.get_text(" ", strip=True) if sub is not None else section.get_text(" ", strip=True)
    m = _UNIT_RE.search(text)
    return _UNIT_MULTIPLIER[m.group(1).lower()] if m else None


def _row_values(row: Tag) -> tuple[str, list[float | None]] | None:
    label_cell = row.find("td", class_="text")
    if label_cell is None:
        return None
    label = _row_label(label_cell)
    value_cells = row.find_all("td")[1:]
    return label, [_parse_number(c.get_text()) for c in value_cells]


def _parse_quarterly_table(section: Tag) -> list[tuple[date, float | None, float | None]]:
    """`#quarters` section -> `[(period_end, revenue, pat), ...]`, oldest first (as rendered)."""
    table = section.find("table")
    if table is None:
        return []
    multiplier = _section_unit_multiplier(section)
    if multiplier is None:
        return []

    header_cells = table.find("thead").find_all("th")[1:]
    period_ends = [
        date.fromisoformat(key) if (key := th.get("data-date-key")) and key != "TTM" else None
        for th in header_cells
    ]

    revenue_by_col: list[float | None] = [None] * len(period_ends)
    pat_by_col: list[float | None] = [None] * len(period_ends)
    for row in table.find("tbody").find_all("tr", recursive=False):
        parsed = _row_values(row)
        if parsed is None:
            continue
        label, values = parsed
        if label == "Sales":
            revenue_by_col = values
        elif label == "Net Profit":
            pat_by_col = values

    results: list[tuple[date, float | None, float | None]] = []
    for i, period_end in enumerate(period_ends):
        if period_end is None:
            continue
        revenue = revenue_by_col[i] * multiplier if i < len(revenue_by_col) and revenue_by_col[i] is not None else None
        pat = pat_by_col[i] * multiplier if i < len(pat_by_col) and pat_by_col[i] is not None else None
        if revenue is None and pat is None:
            continue
        results.append((period_end, revenue, pat))
    return results


def _parse_annual_profit_loss(section: Tag) -> list[tuple[date, float | None, float | None]]:
    """`#profit-loss` section -> `[(period_end, revenue, pat), ...]` - the TTM column is skipped (period_type="FY" only)."""
    table = section.find("table")
    if table is None:
        return []
    multiplier = _section_unit_multiplier(section)
    if multiplier is None:
        return []

    header_cells = table.find("thead").find_all("th")[1:]
    period_ends = [_month_year_to_period_end(th.get_text(strip=True)) for th in header_cells]

    revenue_by_col: list[float | None] = [None] * len(period_ends)
    pat_by_col: list[float | None] = [None] * len(period_ends)
    for row in table.find("tbody").find_all("tr", recursive=False):
        parsed = _row_values(row)
        if parsed is None:
            continue
        label, values = parsed
        if label == "Sales":
            revenue_by_col = values
        elif label == "Net Profit":
            pat_by_col = values

    results: list[tuple[date, float | None, float | None]] = []
    for i, period_end in enumerate(period_ends):
        if period_end is None:
            continue
        revenue = revenue_by_col[i] * multiplier if i < len(revenue_by_col) and revenue_by_col[i] is not None else None
        pat = pat_by_col[i] * multiplier if i < len(pat_by_col) and pat_by_col[i] is not None else None
        results.append((period_end, revenue, pat))
    return results


def _parse_balance_sheet(section: Tag) -> dict[date, dict[str, float | None]]:
    """`#balance-sheet` section -> `{period_end: {"equity": ..., "total_debt": ..., ...}}`.

    `equity` (= Equity Capital + Reserves) is only computed when **both**
    rows have a value for that column - if either is missing, `equity`
    stays `None` rather than treating a missing Reserves as 0 (which
    would understate equity for a company where Reserves dwarfs Equity
    Capital, the usual case).
    """
    table = section.find("table")
    if table is None:
        return {}
    multiplier = _section_unit_multiplier(section)
    if multiplier is None:
        return {}

    header_cells = table.find("thead").find_all("th")[1:]
    period_ends = [_month_year_to_period_end(th.get_text(strip=True)) for th in header_cells]

    rows: dict[str, list[float | None]] = {}
    for row in table.find("tbody").find_all("tr", recursive=False):
        parsed = _row_values(row)
        if parsed is None:
            continue
        label, values = parsed
        if label in ("Equity Capital", "Reserves", "Borrowings", "Total Liabilities", "Total Assets"):
            rows[label] = values

    result: dict[date, dict[str, float | None]] = {}
    for i, period_end in enumerate(period_ends):
        if period_end is None:
            continue

        def _at(key: str) -> float | None:
            values = rows.get(key)
            return values[i] if values is not None and i < len(values) else None

        equity_capital = _at("Equity Capital")
        reserves = _at("Reserves")
        equity = (equity_capital + reserves) * multiplier if equity_capital is not None and reserves is not None else None

        result[period_end] = {
            "equity": equity,
            "total_debt": v * multiplier if (v := _at("Borrowings")) is not None else None,
            "total_liabilities": v * multiplier if (v := _at("Total Liabilities")) is not None else None,
            "total_assets": v * multiplier if (v := _at("Total Assets")) is not None else None,
        }
    return result


def _fetch_soup(symbol: str, exchange: str) -> BeautifulSoup | None:
    """Fetch the consolidated company page, falling back to standalone on 404.

    `None` (not an exception) for "no coverage" - unsupported exchange,
    symbol not found on screener.in (404 on both URLs). Network/transport
    failures and non-404 error statuses propagate, per the
    `FundamentalDataProvider` protocol contract.
    """
    if exchange.upper() != "NSE":
        return None

    with httpx.Client(follow_redirects=True) as client:
        for path in (f"/company/{symbol.upper()}/consolidated/", f"/company/{symbol.upper()}/"):
            resp = client.get(f"{BASE_URL}{path}", headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
    return None


class ScreenerInFundamentalProvider:
    """Annual (`period_type="FY"`) `FundamentalDataProvider` backed by screener.in.

    See module docstring for scope/unit/scraping-posture details. Also
    exposes `get_quarterly_fundamental_snapshots` (not part of the
    `FundamentalDataProvider` protocol) - see
    `ScreenerInQuarterlyFundamentalProvider` for the protocol-compliant
    adapter used for quarterly data.
    """

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        try:
            soup = _fetch_soup(symbol, exchange)
        except httpx.HTTPError as exc:
            logger.warning("screener_in annual fetch failed", extra={"symbol": symbol, "error": str(exc)})
            raise
        if soup is None:
            return []

        profit_loss_section = soup.find("section", id="profit-loss")
        if profit_loss_section is None:
            return []
        pl_rows = _parse_annual_profit_loss(profit_loss_section)

        balance_sheet_section = soup.find("section", id="balance-sheet")
        bs_by_period = _parse_balance_sheet(balance_sheet_section) if balance_sheet_section is not None else {}

        now = datetime.now(UTC)
        snapshots: list[FundamentalSnapshotData] = []
        for period_end, revenue, pat in pl_rows:
            bs = bs_by_period.get(period_end, {})
            if revenue is None and pat is None and not any(bs.values()):
                continue
            snapshots.append(
                FundamentalSnapshotData(
                    symbol=symbol.upper(),
                    exchange=exchange.upper(),
                    period_end=period_end,
                    period_type="FY",
                    revenue=revenue,
                    ebitda=None,
                    ebit=None,
                    pat=pat,
                    eps=None,
                    operating_cash_flow=None,
                    free_cash_flow=None,
                    total_assets=bs.get("total_assets"),
                    total_liabilities=bs.get("total_liabilities"),
                    total_debt=bs.get("total_debt"),
                    cash=None,
                    equity=bs.get("equity"),
                    shares_outstanding=None,
                    dividend_yield=None,
                    interest_expense=None,
                    current_assets=None,
                    current_liabilities=None,
                    source=SOURCE_NAME,
                    source_timestamp=now,
                )
            )
        return snapshots

    def get_quarterly_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        try:
            soup = _fetch_soup(symbol, exchange)
        except httpx.HTTPError as exc:
            logger.warning("screener_in quarterly fetch failed", extra={"symbol": symbol, "error": str(exc)})
            raise
        if soup is None:
            return []

        quarters_section = soup.find("section", id="quarters")
        if quarters_section is None:
            return []

        now = datetime.now(UTC)
        return [
            FundamentalSnapshotData(
                symbol=symbol.upper(),
                exchange=exchange.upper(),
                period_end=period_end,
                period_type="Q",
                revenue=revenue,
                ebitda=None,
                ebit=None,
                pat=pat,
                eps=None,
                operating_cash_flow=None,
                free_cash_flow=None,
                total_assets=None,
                total_liabilities=None,
                total_debt=None,
                cash=None,
                equity=None,
                shares_outstanding=None,
                dividend_yield=None,
                interest_expense=None,
                current_assets=None,
                current_liabilities=None,
                source=SOURCE_NAME,
                source_timestamp=now,
            )
            for period_end, revenue, pat in _parse_quarterly_table(quarters_section)
        ]


class ScreenerInQuarterlyFundamentalProvider:
    """`FundamentalDataProvider` adapter exposing `ScreenerInFundamentalProvider`'s quarterly method.

    `FundamentalDataProvider` is a single-method protocol
    (`get_fundamental_snapshots`); screener.in's quarterly data comes from
    a second method on the same underlying provider (one scrape serves
    both annual and quarterly sections), so this thin adapter is what
    `packages/fundamentals/factory.py::get_quarterly_fundamental_provider`
    actually wires up.
    """

    def __init__(self) -> None:
        self._inner = ScreenerInFundamentalProvider()

    def get_fundamental_snapshots(self, symbol: str, exchange: str) -> list[FundamentalSnapshotData]:
        return self._inner.get_quarterly_fundamental_snapshots(symbol, exchange)
