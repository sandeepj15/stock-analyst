"""Stage 2 Momentum Scanner package ("Minervini Trend Template").

See MOMENTUM_SCANNER.md for the full methodology write-up (the 8
conditions, the RS Rank formula, and the honesty labeling convention).

Layout mirrors `packages/scoring/`:
- `rs_rank.py` - universe-wide RS Rank (raw score + percentile).
- `scanner.py` - the pure 8-condition evaluator.
- `models.py` - the `momentum_scans` ORM model.

No LLM calls anywhere in this package (SPEC.md section 81 rule 3).
"""
from __future__ import annotations

from packages.momentum.models import MomentumScan
from packages.momentum.rs_rank import (
    RS_RANK_LOOKBACK_TRADING_DAYS,
    RS_RANK_UNIVERSE_LABEL,
    RawScoreResult,
    compute_raw_score,
    percentile_rank_universe,
)
from packages.momentum.scanner import (
    DEFAULT_SMA200_TREND_LOOKBACK_DAYS,
    METHODOLOGY_VERSION,
    MIN_TRADING_DAYS_REQUIRED,
    ConditionResult,
    MomentumScanResult,
    evaluate_stage2_momentum,
)
from packages.momentum.service import (
    ConditionOut,
    MomentumScanResponse,
    compute_momentum_scan,
    compute_universe_raw_scores,
    get_cached_universe_raw_scores,
)

__all__ = [
    "DEFAULT_SMA200_TREND_LOOKBACK_DAYS",
    "METHODOLOGY_VERSION",
    "MIN_TRADING_DAYS_REQUIRED",
    "ConditionOut",
    "ConditionResult",
    "MomentumScan",
    "MomentumScanResponse",
    "MomentumScanResult",
    "RS_RANK_LOOKBACK_TRADING_DAYS",
    "RS_RANK_UNIVERSE_LABEL",
    "RawScoreResult",
    "compute_momentum_scan",
    "compute_raw_score",
    "compute_universe_raw_scores",
    "evaluate_stage2_momentum",
    "get_cached_universe_raw_scores",
    "percentile_rank_universe",
]
