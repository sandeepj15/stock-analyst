"""RS Rank: a documented, open-source-style approximation of IBD's "RS
Rating" (see MOMENTUM_SCANNER.md for the full write-up).

This is **not** the licensed/official IBD Relative Strength Rating -
it is a percentile rank computed only over this app's own seeded
instrument universe, using the commonly-published open-source
approximation of the underlying methodology. Every value this module
produces must be labeled `rs_rank_universe` (see `RS_RANK_UNIVERSE_LABEL`)
wherever it is surfaced (API responses, UI tooltips, docs) - the exact
same honesty convention this codebase already uses for
`peer_universe`/`breadth_universe`/`valuation_universe_size`
(SPEC.md sections 2.3, 21, 81 rule 23).

Formula
-------
1. Split the trailing 252 trading days (this codebase's "one year"
   convention, see `packages/analytics/price_structure.py`) of
   `adjusted_close` into four ~63-day quarters: Q1 = most recent 63
   bars, Q4 = oldest of the four.
2. `quarter_return = close[end] / close[start] - 1` for each quarter.
3. `raw_score = 2*Q1_return + Q2_return + Q3_return + Q4_return`
   (double-weighting the most recent quarter - the standard
   open-source approximation of IBD's publicized weighting scheme).
4. `rs_rank = percentile_rank(raw_score)` across every active EQUITY
   instrument in the universe with >= 252 trading days of history:
   0 = weakest raw_score in the universe, 100 = strongest.

Performance (SPEC.md section 81 rule 24, and the lesson already learned
the hard way for valuation percentiles - see
`packages/scoring/components.py`'s module-level comment): `raw_score`
must be computed exactly once per instrument, then the whole universe
ranked together in one O(n log n) sort - never recomputed per-pair
(O(n^2)). `apps/worker/jobs.py::compute_all_momentum_scans_job` is the
only caller that ranks a real universe; this module itself does no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

QUARTER_TRADING_DAYS = 63
RS_RANK_LOOKBACK_TRADING_DAYS = QUARTER_TRADING_DAYS * 4  # 252: this codebase's "one trading year" convention

# Documented honesty label (SPEC.md sections 2.3, 21, 81 rule 23) - the
# actual active-EQUITY universe size varies as instruments are seeded;
# callers that know the real-time count should prefer reporting that
# number directly (see valuation_universe_size's precedent in
# packages/scoring/components.py) alongside this fixed label.
RS_RANK_UNIVERSE_LABEL = "seeded_755"


@dataclass(frozen=True)
class RawScoreResult:
    """`raw_score` is `None` (never a fabricated number) when there isn't
    enough history to compute all four quarterly returns."""

    raw_score: float | None
    reason: str | None  # None when raw_score is populated; else e.g. "insufficient_price_history"


def compute_raw_score(adjusted_close: pd.Series) -> RawScoreResult:
    """`2*Q1 + Q2 + Q3 + Q4` quarterly-return score for one instrument.

    `adjusted_close` must be sorted ascending by date (the same
    convention every other analytics function in this codebase assumes).
    Requires at least `RS_RANK_LOOKBACK_TRADING_DAYS + 1` bars (252
    trading days of *returns* needs 253 price points); returns
    `reason="insufficient_price_history"` otherwise - never a fabricated
    score (SPEC.md section 81 rule 23).
    """
    required_points = RS_RANK_LOOKBACK_TRADING_DAYS + 1
    if len(adjusted_close) < required_points:
        return RawScoreResult(raw_score=None, reason="insufficient_price_history")

    window = adjusted_close.iloc[-required_points:]
    # `window` has 253 points: index 0 = "252 trading days ago", index
    # 252 = "today". Quarter boundaries, walking backwards in 63-bar
    # steps from today: Q1 = [189:252] (most recent), Q2 = [126:189],
    # Q3 = [63:126], Q4 = [0:63] (oldest).
    quarter_returns: list[float] = []
    last_idx = len(window) - 1
    for q in range(4):
        end_idx = last_idx - q * QUARTER_TRADING_DAYS
        start_idx = end_idx - QUARTER_TRADING_DAYS
        end_price = float(window.iloc[end_idx])
        start_price = float(window.iloc[start_idx])
        if start_price == 0:
            return RawScoreResult(raw_score=None, reason="insufficient_price_history")
        quarter_returns.append(end_price / start_price - 1.0)

    q1, q2, q3, q4 = quarter_returns
    raw_score = 2.0 * q1 + q2 + q3 + q4
    return RawScoreResult(raw_score=raw_score, reason=None)


def percentile_rank_universe(raw_scores: dict[str, float]) -> dict[str, float]:
    """0-100 percentile rank of each key's raw_score within `raw_scores`.

    O(n log n): sorts once, then assigns every value in a tied block the
    *average* rank across that block (standard fractional-rank tie
    handling) - never an O(n^2) pairwise comparison. `100` = the
    strongest (highest) raw_score in the population, `0` = the weakest.

    A single-instrument population has no meaningful relative rank;
    returns `50.0` (the only non-arbitrary neutral choice) in that case
    rather than fabricating a 0 or 100.
    """
    if not raw_scores:
        return {}
    n = len(raw_scores)
    if n == 1:
        return {symbol: 50.0 for symbol in raw_scores}

    ordered = sorted(raw_scores.items(), key=lambda kv: kv[1])
    ranks: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0  # 0-indexed average rank across the tied block [i, j]
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = avg_rank
        i = j + 1

    return {symbol: (rank / (n - 1)) * 100.0 for symbol, rank in ranks.items()}
