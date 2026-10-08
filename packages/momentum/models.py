"""`momentum_scans` ORM model (SPEC.md section 81 rule 14 - migrations for schema changes).

Append-only, one row per computation, mirroring
`packages.scoring.models.ResearchScore`'s persistence pattern exactly
(SPEC.md section 47's "never silently reinterpret historical data"
applied here too): a row is never mutated or deleted, only ever added.
Readers (API routes, the Redis cache write-through) always take the
most recently *persisted* row for an instrument/`scan_date`/
`sma200_trend_lookback_days`/`methodology_version` combination.
"""
from __future__ import annotations

import uuid
from datetime import date as date_
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.common.models import Base


class MomentumScan(Base):
    """One Stage 2 Trend Template evaluation for one instrument, as of `scan_date`.

    `passed` is `None` when the scan was not evaluable (insufficient
    price history) - never a fabricated PASS or FAIL (SPEC.md section
    81 rule 23). `conditions` is the full 8-condition breakdown (each a
    `{name, passed, value, threshold, description}` object - see
    `packages/momentum/scanner.py::ConditionResult`), empty when
    `passed` is `None`.
    """

    __tablename__ = "momentum_scans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_date: Mapped[date_] = mapped_column(Date, nullable=False, index=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    distance_from_52w_high_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    rs_rank: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    sma200_trend_lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<MomentumScan instrument_id={self.instrument_id} scan_date={self.scan_date} passed={self.passed}>"
