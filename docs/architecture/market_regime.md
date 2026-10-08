# Market Regime Engine (`regime_v1`)

SPEC.md section 15. Implementation: `packages/regime/`. This document and
`packages/regime/classifier.py` must be kept in sync - the code is the
executable version of the rule table below.

## Inputs (features)

| Feature | Source |
|---|---|
| `nifty_close` | Latest close of the `NIFTY50` benchmark instrument (`^NSEI` via yfinance, see "Benchmark instrument" below) |
| `nifty_sma_50`, `nifty_sma_200` | 50/200-day SMA of the benchmark's `adjusted_close` (`packages.analytics.trend.sma`) |
| `nifty_vs_200dma_pct` | `(nifty_close / nifty_sma_200 - 1) * 100` (derived property, `None` if `nifty_sma_200` unavailable) |
| `golden_cross` | `nifty_sma_50 > nifty_sma_200` (derived property, `None` if either is unavailable) |
| `breadth_above_50dma_pct`, `breadth_above_200dma_pct` | % of the **seeded 117-instrument universe** (not the real market) whose own latest close is above its own 50/200 DMA. Each ratio's denominator only counts instruments with enough history for that window. |
| `rolling_volatility_pct` | 20-day annualized rolling volatility of the benchmark (`packages.analytics.volatility.rolling_volatility`, `* 100`) |

**`breadth_universe: "seeded_117"` is always present in the API response** -
this is never real NSE/BSE market breadth, only breadth across the dev
seed set, per the same honesty pattern used by `/relative-strength`'s
`peer_universe: "seeded_sector_peers"`.

## Benchmark instrument

Nifty 50 is registered as a normal `Instrument` row (`symbol="NIFTY50"`,
`exchange="NSE"`, `instrument_type="INDEX"`) and its OHLCV flows through
the exact same `ohlcv_daily` table and `ingest_daily_bars` pipeline as any
equity - no parallel data path. Its Yahoo Finance ticker (`^NSEI`) does not
follow the equity `SYMBOL.NS` convention, so `YFinanceDevProvider._yf_symbol`
has one small, explicit, documented special case for a small map of known
index symbols (see that module) - everything else about ingestion,
quality checks, and storage is unchanged.

## Thresholds (documented constants, `packages/regime/classifier.py`)

| Constant | Value |
|---|---|
| `HIGH_VOL_THRESHOLD_PCT` | 25.0 |
| `LOW_VOL_THRESHOLD_PCT` | 12.0 |
| `BREADTH_BULLISH_PCT` | 60.0 |
| `BREADTH_BEARISH_PCT` | 40.0 |
| `TREND_FLAT_BAND_PCT` | 3.0 |

These are product judgment calls documented here, not empirically fitted
- SPEC.md section 15 forbids ML for this engine; a human-readable,
auditable rule table is the entire point.

## Rule tree (first match wins, evaluated top to bottom)

1. **`TRANSITION` ("insufficient_data")** - if `nifty_vs_200dma_pct`,
   `golden_cross`, `breadth_above_50dma_pct`, or `rolling_volatility_pct`
   is `None` (not enough history or breadth not yet computable). Never
   guess a regime from partial data.
2. **`HIGH_VOLATILITY`** - if `rolling_volatility_pct > 25.0`, regardless
   of trend direction. Volatility regime takes priority because it is the
   most immediately actionable risk signal.
3. **`BULLISH_TREND`** - SPEC.md section 15's worked example, verbatim:
   `nifty_vs_200dma_pct > 0 AND golden_cross AND breadth_above_50dma_pct > 60`.
4. **`BEARISH_TREND`** - mirror image:
   `nifty_vs_200dma_pct < 0 AND NOT golden_cross AND breadth_above_50dma_pct < 40`.
5. **`LOW_VOLATILITY`** - `rolling_volatility_pct < 12.0 AND 40 <= breadth_above_50dma_pct <= 60`
   (quiet tape, no decisive breadth majority either way).
6. **`SIDEWAYS`** - `abs(nifty_vs_200dma_pct) <= 3.0` (index sitting at its
   own 200 DMA).
7. **`TRANSITION` ("conflicting_signals")** - anything that reaches here
   (e.g. index above its 200 DMA but no golden cross yet, moderate
   volatility, breadth not clearly bullish or bearish). A regime that is
   changing rather than settled.

## Versioning

Every row in `market_regimes` carries `rule_version` (currently
`"regime_v1"`, SPEC.md section 47). If the rule tree or thresholds above
ever change, bump to `regime_v2` and keep `regime_v1`'s historical rows
untouched - never silently reinterpret a stored classification.

## Known limitation

Breadth is computed over the ~117-instrument seed universe, not the full
NSE/BSE market. This is explicit in both the API response
(`breadth_universe: "seeded_117"`) and this document, and must not be
read as real market breadth until a production instrument universe
replaces the seed set.
