"""`EvidenceBuilder` - the first-class evidence model (SPEC.md section 46).

Every score component (`packages/scoring/components.py`) builds its
`EvidenceItem` rows through one `EvidenceBuilder` per score computation,
so every number that feeds the Research Score is traceable back to a
persisted evidence row with its own ID (SPEC.md sections 1, 2.1, 104).

Interpretation strings are deterministic Python string templates - NEVER
an LLM call (SPEC.md section 81 rule 3; this whole package makes zero AI
calls). `EvidenceItem.value_text` always holds this templated sentence -
see `packages/scoring/models.py` docstring.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from packages.scoring.models import EvidenceItem


class EvidenceBuilder:
    """Accumulates `EvidenceItem` rows for one instrument's score computation.

    IDs are assigned client-side (`uuid.uuid4()`) at creation time, before
    any DB flush - this lets component-scoring functions reference an
    evidence item's ID immediately (e.g. in a component's `evidence: [...]`
    list) without needing to await a flush mid-computation. The caller
    (`packages.scoring.engine.compute_research_score`) is responsible for
    `session.add_all(builder.items)` + commit before the score response
    is returned, so every referenced ID is guaranteed to exist in the DB.
    """

    def __init__(self, instrument_id: uuid.UUID, methodology_version: str) -> None:
        self.instrument_id = instrument_id
        self.methodology_version = methodology_version
        self.items: list[EvidenceItem] = []

    def add(
        self,
        *,
        evidence_type: str,
        metric_name: str,
        interpretation: str,
        value_numeric: float | None,
        source_name: str,
        observed_at: datetime,
        source_timestamp: datetime,
        unit: str | None = None,
        published_at: datetime | None = None,
        source_reference: str | None = None,
        confidence: float | None = None,
    ) -> EvidenceItem:
        item = EvidenceItem(
            id=uuid.uuid4(),
            instrument_id=self.instrument_id,
            evidence_type=evidence_type,
            metric_name=metric_name,
            value_numeric=value_numeric,
            value_text=interpretation,
            unit=unit,
            observed_at=observed_at,
            published_at=published_at,
            source_name=source_name,
            source_reference=source_reference,
            source_timestamp=source_timestamp,
            methodology_version=self.methodology_version,
            confidence=confidence,
        )
        self.items.append(item)
        return item
