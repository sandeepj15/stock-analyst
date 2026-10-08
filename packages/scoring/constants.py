"""Research Strength weights + methodology version (SPEC.md section 17, 47).

Single source of truth for both `packages/scoring/components.py` (which
component gets how much weight) and `packages/scoring/aggregate.py`
(renormalization). If these weights ever change, bump
`METHODOLOGY_VERSION` and leave the prior version's values documented in
SCORING.md's history section - never silently reinterpret a historical
`research_scores` row under new weights (SPEC.md section 47, section 81
rule 6).

## Methodology version history

- `research_score_v1` (original): the "fundamentals" component scored a
  flat delta sum over revenue/PAT/EPS growth + ROE/simplified ROCE only.
- `research_score_v2` (current, 2026-10): the "fundamentals" component
  was refactored to call `packages/scoring/signals.py::compute_fundamental_score`
  - the same function that now backs the standalone Fundamental Score on
    `GET /api/v1/stocks/{symbol}/fundamentals` (single source of truth,
    see that module's docstring). This adds ROA, net profit margin,
    Debt/Equity, Net Debt/EBITDA, interest coverage, current ratio and
    asset turnover as new sub-signals feeding the component (previously
    exposed on `/fundamentals` for transparency only, or not computed at
    all), combined via four named sub-scores (Growth/Profitability/
    Leverage/Efficiency - see `FUNDAMENTAL_SUBSCORE_WEIGHTS` in
    `signals.py` and SCORING.md). The *component weight* (20% of the
    headline score) is unchanged; what changed is how that 20% itself is
    computed. **Decision**: bumped to `v2` rather than silently
    reinterpreting `v1` in place, even though SignalForge is still
    pre-launch with zero external users depending on score continuity -
    see SCORING.md's "Methodology version history" section for the full
    reasoning. Historical `research_scores` rows already persisted under
    `v1` are left as-is; nothing re-scores them retroactively.
- The 8 component *weights* below (`COMPONENT_WEIGHTS`) themselves have
  never changed between v1 and v2.
"""
from __future__ import annotations

METHODOLOGY_VERSION = "research_score_v3"

COMPONENT_WEIGHTS: dict[str, float] = {
    "technical_structure": 0.20,
    "momentum": 0.20,
    "fundamentals": 0.20,
    "valuation": 0.10,
    "sector_relative_strength": 0.10,
    "market_regime": 0.10,
    "risk_quality": 0.10,
}

assert abs(sum(COMPONENT_WEIGHTS.values()) - 1.0) < 1e-9, "COMPONENT_WEIGHTS must sum to 1.0"

# Standalone Fundamental Score methodology version (SCORING.md
# "Fundamental Score" section) - versioned independently of
# `METHODOLOGY_VERSION` above because it is consumed by two different
# callers (the Research Score's "fundamentals" component, and the
# standalone `fundamental_score` block on `/fundamentals`) that don't
# necessarily version in lockstep with the other 7 Research Score
# components.
FUNDAMENTAL_SCORE_METHODOLOGY_VERSION = "fundamental_score_v1"
