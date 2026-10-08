# SCORING.md — Research Strength (`research_score_v2`)

This is the authoritative methodology reference for the Research Score
engine (`packages/scoring/`, SPEC.md sections 17-22, 24, 46-47, 86). It
should be precise enough to reimplement the score from this document
alone. If the weights, bands, or formulas below ever change, the new
version must be shipped as a new `METHODOLOGY_VERSION` — a stored
`research_scores.methodology_version` value is never reinterpreted
retroactively (SPEC.md section 47, section 81 rule 6).

**No LLM is used anywhere in this engine.** Every number here is a
deterministic function of stored data (SPEC.md section 81 rule 3).

## 0. Methodology version history

- **`research_score_v1`** (original): all 8 components as described
  below, except the "fundamentals" component scored a flat delta sum
  over revenue/PAT/EPS growth + ROE/simplified ROCE only (§3.3's old
  table), and the bull/bear case (§8) carried no `strength` field and
  plainer, more mechanical interpretation text.
- **`research_score_v2`** (current, 2026-10): two changes, both
  additive/explanatory rather than a reweighting of the 8 components
  against each other:
  1. **Richer, explanatory evidence text** (§7.1) — every interpretation
     sentence now adds a plain-language "why it matters" clause and a
     magnitude qualifier, still 100% templated (no LLM).
  2. **Fundamental Score refactor** (§3.3, §10) — the "fundamentals"
     component (still 20% of the headline score) is now computed by
     `packages/scoring/signals.py::compute_fundamental_score`, which
     combines four named sub-scores (Growth/Profitability/Leverage/
     Efficiency) instead of a flat delta sum, adding ROA, net profit
     margin, Debt/Equity, Net Debt/EBITDA, interest coverage, current
     ratio and asset turnover as new sub-signals. This is the *same*
     function behind the standalone Fundamental Score on
     `GET /stocks/{symbol}/fundamentals` — single source of truth, see
     §10.
  - **Decision: bump, don't reinterpret in place.** SignalForge is
    still pre-launch with zero external users depending on historical
    score continuity, so an in-place reinterpretation would have cost
    nothing in practice. The version was still bumped (`v1` → `v2`)
    because (a) the fundamentals component's actual formula materially
    changed — it is not just added transparency fields, it is a
    different point-math path that can produce a different number for
    the same instrument/snapshot than `v1` would have, and (b) this
    codebase's own documented rule (SPEC.md section 47, section 81 rule
    6: "every calculation must have a version... never silently
    recalculate historical reports using a new methodology") doesn't
    carve out an exception for pre-launch convenience — the discipline
    of always versioning a changed formula is the entire point of the
    rule, and establishing a precedent of skipping it "just this once
    because no one's watching yet" is a worse habit to start than the
    cost of one extra version bump. Every `research_scores` row already
    persisted under `v1` is left as-is; nothing re-scores it
    retroactively. The 8 component *weights* (§2) themselves are
    unchanged between `v1` and `v2`.
  - The standalone Fundamental Score is versioned independently as
    `fundamental_score_v1` (`FUNDAMENTAL_SCORE_METHODOLOGY_VERSION`,
    `packages/scoring/constants.py`) since it's also consumed by
    `GET /fundamentals`, a different endpoint with its own version
    lifecycle.

## 1. The name and the number

The score is called **Research Strength**, not a prediction, not a
recommendation. Range: 0–100, never rounded internally (only at display
time).

## 2. Components and weights

| Component | Weight | Package function |
|---|---|---|
| Technical Structure | 20% | `score_technical_structure_points` |
| Momentum | 15% | `score_momentum_points` |
| Fundamentals | 20% | `compute_fundamental_score` (research_score_v2 — see §3.3, §10) |
| Valuation | 10% | `score_valuation_points` |
| Sector Relative Strength | 10% | `score_sector_relative_strength_points` |
| Market Regime | 10% | `market_regime_signal` |
| Risk Quality | 10% | `score_risk_quality_points` |
| Event / News Context | 5% | always unavailable in this version |

Weights are defined once in `packages/scoring/constants.py::COMPONENT_WEIGHTS`
and sum to exactly 1.0 (asserted at import time).

## 3. Per-component scoring convention

Every component starts at a **neutral baseline of 50** and accumulates a
point delta per available sub-signal (each sub-signal's band is listed
below), then **clamps to `[0, 100]`**. A sub-signal that cannot be
computed (missing input) contributes nothing — it is skipped, never
counted as 0 or as a reward. All band thresholds below are a documented
product judgment call (SPEC.md explicitly allows this, as long as it is
documented and deterministic — not an empirically fitted or ML-derived
number).

### 3.1 Technical Structure (`packages/scoring/signals.py::score_technical_structure_points`)

| Sub-signal | Condition | Delta |
|---|---|---|
| `close_vs_sma_50` | close > SMA50 / close < SMA50 | +10 / −10 |
| `close_vs_sma_200` | close > SMA200 / close < SMA200 | +10 / −10 |
| `sma_50_vs_sma_200` | SMA50 > SMA200 (golden-cross state) / < (death-cross state) | +10 / −10 |
| `ema_20_vs_ema_50` | EMA20 > EMA50 / < | +5 / −5 |
| `adx_14` | ADX≥25 (strong trend) / <15 (weak) / else | +10 / −5 / 0 |
| `breakout_20d` / `breakdown_20d` | new 20d high / new 20d low / neither | +10 / −10 / 0 |

### 3.2 Momentum (`score_momentum_points`)

| Sub-signal | Bands | Delta |
|---|---|---|
| `rsi_14` | >70 / 55–70 / 45–55 / 30–45 / <30 | +15 / +10 / 0 / −10 / −15 |
| `macd_histogram` | >0 / ≤0 | +10 / −10 |
| `roc_12` | >5% / 0–5% / −5–0% / <−5% | +10 / +5 / −5 / −10 |
| `stochastic_k` | >80 / <20 / else | +5 / −5 / 0 |

### 3.3 Fundamentals — now the Fundamental Score (`compute_fundamental_score`)

**research_score_v2 change**: this component's score is no longer a
single flat delta sum. It is now `sub_scores.overall` from
`packages/scoring/signals.py::compute_fundamental_score` — see §10 for
the full Fundamental Score methodology, which is reproduced here only
as a summary because this component **is** the Fundamental Score (same
function, same inputs, same number — single source of truth, §10.3).

Growth metrics need **≥2 reporting periods**; with only one period
available, growth is `None` (not 0) and that sub-signal is skipped.

| Sub-score | Weight within Fundamental Score | Sub-signals |
|---|---|---|
| Growth | 35% | `revenue_growth_yoy`, `pat_growth_yoy`, `eps_growth_yoy` |
| Profitability | 35% | `roe`, `roce_simplified`, `roa`, `net_profit_margin` |
| Leverage / Risk | 20% | `debt_to_equity`, `net_debt_to_ebitda`, `interest_coverage`, `current_ratio` |
| Efficiency | 10% | `asset_turnover` |

Each sub-score starts at the same neutral baseline of 50 and clamps to
`[0, 100]`, exactly like every other component (§3's convention). The
four weights above sum to 1.0 (`FUNDAMENTAL_SUBSCORE_WEIGHTS`,
`packages/scoring/constants.py` imports it from `signals.py`) and
renormalize over only the sub-scores with real data — identical
convention to §4's component-level renormalization, just one level
down: if, say, `current_ratio` is `None` (common for banks — their
balance sheets have no current/non-current split at all, confirmed
live against HDFCBANK, see DATA_SOURCES.md) but
`debt_to_equity`/`net_debt_to_ebitda`/`interest_coverage` are available
(banks *do* generally report a standalone interest-expense line - that
assumption was checked and corrected during development, see
DATA_SOURCES.md), the Leverage
sub-score still computes from those two alone; if *all four* leverage
inputs are `None`, the Leverage sub-score itself is `None` and is
excluded from the overall blend's numerator and denominator (never
treated as 0 or 50).

`ebitda_growth_yoy` and `financial_leverage`/`peg_ratio` are computed
and exposed on `/fundamentals` for transparency but are **not** part of
the score (documented decision to avoid double-counting growth/leverage
information already captured by the sub-signals above).

#### 3.3.1 Per-sub-signal bands

| Sub-signal | Bands | Delta |
|---|---|---|
| `revenue_growth_yoy` | ≥15% / 5–15% / 0–5% / −5–0% / <−5% | +15 / +8 / 0 / −8 / −15 |
| `pat_growth_yoy` | same bands | +15 / +8 / 0 / −8 / −15 |
| `eps_growth_yoy` | same bands, half weight | +10 / +5 / 0 / −5 / −10 |
| `roe` | ≥15% / 8–15% / 0–8% / <0% | +10 / +5 / 0 / −10 |
| `roce_simplified` | same bands as ROE | +10 / +5 / 0 / −10 |
| `roa` | ≥8% / 3–8% / 0–3% / <0% | +10 / +5 / 0 / −10 (lower-magnitude bands than ROE — total assets ≥ equity) |
| `net_profit_margin` | ≥15% / 5–15% / 0–5% / <0% | +10 / +5 / 0 / −10 |
| `debt_to_equity` | <0.3x / 0.3–0.6x / 0.6–1.0x / ≥1.0x | +15 / +5 / −5 / −15 (lower is better) |
| `net_debt_to_ebitda` | <1.0x / 1.0–2.0x / 2.0–3.5x / ≥3.5x | +15 / +5 / −5 / −15 (lower is better; standard analyst convention) |
| `interest_coverage` | ≥8x / 4–8x / 1.5–4x / <1.5x | +15 / +5 / −5 / −15 (higher is better) |
| `current_ratio` | ≥2.0x / 1.2–2.0x / 1.0–1.2x / <1.0x | +10 / +5 / −5 / −10 (higher is better; liquidity) |
| `asset_turnover` | ≥1.0x / 0.5–1.0x / 0.2–0.5x / <0.2x | +15 / +5 / −5 / −15 (sector-agnostic — a documented simplification, see §9) |

### 3.4 Risk Quality (`score_risk_quality_points`)

Lower volatility/drawdown → higher score (this is a *quality*, not a
*reward-for-risk*, component).

| Sub-signal | Bands | Delta |
|---|---|---|
| `atr_pct` (ATR14 / close × 100) | <1.5% / 1.5–3% / 3–5% / ≥5% | +15 / +5 / −5 / −15 |
| `rolling_volatility_20d_pct` (annualized) | <20% / 20–35% / 35–50% / ≥50% | +15 / 0 / −10 / −20 |
| `max_drawdown_pct` (over full available history) | <15% / 15–30% / 30–50% / ≥50% | +10 / 0 / −10 / −20 |

### 3.5 Sector Relative Strength (10%)

Reuses `packages.market_data.relative_strength.compute_relative_strength`
**directly** — the same function backing `GET /relative-strength` — no
duplicated logic. Uses the **3-month** horizon's `relative_strength_pct`
(stock return − sector-peer average return, in percentage points):

```
delta = clamp(relative_strength_pct, -40, 40)
score = clamp(50 + delta, 0, 100)
```

Unavailable (reason `insufficient_peer_universe` or
`insufficient_price_history`) if the sector has fewer than 2 other
seeded peers, or there isn't enough price history for the 3M horizon.
`peer_universe: "seeded_sector_peers"` always accompanies this — not a
licensed sector index.

### 3.6 Valuation (10%) — percentile vs. the active seeded universe

**Documented choice: percentile vs. the active seeded EQUITY universe**
(not a fixed reasonableness band), labeled
`valuation_universe_size={N}` everywhere it appears (previously a
hardcoded `"seeded_117"` label from when the universe was ~117
instruments; now reports the real, current peer-population size since
the universe has grown to ~750 — see `packages/market_data/universe.py`
and `DATA_SOURCES.md`), per the same honesty convention as
`breadth_universe`/`peer_universe`.

For each of P/E, P/B, EV/EBITDA (if the stock's own value is computable
*and* at least 5 peers in the universe have a computable value for that
metric):

```
percentile_cheaper = (# peers with a higher — i.e. more expensive — value) / (# peers) * 100
delta = (percentile_cheaper - 50) * 0.6     # scaled to [-30, +30]
```

`score = clamp(50 + mean(deltas across available metrics), 0, 100)`.
Unavailable (`valuation_metrics_unavailable`) if none of P/E/P/B/EV-EBITDA
are computable, or `no_fundamental_data` if there's no fundamentals
snapshot at all.

**Performance (fixed)**: the universe scan
(`packages.scoring.components._universe_valuation_values`) used to
re-query the full active-EQUITY universe on every single
valuation-component computation with no caching — O(N²) over a batch
run, fine at ~117 instruments (~2 minutes) but projected 40x+ worse
(likely over an hour) at ~750. Fixed by computing the scan **once** per
batch run (`apps/worker/jobs.py::compute_all_scores_job` computes it up
front and passes it to every instrument explicitly) and via a
15-minute, process-local TTL cache for the on-demand `/score` endpoint
(`packages.scoring.components.get_cached_universe_valuation_values`) —
same methodology, same percentile formula above, just computed far less
often. Real measurement after the fix: `compute_all_scores_job` across
755 active EQUITY instruments completed in ~53 seconds. See
`tests/unit/scoring/test_valuation_cache.py` for a test proving the
precomputed/cached path returns identical percentiles to a naive
per-instrument full rescan.

### 3.7 Market Regime (10%)

```
BULLISH_TREND -> 85   LOW_VOLATILITY -> 60   SIDEWAYS -> 50
TRANSITION    -> 50   HIGH_VOLATILITY -> 40  BEARISH_TREND -> 20
```

Taken directly from the latest `market_regimes` row (SPEC.md section
15/`packages/regime/`). Unavailable (`market_regime_not_computed`) if no
regime has ever been computed. Freshness decays fast relative to
fundamentals (regime should refresh daily): `freshness = max(0, 100 -
20 * age_days)`, i.e. fully stale after 5 days with no refresh.

### 3.8 Event / News Context (5%)

**Always unavailable in this version** (`available=False`, `score=None`,
`reason="no_news_data_source_in_this_version"`). There is no news
ingestion pipeline in this build (explicitly out of scope). This
component's full weight is excluded from every score's renormalization —
see §4.

## 4. Missing-component renormalization (exact formula)

```
available_weight = Σ weight[c]  for c in components if c.available and c.score is not None
score = Σ (c.score * c.weight)  for c in components if available   /  available_weight
```

- If `available_weight == 0` (every component missing), `score = None` —
  never a fabricated 0 or 50.
- Per component: `weight_used = c.weight / available_weight` (0 if
  unavailable); `contribution = c.score * weight_used`.
- **By construction, `Σ contribution == score`** — this is checked in
  `tests/unit/scoring/test_aggregate.py::test_renormalization_hand_computed_weighted_average`.
- A missing component is **never** treated as 0 and **never** treated as
  a neutral 50 — it is excluded from both the numerator and denominator
  entirely (SPEC.md section 86's explicit requirement).

Implementation: `packages/scoring/aggregate.py::aggregate_components`
(pure function, no DB — this is deliberate so the renormalization math
is testable independent of how any one component's score was derived).

## 5. Confidence formula (exact)

```
weight_coverage_pct = available_weight / total_weight * 100
freshness_avg = mean(c.freshness for c in components if c.available)   # 0 if nothing available
confidence = clamp(0.7 * weight_coverage_pct + 0.3 * freshness_avg, 0, 100)
```

- `freshness` is 0–100 **per component**, independent of that
  component's own score. Price-derived components (Technical, Momentum,
  Risk Quality, Sector Relative Strength, Market Regime's *trend* input)
  report `freshness=100` — they are always computed from the latest
  ingested bar, with staleness surfaced separately via each endpoint's
  own `data_freshness` block.
- Fundamentals/Valuation freshness decays with the age of the
  fundamentals snapshot used (`packages/fundamentals/derive.py::fundamentals_freshness_score`):
  `100` while `age_days ≤ 90`, linearly down to `0` at `age_days ≥ 720`.
- Market Regime freshness: `max(0, 100 - 20 * age_days)` (regime should
  refresh daily).
- **Score and confidence are always two independent numbers.** A stock
  can have `score=85, confidence=51` if its fundamentals are very stale
  even though every component still produced a number (SPEC.md section
  22) — confirmed by
  `tests/unit/scoring/test_aggregate.py::test_stale_fundamentals_reduces_confidence_without_changing_score`.

## 6. Score bands (`packages/scoring/bands.py`)

| Range | Band |
|---|---|
| 0–29 | Very Weak |
| 30–44 | Weak |
| 45–54 | Neutral |
| 55–69 | Moderate |
| 70–84 | Strong |
| 85–100 | Very Strong |

Bands are **descriptive only** — never auto-translated into Buy/Sell/Hold
anywhere in this codebase (SPEC.md sections 19, 61, 81 rule 21).

## 7. Evidence model (SPEC.md section 46)

Every sub-signal that contributes to a component's score becomes one
`evidence_items` row (`packages/scoring/evidence.py::EvidenceBuilder`),
with a deterministic, Python-string-templated interpretation (e.g.
`f"Price is {pct:.1f}% above the 50 DMA"`) — **never LLM-generated**.
`value_text` on `evidence_items` always holds this templated
interpretation sentence (a documented reuse of that column — see
`packages/scoring/models.py`); `value_numeric` holds the underlying
metric value when numeric.

Every evidence row is persisted (`session.add_all` + commit) **before**
the score response is returned, so every `evidence_id` referenced
anywhere in a `/score` response (per component, and in the bull/bear
case) is guaranteed to already exist in `evidence_items` — tested
end-to-end in `tests/unit/scoring/test_engine.py::test_full_score_computation_persists_real_evidence`
and `tests/api/test_score.py::test_score_and_evidence_round_trip`.

### Persistence model

`research_scores.components` (JSONB) embeds each component's
`evidence` as a list of `evidence_items.id` strings, rather than a
separate `score_evidence_links` join table. This is a documented choice:
every ID is independently verifiable against `evidence_items` (it's a
real foreign-key-shaped UUID, just not DB-enforced as one), and a join
table would add a layer of indirection without adding any traceability
this JSONB structure doesn't already provide at this scale.

### 7.1 Explanatory interpretation text (research_score_v2)

Every interpretation sentence in `packages/scoring/signals.py` now adds
two things beyond the bare fact, **both still 100% deterministic Python
f-string templates filled with real computed values — never an LLM call**
(SPEC.md section 2.3/81 rule 3):

1. **Why it matters** — a short, static, metric-specific clause
   explaining what the metric measures and why a reader should care
   (e.g. ADX: "ADX measures trend strength regardless of direction, and
   readings at or above 25 typically mark a tradable, momentum-friendly
   trend"). This text is the same for every reading of that metric — it
   doesn't vary with the number.
2. **A magnitude qualifier** — a short "a significant/moderate/mild
   {noun}" clause (`_qualifier` in `signals.py`) describing *how
   unusual* this particular reading is, relative to the real scoring
   bands already in this file. For every metric with a genuine
   multi-tier band (RSI, ROC, growth, ROE/ROCE, risk-quality metrics,
   leverage ratios, sector relative strength, valuation percentile,
   market regime), this qualifier is derived from `classify_strength(delta)`
   — i.e. it is a direct, honest translation of the exact band that
   already produced that signal's score contribution, never a second,
   disconnected scale (see §8.1 for the exact thresholds). For the two
   technical signals with only a single scoring threshold at zero
   (`close_vs_sma_50`/`close_vs_sma_200`/`ema_20_vs_ema_50` crossovers),
   the qualifier instead reads the underlying %-distance via
   `_pct_deviation_label` (`<3%` mild / `3–10%` moderate / `≥10%`
   significant) — these breakpoints deliberately bracket the same
   order-of-magnitude vocabulary this file already uses for ROC (5%)
   and ATR% (1.5/3/5%), rather than inventing a disconnected scale.

Example (technical, before → after, research_score_v1 → v2):

```
v1: "Price is 8.2% above the 50 DMA"
v2: "Price is 8.2% above the 50 DMA, an uptrend-consistent posture
     relative to this trend line (a moderate deviation from trend)."
```

Example (fundamentals growth):

```
v1: "Revenue grew +18.5% year-over-year"
v2: "Revenue grew +18.5% year-over-year - sustained top/bottom-line
     growth is one of the clearest signs a business is expanding its
     competitive position (a significant growth reading)."
```

See `tests/unit/scoring/test_signal_text.py` for exact-string tests
across one representative metric per evidence type, and
`tests/unit/scoring/test_signals.py` for the magnitude-qualifier
boundary tests.

## 8. Bull case / Bear case (scoped-down SPEC.md section 24)

**Not** the full AI bull/bear case (sections 24–26) — no LLM, no
narrative generation anywhere in this bucketing
(`packages/scoring/bull_bear.py`). Every `Signal` produced during
scoring already carries a `direction` (`+1` bullish / `-1` bearish / `0`
neutral) from the *exact same* deterministic band that produced its
score delta — not a second, independently-derived sign rule. Bucketing
rule:

- `direction > 0` → bull case
- `direction < 0` → bear case
- `direction == 0` → excluded from both

Each bucket is sorted by `abs(delta)` descending (**"magnitude of
deviation from neutral"**). Every entry references its real
`evidence_id`.

### 8.1 Strength tiers (research_score_v2, `BullBearEntry.strength`)

Every bull/bear entry also carries `strength`: `"strong"` / `"moderate"`
/ `"mild"`, computed once by `packages/scoring/signals.py::classify_strength`
at `Signal` construction time (`Signal.strength`, a derived/`init=False`
field) and copied verbatim onto the `BullBearEntry` — never recomputed
independently, so the badge the UI shows is always a faithful
reflection of the real point delta that signal contributed to the
score, not a second, disconnected scale.

**Exact thresholds** (`abs(delta)` is the signal's point contribution,
i.e. the exact number from §3's per-component band tables):

| `abs(delta)` | Strength |
|---|---|
| ≥ 15.0 | `"strong"` |
| ≥ 8.0 (and < 15.0) | `"moderate"` |
| < 8.0 | `"mild"` |

These two breakpoints (15.0, 8.0) are not new/arbitrary — they are the
two natural clusters that already recur throughout `signals.py`'s
hardcoded delta vocabulary: `5`/`10` for "secondary" sub-signals
(EMA-cross, stochastic, half-weight EPS growth, ATR-moderate) vs.
`15`/`20`/scaled-up-to-`30`–`40` for "primary" ones (RSI extremes,
full-weight revenue/PAT growth, breakout/breakdown, deep drawdowns,
large relative-strength/valuation gaps, extreme market regimes). See
`tests/unit/scoring/test_signals.py::TestClassifyStrength` for the exact
boundary tests (`15.0` → strong, `14.999` → moderate, `8.0` → moderate,
`7.999` → mild).

The UI (`apps/web/components/BullBearPanel.tsx`) renders this as a
pill badge reusing the existing `--up`/`--down` theme colors (the same
hue the Stage 2 pass/fail badge already uses) at varying
opacity/weight by tier, plus bolder body text for `"strong"` entries
and muted body text for `"mild"` ones — never a new color system.

## 9. Known limitations / deferrals

- **Event/News Context is always unavailable** — no news ingestion
  pipeline exists in this build.
- **Market regime breadth is `seeded_117`**, not real NSE/BSE market
  breadth (SPEC.md section 15; see `docs/architecture/market_regime.md`).
- **Valuation percentiles are vs. the active seeded EQUITY universe**
  (`valuation_universe_size={N}`, ~750 instruments as of the NSE Nifty
  Total Market universe backfill — see DATA_SOURCES.md), not the full
  real market. The full-universe scan is now computed once per batch
  run / short-TTL-cached for on-demand calls rather than recomputed on
  every single call — see §3.6 above.
- **yfinance fundamentals coverage for NSE tickers is inconsistent** —
  some stocks will have `has_fundamental_data: false` on
  `/fundamentals`, and their Fundamentals/Valuation score components
  will be `available: false`. This is a real, expected data-source gap
  (see DATA_SOURCES.md), not a bug.
- **Bull/bear lists are rule-based, not AI-narrated** — the full
  AI explanation layer (sections 25–26) is a later, explicitly
  out-of-scope phase.
- **Quick ratio is not implemented** — it needs an inventory figure,
  which neither yfinance's nor tradingview_ta's exposed fields for NSE
  tickers reliably provide. Current ratio (which doesn't need
  inventory) is implemented instead — see §10.
- **Current ratio is structurally unavailable for banks** — confirmed
  empirically (Oct 2026, HDFCBANK): `"Current Assets"`/`"Current
  Liabilities"` are not present in a bank's yfinance balance sheet at
  all (banks have no current/non-current split) and tradingview_ta's
  fallback fields were also `None` for HDFCBANK. This is a genuine
  sector-structural gap, not a provider bug. (`interest_expense`, by
  contrast, *is* generally available for banks too — confirmed live for
  HDFCBANK — so a bank's Leverage sub-score typically still gets 3 of 4
  sub-signals: Debt/Equity, Net Debt/EBITDA, and interest coverage;
  only current ratio is missing.)
- **Asset turnover bands are sector-agnostic** (§3.3.1) — a capital-light
  business (e.g. IT services) will score higher here than a
  capital-intensive one independent of either being the "better"
  business. Documented simplification, not a bug.
- **PEG ratio uses trailing EPS growth**, not a forward analyst-estimate
  growth rate (this codebase has no earnings-estimates data source) — a
  documented approximation to the conventional PEG definition.
- **Redis caching (fixed)** — `/score` used to recompute (and
  re-persist evidence for) a fresh score on *every* request, which grew
  `evidence_items`/`research_scores` unboundedly under repeated polling.
  Fixed via a Redis cache-aside layer (`packages/common/cache.py`):
  `/score` is now cache-first, keyed `score:v1:{instrument_id}`, 30
  minute TTL. `apps/worker/jobs.py::compute_all_scores_job` is the
  *primary* cache populator — it write-throughs every instrument's
  score into Redis immediately after persisting it, so the cache is
  warm immediately after every batch run; the on-demand route's own
  cache-miss path (which still does the full live-compute-and-persist
  flow, preserving the audit trail for anything the batch job hasn't
  covered yet) is only a safety net. `as_of_date`/`computed_at` in the
  response always reflect when the underlying score was actually
  computed, cache hit or not — a cache hit only means "served faster,"
  never "fresher" or "staler." Real measurement: a cold (cache-miss)
  `/score` call took ~5.5s; the next (cache-hit) call took ~0.004s.
  See `packages/scoring/engine.py`'s "Redis caching" comment and
  `tests/api/test_score_cache.py`.

## 10. Fundamental Score (`fundamental_score_v1`)

A standalone, 0–100 Fundamental Score + sub-score breakdown, exposed on
`GET /api/v1/stocks/{symbol}/fundamentals` as the `fundamental_score`
block, **and** the exact score backing the Research Score's
"fundamentals" component (§3.3) — see §10.3 for the single-source-of-
truth guarantee.

### 10.1 Sub-scores and combination weights

| Sub-score | Weight | Sub-signals (see §3.3.1 for bands) |
|---|---|---|
| Growth | 35% | revenue growth YoY, PAT growth YoY, EPS growth YoY |
| Profitability | 35% | ROE, simplified ROCE, ROA, net profit margin |
| Leverage / Risk | 20% | Debt/Equity, Net Debt/EBITDA, interest coverage, current ratio |
| Efficiency | 10% | asset turnover |

Weights are defined once in `packages/scoring/signals.py::FUNDAMENTAL_SUBSCORE_WEIGHTS`
and sum to exactly 1.0 (asserted at import time, same convention as
`COMPONENT_WEIGHTS`). **Why these weights**: Growth and Profitability
are weighted equally and highest (35% each) because they are the two
most direct, least sector-dependent reads on business quality; Leverage
is weighted meaningfully (20%) as a risk check but not equal to
growth/profitability since a conservative balance sheet alone doesn't
make a good investment; Efficiency is weighted lowest (10%) because
asset turnover is the most sector-dependent of the five sub-scores (see
§9) and is intended as a secondary signal, not a primary one.

```
overall = Σ (sub_score[s] * weight[s])  for s in sub_scores if sub_score[s] is not None
          / Σ weight[s]                 for s in sub_scores if sub_score[s] is not None
```

Identical renormalization convention to §4 (component-level): a `None`
sub-score (every one of its sub-signals unavailable) is excluded from
both the numerator and denominator, never treated as 0 or 50. If every
sub-score is `None`, `overall` is `None`.

### 10.2 Response shape

```json
"fundamental_score": {
  "overall": 83.05,
  "band": "Strong",
  "sub_scores": {
    "growth": 83.0,
    "profitability": 90.0,
    "leverage": 85.0,
    "efficiency": 55.0
  },
  "methodology_version": "fundamental_score_v1"
}
```

`band` reuses `packages/scoring/bands.py::score_band` — the exact same
Very Weak…Very Strong labels as the headline Research Score (§6), never
a second band vocabulary. `overall`/`band`/every `sub_scores` entry is
`null` (never 0/fabricated) when `has_fundamental_data: false` or when
every sub-score was `None`.

### 10.3 Single source of truth (hard requirement)

`packages/scoring/components.py::score_fundamentals` (the Research
Score's "fundamentals" component) and
`apps/api/routes/fundamentals.py::get_fundamentals` (the standalone
`fundamental_score` block) both call the exact same
`packages.scoring.signals.compute_fundamental_score` function, with the
exact same derived inputs computed from the exact same
`packages.fundamentals.derive` functions over the exact same latest
`FundamentalSnapshot` row. There is no second, independent
"fundamentals number" anywhere in this codebase that could silently
diverge from this one.

Proven by `tests/api/test_fundamental_score_single_source.py`, which
calls both `GET /score` and `GET /fundamentals` for the same instrument
and asserts the "fundamentals" component's `score` equals
`fundamental_score.overall` exactly (not just "close") — including a
case where the Leverage sub-score is degraded (bank-style, missing
interest_expense/current_assets/current_liabilities) to prove the
guarantee holds even when sub-score renormalization is in play.

### 10.4 New raw fields (migration `b7a1c9d4e821`)

`fundamental_snapshots.interest_expense` / `.current_assets` /
`.current_liabilities` — raw, nullable, never backfilled, same
convention as every other column on that table. See DATA_SOURCES.md for
the empirical verification of what yfinance/tradingview_ta actually
expose for these three fields.
