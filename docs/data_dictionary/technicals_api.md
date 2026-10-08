# Technicals / Price / Relative-Strength API contract

New API surface added in Phase 2 (SPEC.md sections 14, 16, 48, 49). This
document is the authoritative description of the response shapes; keep it
in sync with `apps/api/routes/stocks.py` and `apps/api/routes/instruments.py`.

## `GET /api/v1/instruments`

Query params: `exchange` (default `NSE`), `active_only` (default `true`),
`sort` (`symbol|company_name|sector|score|momentum_pass`), `order`
(`asc|desc`), `momentum_pass` (optional `true`/`false` filter - see
MOMENTUM_SCANNER.md section 5).

Returns `list[InstrumentSummary]` - the full seeded universe (used by the
web frontend's browse/picker table, distinct from `/instruments/search`
which requires a query string `q`), left-joined with each instrument's
latest persisted `research_scores` and default-lookback `momentum_scans`
rows (never computed live by this endpoint). Short-TTL cached in Redis
(90s - see `apps/api/routes/instruments.py`):

```json
[{"symbol": "RELIANCE", "exchange": "NSE", "company_name": "Reliance Industries Ltd",
  "sector": "Energy", "instrument_type": "EQUITY", "active": true,
  "score": 49.0, "confidence": 92.0, "band": "Neutral",
  "momentum_pass": false, "distance_from_52w_high_pct": -26.3}]
```

## `GET /api/v1/stocks/{symbol}/momentum-scan?sma200_trend_lookback_days=22`

Stage 2 Momentum Scanner (`packages/momentum/`) - full methodology,
exact response shape, and worked examples in **MOMENTUM_SCANNER.md**.
Redis cache-first exactly like `/score` below.

## `GET /api/v1/stocks/{symbol}/price?range=1M|3M|6M|1Y|2Y|ALL`

Default `range=6M`. Range is anchored to the *latest available bar*, not
wall-clock "today" (the seeded dataset is a frozen ~2 year window).

```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "range": "6M",
  "start_date": "2025-04-04",
  "end_date": "2025-10-03",
  "bars": [
    {"date": "2025-04-04", "open": 1234.5, "high": 1250.0, "low": 1220.0,
     "close": 1240.0, "adjusted_close": 1240.0, "volume": 5230000}
  ],
  "data_freshness": {
    "latest_trading_date": "2025-10-03",
    "as_of": "2026-10-04T12:00:00+00:00",
    "data_age_days": 366,
    "stale": true
  }
}
```

Errors:
- `404` - unknown symbol.
- `422` - the instrument exists but has zero ingested OHLCV rows yet
  (not a 500; "exists but no data" is a different, clearly-labeled
  condition from "doesn't exist").

## `GET /api/v1/stocks/{symbol}/technicals?range=1M|3M|6M|1Y|2Y|ALL`

Default `range=6M`. `snapshot` is always computed from the instrument's
**full** history (so long-window indicators like SMA200 are never
short-changed by a short display range); only `series` is sliced to
`range`.

```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "range": "6M",
  "as_of_date": "2025-10-03",
  "snapshot": {
    "as_of_date": "2025-10-03", "close": 1240.0, "adjusted_close": 1240.0,
    "sma_20": 1230.1, "sma_50": 1200.4, "sma_100": 1180.2, "sma_150": 1165.0, "sma_200": 1150.0,
    "ema_9": 1235.0, "ema_20": 1228.0, "ema_50": 1205.0, "ema_200": 1160.0,
    "adx_14": 28.5,
    "rsi_14": 61.2, "macd_line": 12.3, "macd_signal": 10.1, "macd_histogram": 2.2,
    "roc_12": 4.1, "stochastic_k": 72.0, "stochastic_d": 68.5,
    "atr_14": 18.4, "bollinger_upper": 1270.0, "bollinger_mid": 1230.1, "bollinger_lower": 1190.2,
    "rolling_volatility_20": 0.22,
    "volume_sma_20": 4200000, "relative_volume_20": 1.3, "obv": 98230000,
    "fifty_two_week_high": 1310.0, "fifty_two_week_low": 980.0,
    "distance_from_52w_high_pct": -5.3, "distance_from_52w_low_pct": 26.5,
    "breakout_20d": false, "breakdown_20d": false
  },
  "series": {
    "dates": ["2025-04-04", "..."],
    "close": [1210.0, "..."],
    "volume": [4800000, "..."],
    "ema_20": [1215.3, "..."],
    "ema_50": [1198.1, "..."],
    "ema_200": [1150.4, "..."],
    "rsi_14": [55.2, "..."],
    "macd_line": [8.1, "..."],
    "macd_signal": [7.0, "..."],
    "macd_histogram": [1.1, "..."]
  },
  "data_freshness": { "...": "same shape as /price" }
}
```

Any field may be `null` where the instrument's history isn't yet long
enough for that window (e.g. `sma_200` is `null` with fewer than 200 bars) -
`null` is never silently replaced with `0` or a fabricated value.

Errors: same `404`/`422` semantics as `/price`.

## `GET /api/v1/stocks/{symbol}/relative-strength`

Simplified sector relative strength (SPEC.md section 16, explicitly scoped
down - see README "Known limitations"). The "sector return" is the simple
average return of other seeded instruments sharing the same
`Instrument.sector` - **not** a licensed sector index. `peer_universe` is
always `"seeded_sector_peers"` to make this unambiguous.

```json
{
  "symbol": "TCS",
  "exchange": "NSE",
  "sector": "Information Technology",
  "peer_universe": "seeded_sector_peers",
  "peer_count": 10,
  "peer_symbols": ["COFORGE", "HCLTECH", "INFY", "..."],
  "as_of_date": "2025-10-03",
  "metrics": {
    "1W": {"stock_return_pct": 1.2, "peer_avg_return_pct": 0.4, "relative_strength_pct": 0.8, "reason": null},
    "1M": {"...": "..."},
    "3M": {"...": "..."},
    "6M": {"...": "..."},
    "1Y": {"...": "..."}
  },
  "data_freshness": { "...": "same shape as /price" }
}
```

Horizons are **trading-bar** lookbacks (1W=5, 1M=21, 3M=63, 6M=126,
1Y=252), not calendar days.

Per-horizon `reason` (always `null` when the metric was actually computed):
- `"insufficient_peer_universe"` - the instrument's sector has fewer than
  2 other active seeded instruments (or `sector` is `null`). `stock_return_pct`
  may still be populated (it's a real, independently-computed number, not
  a comparison) but `peer_avg_return_pct`/`relative_strength_pct` are
  always `null` - never a fabricated sector comparison.
- `"insufficient_price_history"` - the peer universe is fine, but either
  the stock itself or every one of its peers doesn't have enough bars yet
  for this specific horizon.

Errors: `404` for unknown symbol, `422` if the instrument itself has zero
OHLCV rows (peers lacking data never error the whole request - they're
just excluded from that horizon's average).
