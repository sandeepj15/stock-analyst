# MOMENTUM_SCANNER.md — Stage 2 Momentum Scanner (`stage2_momentum_v1`)

Authoritative methodology reference for `packages/momentum/` (SPEC.md
section 39's "Setup Scanner" concept). Precise enough to reproduce the
scan and the RS Rank from this document alone. If the 8 conditions,
thresholds, or RS Rank formula ever change, the new version must ship
as `stage2_momentum_v2` (or later) — a stored `momentum_scans.methodology_version`
value is never reinterpreted retroactively (SPEC.md section 47, section
81 rule 6).

**No LLM is used anywhere in this scanner.** Every number is a
deterministic function of stored OHLCV data (SPEC.md section 81 rule 3).

## 1. What this is

A deterministic, binary pass/fail screen for Mark Minervini's "Stage 2
Trend Template" — identifying stocks in a confirmed, established
uptrend. A stock passes **only when all 8 conditions below are true**
on the evaluation date, computed from daily **adjusted** closing
prices (`adjusted_close`, not raw `close` — see
`packages/indicators/snapshot.py`'s rationale: splits/dividends must
never show up as spurious price jumps, SPEC.md section 2.8).

252 trading days = "one year", 22 trading days = "one month" — the
same convention already used for 52-week calculations elsewhere in
this codebase (`packages/analytics/price_structure.py`).

## 2. The 8 conditions (`packages/momentum/scanner.py::evaluate_stage2_momentum`)

| # | Name | Condition |
|---|---|---|
| 1 | `close_above_sma150_and_sma200` | `close > SMA150 AND close > SMA200` |
| 2 | `sma150_above_sma200` | `SMA150 > SMA200` |
| 3 | `sma200_trending_up` | `SMA200(today) > SMA200(N trading days ago)` |
| 4 | `sma50_above_sma150_and_sma200` | `SMA50 > SMA150 AND SMA50 > SMA200` |
| 5 | `close_above_sma50` | `close > SMA50` |
| 6 | `close_at_least_130pct_of_52w_low` | `close >= 1.30 × 52_week_low` |
| 7 | `close_within_25pct_of_52w_high` | `close >= 0.75 × 52_week_high` |
| 8 | `rs_rank_at_least_70` | `RS_Rank >= 70` |

`N` (condition 3's lookback) is `sma200_trend_lookback_days`, a
**configurable parameter**, default **22** (~1 month). It is never
hardcoded — pass a stricter value (the task spec suggests ~90-110,
~4-5 months, for a tougher long-term-trend confirmation) via the API's
`?sma200_trend_lookback_days=N` query param or the scanner function's
keyword argument. SMA150 reuses the same generic `sma()` function
every other SMA window in this codebase uses
(`packages/analytics/trend.py::sma`) — no duplicated moving-average math.

**Overall gate is strictly binary** (`passed = all(conditions)`), but
every one of the 8 individual condition results — `name`, `passed`,
`value`, `threshold`, `description` — is always returned, even for a
failing stock, so a stock's page/tooltip can show *exactly which*
conditions failed (this app's evidence-first philosophy, SPEC.md
section 2.1, applied to a scanner just as much as to the Research
Score engine).

**Insufficient history**: a stock with fewer than
`MIN_TRADING_DAYS_REQUIRED` (252) trading days, or any missing required
input (SMA/52w-high-low/RS Rank), scans as `evaluable: false`,
`passed: null` — **never** a fabricated PASS or FAIL (SPEC.md section
81 rule 23).

**Distance from 52-week high** (for ranking passing stocks by
proximity to their high downstream):

```
distance_from_52w_high_pct = (close - 52_week_high) / 52_week_high * 100
```

Always `<= 0`; closer to `0` = stronger (closer to its 52-week high).

## 3. RS Rank — a documented approximation, not the licensed IBD metric

**This is not IBD's licensed/official "Relative Strength Rating."** It
is a percentile rank computed only over this app's own seeded
instrument universe, using the commonly-published open-source
approximation of that methodology. Every value this produces is
labeled `rs_rank_universe` (currently `"seeded_755"`) everywhere it
appears — API responses, docs, UI tooltips — the same honesty
convention this codebase already uses for `peer_universe`
(`"seeded_sector_peers"`), `breadth_universe` (`"seeded_117"`), and
`valuation_universe_size` (SPEC.md sections 2.3, 21, 81 rule 23).

### 3.1 Raw score (`packages/momentum/rs_rank.py::compute_raw_score`)

Split the trailing 252 trading days of `adjusted_close` into four
63-trading-day quarters: **Q1 = most recent 63 bars**, Q2, Q3,
**Q4 = oldest of the four**. Each quarter's return:

```
quarter_return = close[quarter_end] / close[quarter_start] - 1
```

```
raw_score = 2 × Q1_return + Q2_return + Q3_return + Q4_return
```

(double-weighting the most recent quarter — the standard open-source
approximation of IBD's publicized weighting). Requires 253 price
points (252 trading days of returns); `None` (never fabricated) with
fewer.

### 3.2 Percentile rank (`percentile_rank_universe`)

`raw_score` is computed for **every** active EQUITY instrument with
enough history, then percentile-ranked together: `0` = weakest
`raw_score` in the universe, `100` = strongest. Ties get the *average*
rank across the tied block (standard fractional-rank tie handling). A
single-instrument population has no meaningful relative rank and
returns a neutral `50.0` rather than a fabricated extreme.

### 3.3 Performance (O(n log n), not O(n²))

RS Rank requires a universe-wide percentile. The batch job
(`apps/worker/jobs.py::compute_all_momentum_scans_job`) computes every
instrument's `raw_score` **once**, then ranks the whole universe
together in a single sort — **never** recomputed per-instrument
pairwise, which would be O(n²) over the batch (the exact mistake
already made and fixed once for valuation percentiles — see
`packages/scoring/components.py`'s module-level comment and
SCORING.md §3.6). The on-demand `/momentum-scan` route uses a
15-minute, process-local TTL cache of the same universe scan
(`packages.momentum.service.get_cached_universe_raw_scores`) instead
of rescanning ~750 instruments per request — identical methodology,
just computed less often.

Real measurement: `compute_all_momentum_scans_job` across 754 active
instruments completed in **~15 seconds**.

## 4. Persistence (`packages/momentum/models.py::MomentumScan`)

One `momentum_scans` row per computation (append-only, mirrors
`research_scores`' pattern exactly — SPEC.md section 47): `instrument_id`,
`scan_date`, `passed` (bool, nullable), `conditions` (JSONB — the full
8-condition breakdown), `distance_from_52w_high_pct`, `rs_rank`,
`sma200_trend_lookback_days` (the `N` actually used), `methodology_version`
(`"stage2_momentum_v1"`), `computed_at`. Never mutated after insert —
readers always take the most recently persisted row.

## 5. API shape

### `GET /api/v1/stocks/{symbol}/momentum-scan?sma200_trend_lookback_days=N`

```json
{
  "instrument_id": "277642d6-...",
  "symbol": "DIVISLAB",
  "exchange": "NSE",
  "scan_date": "2026-10-01",
  "evaluable": true,
  "passed": true,
  "conditions": [
    {"name": "close_above_sma150_and_sma200", "passed": true, "value": 9249.0, "threshold": 7297.39,
     "description": "Close must be above both SMA150 and SMA200."},
    "... 7 more, one per condition in section 2's table order ..."
  ],
  "distance_from_52w_high_pct": -3.9,
  "rs_rank": 91.78,
  "rs_rank_universe": "seeded_755",
  "sma200_trend_lookback_days": 22,
  "methodology_version": "stage2_momentum_v1",
  "computed_at": "2026-10-05T17:39:21.11Z",
  "reason": null,
  "cache_hit": true
}
```

`reason` is populated (e.g. `"insufficient_price_history"`) only when
`evaluable` is `false`; `conditions` is `[]` in that case.

### `GET /api/v1/instruments?momentum_pass=true&sort=momentum_pass&order=desc`

Extends the existing sortable instrument listing
(`apps/api/routes/instruments.py`) with two fields joined from each
instrument's latest *persisted* `momentum_scans` row at the default
lookback (never computed live by this endpoint):

```json
{"symbol": "DIVISLAB", "...": "...", "momentum_pass": true, "distance_from_52w_high_pct": -3.9}
```

`momentum_pass` is a valid `sort` key (`true` sorts first on `desc`;
`null` — not yet scanned, or not evaluable — always sorts last
regardless of direction). `?momentum_pass=true` filters the listing
down to genuine, evaluable passes only — this is what turns the
listing into an actual Stage 2 scanner view (SPEC.md section 39).

## 6. Redis caching (SPEC.md section 59)

See `packages/scoring/engine.py` and `packages/momentum/service.py`'s
"Redis caching" comments, and `packages/common/cache.py`. Short
version: `compute_all_momentum_scans_job` write-throughs every
instrument's scan into Redis immediately after persisting it
(`momentum_scan:v1:{instrument_id}:{sma200_trend_lookback_days}`, 30
minute TTL as a safety net); the on-demand route checks Redis first
and only falls back to a live computation on a miss.

## 7. Known limitations

- RS Rank is a **documented open-source approximation**, not the
  licensed IBD RS Rating — see §3.
- A stock needs ~252 trading days of adjusted-close history to be
  evaluable at all; this dev dataset's seeded universe includes some
  thinly-covered/dummy instruments that will always scan as
  `evaluable: false`.
- The default lookback (`N=22`) is a product judgment call per the
  task spec, not an empirically fitted number — callers that want the
  stricter 4-5 month confirmation window must pass
  `?sma200_trend_lookback_days=90..110` explicitly; the batch job and
  the home-page listing's persisted `momentum_pass` column always use
  the default (22).
- A handful of instruments can fail to scan due to a pre-existing,
  unrelated data-quality edge case in `packages/analytics/momentum.py::stochastic`
  (a `pandas.NA` surfacing for certain OHLC patterns) that
  `compute_indicator_series` also hits — the batch job catches and
  skips these per-instrument (same resilience pattern as every other
  batch job in this codebase), they do not corrupt or block the rest
  of the run.
