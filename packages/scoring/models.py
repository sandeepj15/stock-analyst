"""Evidence + Research Score ORM models (SPEC.md sections 17-22, 45-47).

- `EvidenceItem` is the first-class evidence model (SPEC.md section 46),
  schema matched exactly to the spec's `evidence_items` table.
- `ResearchScore` stores one row per score computation. The per-component
  breakdown (weight, weight_used, score, contribution, available,
  evidence IDs) is embedded in the `components` JSONB column rather than
  a separate `score_components`/`score_evidence_links` join table - a
  documented choice (see SCORING.md "Persistence model"): every evidence
  ID referenced in `components` is a real, already-committed
  `evidence_items.id` (tested in `tests/unit/scoring/test_engine.py`), so
  the join table would add a layer of indirection without adding any
  traceability this JSONB structure doesn't already give.

`value_text` on `EvidenceItem` always holds the deterministic templated
interpretation sentence for that evidence item (e.g. "Price is 8.2% above
the 50 DMA") - see `packages/scoring/evidence.py`. This is a documented
reuse of the spec's `value_text` column, not an extra undocumented field.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.common.models import Base


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "technical_structure", "fundamentals"
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "close_vs_50dma"
    value_numeric: Mapped[float | None] = mapped_column(Numeric(24, 6), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchScore(Base):
    __tablename__ = "research_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(32), nullable=False)
    components: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bull_case: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    bear_case: Mapped[list | None] = mapped_column(JSONB, nullable=True)
