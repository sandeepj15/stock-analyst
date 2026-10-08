"""SignalForge Research Score engine - "Research Strength v1" (SPEC.md sections 17-22, 24, 46-47, Phase 3).

No LLM calls anywhere in this package (SPEC.md section 81 rule 3). See
SCORING.md for the full methodology (weights, per-component bands,
missing-component renormalization, confidence formula, bull/bear
bucketing rule, score bands).

Layout:
- `models.py`: `evidence_items` and `research_scores` ORM tables.
- `evidence.py`: `EvidenceBuilder`, the first-class evidence model.
- `signals.py`: pure per-metric point/band functions (hand-value-tested).
- `components.py`: DB-backed wrappers that turn signals into `EvidenceItem`s.
- `aggregate.py`: renormalization + confidence (pure, heavily tested).
- `bands.py`: score band labels.
- `bull_bear.py`: deterministic, evidence-linked bull/bear bucketing.
- `engine.py`: `compute_research_score`, the single entry point.
"""
from __future__ import annotations

from packages.scoring.bands import score_band
from packages.scoring.constants import COMPONENT_WEIGHTS, METHODOLOGY_VERSION
from packages.scoring.engine import ResearchScoreResult, compute_research_score
from packages.scoring.models import EvidenceItem, ResearchScore

__all__ = [
    "COMPONENT_WEIGHTS",
    "METHODOLOGY_VERSION",
    "ResearchScoreResult",
    "compute_research_score",
    "score_band",
    "EvidenceItem",
    "ResearchScore",
]
