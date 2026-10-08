"""Deterministic, evidence-linked bull/bear case (SPEC.md section 24, scoped down).

**Not** the full AI bull/bear case from SPEC.md sections 24-26: there is
no LLM call and no narrative text anywhere in this module (SPEC.md
section 81 rule 3; see SCORING.md "Known limitations"). This is a
structured bucketing of the same `Signal`s already produced by
`packages/scoring/signals.py` during scoring - each signal already
carries a `direction` (+1 bullish / -1 bearish / 0 neutral, derived from
the exact same deterministic bands used for the score itself, not a
second independent rule) and a `delta` (points away from neutral, i.e.
"magnitude of deviation from neutral").

Bucketing rule (documented, per `evidence_type`): a signal with
`direction > 0` goes to the bull case, `direction < 0` goes to the bear
case, `direction == 0` (neutral) goes to neither. Each bucket is sorted
by `abs(delta)` descending.

Each entry also carries `strength` (`"strong"`/`"moderate"`/`"mild"`),
copied straight from the originating `Signal.strength`
(`packages/scoring/signals.py::classify_strength`) - computed from the
same `delta` that drives the sort order and the score contribution
itself, never a second, independently-invented scale. See SCORING.md's
"Bull case / Bear case" section for the exact thresholds.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from packages.scoring.signals import Signal


@dataclass(frozen=True)
class BullBearEntry:
    evidence_id: str
    metric_name: str
    interpretation: str
    magnitude: float
    strength: str


def build_bull_bear_case(
    signal_evidence_pairs: list[tuple[Signal, uuid.UUID]],
) -> tuple[list[BullBearEntry], list[BullBearEntry]]:
    bull: list[BullBearEntry] = []
    bear: list[BullBearEntry] = []

    for signal, evidence_id in signal_evidence_pairs:
        entry = BullBearEntry(
            evidence_id=str(evidence_id),
            metric_name=signal.metric_name,
            interpretation=signal.interpretation,
            magnitude=abs(signal.delta),
            strength=signal.strength,
        )
        if signal.direction > 0:
            bull.append(entry)
        elif signal.direction < 0:
            bear.append(entry)
        # direction == 0 (neutral) is excluded from both cases.

    bull.sort(key=lambda e: e.magnitude, reverse=True)
    bear.sort(key=lambda e: e.magnitude, reverse=True)
    return bull, bear
