# Data Sources

This document is the single source of truth for *which* data source backs
*which* capability, which of those are free/dev-only vs. requiring a key,
and what must change before any commercial launch. See SPEC.md sections 8,
73, and 105 for the underlying policy; this file is the operational detail.

## Local development (today)

| Capability          | Source                          | Key required | Commercial-use OK? |
|----------------------|----------------------------------|---------------|---------------------|
| NSE equity universe (~750 symbols) | NSE Indices' own `ind_niftytotalmarket_list.csv` (fallback: `ind_nifty500list.csv` + `ind_niftymicrocap250_list.csv`) | No | Public index data, see caveat below |
| OHLCV (daily)        | `yfinance` (unofficial Yahoo Finance wrapper) | No | **No** |
| Basic instrument info (name, sector, etc.) | `yfinance` | No | **No** |
| Fundamentals (primary) | `yfinance` (`Ticker.income_stmt`/`.balance_sheet`/`.cashflow`/`.info`) | No | **No** |
| Fundamentals (secondary/fallback, opt-in) | `tradingview-ta` (TradingView's public stock screener) | No | **No** |
| Market regime (Nifty 50 benchmark) | `yfinance` (`^NSEI`) | No | **No** |
| News                 | Not implemented yet (future: public RSS feeds) | No | TBD per feed's terms |
| AI explanation layer | Not implemented (stubbed/mocked until Phase 10) | - | - |

### NSE equity universe (~750 symbols) — `packages/market_data/universe.py`

- Primary source: `https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv`,
  NSE Indices Ltd's (NSE's own index subsidiary) official constituent file
  for the **Nifty Total Market Index** — defined by NSE as the ~750
  largest NSE-listed companies by free-float market cap (Nifty 500 +
  Nifty Microcap 250, deduplicated). Published on NSE's own public
  website, refreshed periodically for index reconstitution and corporate
  actions, no authentication, no API key. Verified live (Oct 2026): 755
  rows, columns `Company Name`, `Industry`, `Symbol`, `Series`, `ISIN Code`.
  This is why it's safe to rely on for local development: it is NSE's
  own published reference list, not a scrape or an inferred universe.
- Fallback (used only if the primary file is unreachable after retries):
  `ind_nifty500list.csv` + `ind_niftymicrocap250_list.csv` from the same
  host, unioned and deduplicated by symbol. This is the exact technique
  the sibling `laya-stock-intelligence` project
  (`ai_stock_agent_1d_1w.py::get_nse_tickers_fast`) already uses for the
  same purpose — reused here as the documented fallback, same author's
  own prior work, not a third party's.
- Caveat: NSE's constituent file includes a handful of non-tradeable
  placeholder rows (e.g. `DUMMYHEG`, `DUMMYINXGN` — NSE's own temporary
  scrips used during corporate-action bookkeeping) and at least one REIT
  (`BAGMANE`) that yfinance doesn't cover. These seed as `Instrument`
  rows with zero backfillable OHLCV — a genuine, honestly-reported gap
  (6 symbols out of 756 in the Oct 2026 run), not an ingestion bug. See
  the "Known limitations" section below.

### Corporate-action symbol changes — `packages/market_data/corporate_actions.py`

Three symbols seeded in the original ~117-instrument list
(`TATAMOTORS`, `LTIM`, `ZOMATO`) had zero ingested OHLCV because they no
longer resolve on Yahoo Finance — **all three were genuine renames**,
verified live against Yahoo Finance + cross-checked against NSE's own
`ind_niftytotalmarket_list.csv`, not transient ingestion failures:

| Old symbol | Current symbol | What happened |
|---|---|---|
| `ZOMATO` | `ETERNAL` | 2024 corporate rename, Zomato Ltd → Eternal Ltd. |
| `LTIM` | `LTM` | LTIMindtree Ltd renamed to LTM Ltd; same ISIN/listing continuity (~10y continuous history under the new ticker). |
| `TATAMOTORS` | `TMPV` (+ new instrument `TMCV`) | Tata Motors demerger. The original listed entity (full price history, same ISIN `INE155A01022`) was renamed/re-ticker'd to `TMPV` (Tata Motors Passenger Vehicles). The demerged commercial-vehicles business, `TMCV`, is a **separate, newly-listed entity** (new ISIN `INE1TAE01010`) with only ~10 months of history (first bar 2025-11-12, consistent with "when-issued" trading ahead of full listing) — seeded as its own instrument, never treated as a TATAMOTORS alias. |

`apply_known_symbol_renames` repoints any pre-existing old-symbol
`instruments` row to the new ticker **in place** (preserving
`instruments.id` and therefore all existing OHLCV/fundamentals/
scores/evidence), and records an `instrument_aliases` row
(`symbol`, `exchange`, `instrument_id`, `created_at` — SPEC.md section
45) so the old symbol still resolves via `apps/api/deps.py::resolve_instrument`.
It is idempotent and order-independent with respect to the universe
seed (works whether the old-symbol row already exists, or the DB was
seeded fresh and only ever had the new symbol).

### yfinance — the local-dev market data provider

- Implemented in `packages/market_data/providers/yfinance_provider.py`
  (`YFinanceDevProvider`), selected via `MARKET_DATA_PROVIDER=yfinance_dev`
  (the default in `.env.example`).
- Free, no API key, no signup. This is why it's the dev default — SPEC.md
  section 105.1 requires local development to need **zero paid API keys**.
- `yfinance` is an **unofficial** wrapper around Yahoo Finance endpoints. It
  is not an official, licensed, commercial data product. Yahoo's own
  developer/API terms impose restrictions that vary by product, and this
  provider is explicitly **not licensed for commercial redistribution**
  (SPEC.md sections 8 and 73).
- `get_intraday_bars` deliberately raises `NotImplementedError` rather than
  returning unreliable/retention-limited intraday data as if it were solid.
  `get_quotes` is a best-effort approximation (`fast_info`) suitable for
  local dev only, not a real-time quote feed.
- No code outside `packages/market_data` imports `yfinance` — the rest of
  the application depends only on the `MarketDataProvider` protocol in
  `packages/market_data/base.py`, so swapping the provider later requires no
  changes anywhere else.

### yfinance fundamentals — coverage gaps and a unit quirk

- Implemented in `packages/fundamentals/providers/yfinance_fundamental_provider.py`
  (`YFinanceFundamentalProvider`), selected via `FUNDAMENTAL_PROVIDER=yfinance_dev`
  (defaults to the same `yfinance_dev` family when unset).
- **Coverage is inconsistent for NSE tickers** — some stocks return zero
  periods of fundamentals, or omit individual line items. Every missing
  field is stored as `NULL`, never backfilled (SPEC.md section 81 rule
  8). This is expected and visible via `has_fundamental_data: false` on
  `GET /api/v1/stocks/{symbol}/fundamentals`, not an application error.
- **Unit quirk, verified against live data (Oct 2026)**: yfinance's
  `Ticker.info["dividendYield"]` is already expressed in
  *percentage-point* units (e.g. `0.51` means "0.51%"), unlike every
  other ratio this codebase derives itself (ROE, growth rates, margins),
  which are plain fractions (`0.0893` = "8.93%"). See
  `packages/fundamentals/models.py` and SCORING.md for where this is
  handled.
- Nifty 50 (`^NSEI`) is fetched through the same `YFinanceDevProvider`
  used for equities, via one small documented exception in
  `_yf_symbol` for a short list of known index tickers (see that
  module) — everything else about ingestion is unchanged.

### yfinance quarterly fundamentals — shallow history, kept as the quarterly fallback

- Implemented in `packages/fundamentals/providers/yfinance_fundamental_provider.py`
  (`YFinanceQuarterlyFundamentalProvider`, `period_type="Q"`).
- **Much shallower history than screener.in**: `yfinance`'s
  `quarterly_income_stmt`/`quarterly_balance_sheet`/`quarterly_cashflow`
  returned only 5-6 quarters for RELIANCE/TCS/INFY when checked live —
  nowhere near multi-year quarterly history, and individual quarters can
  be entirely missing (e.g. RELIANCE's Sep-2025 quarter came back with
  `revenue`/`pat` both `None` while the surrounding quarters had real
  values). This is why screener.in (below) is now the quarterly
  **primary** - yfinance quarterly is kept only as its fallback.

### screener.in — annual fallback + quarterly primary (research use, added Oct 2026)

- Implemented in `packages/fundamentals/providers/screener_in_provider.py`
  (`ScreenerInFundamentalProvider` for annual `period_type="FY"`,
  `ScreenerInQuarterlyFundamentalProvider` adapter for `period_type="Q"`).
  Wired in via `packages/fundamentals/factory.py`:
  `FUNDAMENTAL_PROVIDER=yfinance_screener_fallback` composes
  `yfinance (primary) -> screener.in (fallback)` for annual data;
  `get_quarterly_fundamental_provider` always composes
  `screener.in (primary) -> yfinance quarterly (fallback)` for quarterly.
- **Scraping posture, checked explicitly before building this** (personal
  research use, not a redistributed commercial product - same posture
  already taken with yfinance's own non-commercial-redistribution
  caveat above): `screener.in/robots.txt` disallows `/user/*` and a few
  query-param/internal paths, but does **not** disallow `/company/*` -
  the only pages this provider reads. One lightweight GET per instrument,
  identified `User-Agent`, and quarterly/annual syncs each run only a
  handful of times a year per instrument (never part of the daily cron -
  see `sync_quarterly_fundamentals_job`/`sync_fundamentals_job`). Full
  screener.in Terms of Service text was not independently reviewed beyond
  robots.txt.
- **Unit handling**: each screener.in table explicitly labels itself
  "Figures in Rs. Crores" or "Rs. Lakhs" - this provider reads that label
  per-section and multiplies by 1e7/1e5 accordingly, never assuming a
  fixed unit. Cross-validated live (Oct 2026): screener's RELIANCE
  Jun-2026 quarterly Sales "309,468" (Rs. Crores) x 1e7 ==
  3,094,680,000,000, exactly matching yfinance's own figure for the same
  quarter.
- **Quarterly coverage**: 13 quarters for RELIANCE/TCS/INFY when checked
  live (vs yfinance's 5-6) - this is what makes
  `revenue_at_all_time_high`/`pat_at_all_time_high` and
  `revenue_growth_yoy`/`pat_growth_yoy` meaningfully more complete than
  the yfinance-only version of this feature. Still only scoped to
  `quarters_available` (not true since-listing history) - the API/UI
  surface that count explicitly rather than overclaiming.
- **Annual fields, v1 scope**: only `revenue`, `pat`, `equity` (= Equity
  Capital + Reserves, only computed when *both* rows have a value),
  `total_debt` (Borrowings row), `total_liabilities`, and `total_assets`
  are populated. `ebitda`/`ebit`/`eps`/cash-flow fields are left `None` -
  screener's "Operating Profit" row needs netting against Depreciation to
  reach EBIT, not scraped here to avoid a half-correct mapping.
- **`current_assets`/`current_liabilities` stay `None` from screener.in
  too** - like yfinance, its condensed balance sheet has no
  current/non-current split for Indian companies. This is a genuine
  reporting-format gap, not fixable by switching providers.
- **Quarter-overlap dedup**: since `source` is part of
  `fundamental_snapshots`' unique key, a quarter both screener.in and
  yfinance report ends up as two separate DB rows (never one overwriting
  the other - provenance stays inspectable). `apps/api/routes/fundamentals.py`'s
  `_dedupe_quarterly_by_period` collapses these to one per quarter before
  computing YoY/ATH, preferring screener.in.

### tradingview-ta — secondary/fallback fundamentals provider (opt-in)

- Implemented in `packages/fundamentals/providers/tradingview_fundamental_provider.py`
  (`TradingViewFundamentalProvider`) and composed with the primary
  yfinance provider by `packages/fundamentals/providers/composite_provider.py`
  (`CompositeFundamentalProvider`). Selected via
  `FUNDAMENTAL_PROVIDER=yfinance_tradingview_fallback` (opt-in — the
  default `yfinance_dev` behavior is unchanged unless this is set).
- **Field names were empirically verified, not guessed**: tested live
  against RELIANCE, TCS, ITC, COALINDIA, HDFCBANK, INFY (Oct 2026)
  before any field name was hardcoded. See the provider module's
  docstring for the full verified mapping (e.g. `revenue` →
  `total_revenue`, `eps` → `earnings_per_share_diluted_ttm`, `equity` →
  `total_equity_fq`). Several plausible-sounding field names (e.g.
  `total_liabilities`, `ebit`, `operating_income_ttm`) were tried and
  discarded because they returned `None` for every test symbol.
  Coverage is inconsistent across symbols, same caveat as yfinance.
- **Fill-only-if-missing, never overwrite** (SPEC.md section 13, section
  81 rule 8): `CompositeFundamentalProvider` only fills a field the
  primary (yfinance) snapshot has as `NULL`. A value yfinance already
  supplied is never replaced. If yfinance has **zero** snapshots at all
  for an instrument, a single fallback-only snapshot is synthesized
  (honestly labeled `source="tradingview_ta"`, not blended with a
  nonexistent yfinance row).
- **Provenance stays inspectable**: `fundamental_snapshots.field_sources`
  (new JSONB column, migration `24e15ddb9323`) records, per non-null
  field, which provider actually supplied it — e.g.
  `{"revenue": "yfinance", "eps": "tradingview_ta"}`. The top-level
  `source` column stays the primary provider's name whenever the
  primary contributed at least one field.
- **No period granularity**: TradingView's screener fields (`_ttm`/`_fq`
  suffixed) are a continuously-refreshed *current* snapshot, not a
  specific historical fiscal period. The fallback provider therefore
  always returns at most one `period_type="TTM"` snapshot stamped with
  today's date — when it fills a gap in one of yfinance's *older*
  historical periods, that older period receives the same current
  fallback value (a documented approximation, not a fabrication: it's
  the best available free data for that field, clearly attributed via
  `field_sources`).
- **Observed rate limiting (Oct 2026 real run)**: TradingView's public
  screener endpoint returned HTTP 429 fairly often at concurrency=8
  across ~750 symbols. The existing retry-with-backoff
  (`packages.common.rate_limit.call_with_retry`, 3 attempts) absorbed
  these without the run failing, but it materially slows the fallback
  path down — a real-world confirmation of why SPEC.md section 59
  requires a retry policy for every external provider, not just a
  rate limiter.

### Fundamental Score leverage fields — empirically verified (Oct 2026)

For the Fundamental Score's Leverage sub-score (SCORING.md §10), three
new raw fields were added to `fundamental_snapshots`
(`interest_expense`, `current_assets`, `current_liabilities`, migration
`b7a1c9d4e821`). Before adding them, both candidate providers were
tested live against real NSE symbols — never guessed from memory:

| Field | yfinance (`income_stmt`/`balance_sheet`) | tradingview_ta (screener) |
|---|---|---|
| `interest_expense` | Exact row `"Interest Expense"` — confirmed present with real nonzero values for RELIANCE, TCS, ITC, INFY, **and HDFCBANK** (a bank - its income statement does carry a standalone "Interest Expense" line, contrary to an earlier assumption during development that was corrected after re-checking live). | Candidate `interest_expense_ttm` tested — `None` for every symbol tried (RELIANCE, TCS, ITC, HDFCBANK, INFY). **Not used as a source for this field.** |
| `current_assets` | Exact row `"Current Assets"` — confirmed present for RELIANCE, TCS, ITC, INFY. **Genuinely absent for HDFCBANK** (confirmed live: `"Current Assets" in balance_sheet.index` is `False`) — a bank's balance sheet has no current/non-current split, a real structural difference from non-financial companies, not a coverage gap. | `total_current_assets_fq` — present for TCS, `None` for RELIANCE/ITC/HDFCBANK. Wired up as an opportunistic fallback (fills gaps only). |
| `current_liabilities` | Exact row `"Current Liabilities"` — same coverage as `current_assets` above. | `total_current_liabilities_fq` — same coverage pattern as `total_current_assets_fq` above. Wired up as a fallback. |

**Conclusion**: yfinance is the primary (and for `interest_expense`,
only) source for these three fields; tradingview_ta genuinely has
`current_assets`/`current_liabilities` for *some* symbols (confirmed
live, not fabricated) and is wired up as an opportunistic
`CompositeFundamentalProvider` fallback for those two only.
`interest_expense` is yfinance-only.

**Candidates checked and genuinely NOT added** (per the "never fabricate
a metric that isn't available" rule): a dedicated **quick ratio** was
considered but not implemented — it needs an inventory figure, and
neither provider's exposed fields for NSE tickers reliably supplied one.
Current ratio (which doesn't need inventory) is implemented instead.
ROA, net profit margin, asset turnover and financial leverage did **not**
need any new raw field — they're derived entirely from fields this
schema already had (`pat`, `revenue`, `total_assets`, `equity`). PEG
ratio also needed no new raw field (derived from existing P/E +
EPS-growth), but is explicitly `null` whenever EPS growth is `<=0`
(PEG is conventionally undefined for a flat/shrinking-earnings company)
and uses *trailing* EPS growth, not a forward analyst estimate (no
earnings-estimates data source exists in this codebase) — a documented
approximation, not the vendor-standard forward-PEG some data products
compute.

### Analyst 1-year price target / recommendation — empirically verified (Oct 2026)

For the Analyst Rating / 1-Year Price Target feature
(`packages/analyst_estimates/`), the working assumption going in — based
on the fundamentals work above, where tradingview_ta mostly exposed
technical/screener fields rather than deep fundamental data — was that
TradingView likely would **not** have a genuine analyst price target
either. That assumption was tested live (Oct 2026, RELIANCE, TCS, ITC,
COALINDIA, HDFCBANK, INFY, `india` screener) and turned out to be
**wrong**:

| Field | tradingview_ta (screener) | yfinance (`Ticker.info`) |
|---|---|---|
| 1Y price target (mean/avg) | `price_target_average` — genuinely populated for all 6 symbols tested (e.g. RELIANCE 1656.75, HDFCBANK 996.55) | `targetMeanPrice` — also populated (RELIANCE 1676.85, HDFCBANK 989.61) |
| Target high/low/median | `price_target_high`/`price_target_low`/`price_target_median` — all populated | `targetHighPrice`/`targetLowPrice`/`targetMedianPrice` — all populated |
| Analyst recommendation | **Not genuinely available.** The only non-null candidates (`Recommend.All`, `Recommend.MA`, `Recommend.Other`, `recommendation_mark`) are TradingView's own *technical indicator* consensus (moving-average/oscillator blend), not a Wall-Street analyst poll — `analyst_rating`/`rating`/`recommendation` all returned `None` for every symbol. **Never used as a recommendation source.** | `recommendationMean`/`recommendationKey`/`numberOfAnalystOpinions` — genuine analyst buy/hold/sell consensus + analyst count, populated for all 6 symbols (20-42 analysts each) |

The two providers' price targets were cross-checked against each other
and track closely (e.g. ITC: 326.03 vs. 327.15; TCS: 2411.98 vs.
2436.37) — consistent with two independent aggregations of a real,
overlapping sell-side analyst panel, not two unrelated numbers.

**Conclusion**: unlike the fundamentals composite (yfinance primary,
tradingview_ta fallback), the analyst-estimate composite
(`packages/analyst_estimates/providers/composite_provider.py`) runs the
*opposite* way — **TradingView is primary** for the four price-target
fields specifically because it was confirmed to genuinely have them,
per this task's explicit "prefer TradingView when it genuinely has the
data" instruction — with yfinance filling any price-target gap and
supplying the recommendation/analyst-count fields TradingView does not
have. Running the batch sync (`sync_analyst_estimates_job`) against the
live 756-instrument universe: 648 instruments got a real target (201
from TradingView, 447 filled from yfinance after TradingView either had
no coverage or its free screener endpoint rate-limited some requests
under concurrency=6), 107 had zero coverage from both providers — a
real, expected gap for thinly-covered mid/small-cap NSE names, left
`null`, never fabricated.

## Before commercial launch

Per SPEC.md section 73 ("Important Commercial Constraint"): market data is
potentially the largest licensing dependency of this entire business, and
the production data plan must be validated with the chosen vendor/exchange
— never assume "free API -> commercial SaaS -> unlimited redistribution."

Required before any commercial launch:

1. **Licensed NSE/BSE vendor data contract.** NSE and BSE both offer
   structured real-time/delayed/historical/corporate data products with
   their own data-sharing and usage policies (SPEC.md section 8). Before
   using any such feed commercially: verify redistribution rights, storage
   rights, derived-data rights, API limits, user-facing display
   permissions, and commercial SaaS rights specifically.
2. **Replace `YFinanceDevProvider`** with a provider implementing the same
   `MarketDataProvider` protocol, backed by the licensed feed. Because all
   application code depends only on the protocol, this should not require
   touching ingestion, the API, or the worker.
3. **Re-review SEBI's Research Analyst / Investment Adviser regulatory
   boundary** (SPEC.md section 62) before describing any output as
   investment advice.

## Optional free-tier keys for later redundancy (not needed today)

SPEC.md section 105.2 lists these as optional backups for a later phase —
none are required for the scope built so far:

- `ALPHA_VANTAGE_API_KEY` — alternate/backup OHLCV or fundamentals source.
- `TWELVEDATA_API_KEY` — alternate/backup OHLCV source.
- `NEWSAPI_API_KEY` — alternate news source (public RSS feeds are the
  planned primary free news source for the News capability, SPEC.md
  section 105.1).

## Required starting Phase 10

- `ANTHROPIC_API_KEY` — powers the evidence-grounded AI explanation layer
  (SPEC.md Phase 10 / section 94). Not used anywhere in the code built so
  far; the AI layer package (`packages/ai/`) is an empty placeholder.

## Self-generated secrets (not external data sources)

- `JWT_SECRET`, `ENCRYPTION_KEY` — generate locally with
  `openssl rand -hex 32`. Never share these across environments, never
  commit them.
