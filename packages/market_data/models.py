"""Market-data ORM models (SPEC.md sections 10, 11, 45).

Tables:
- `ohlcv_daily`: daily bars, uniquely keyed by (instrument_id, trading_date,
  source) so the same instrument can carry bars from multiple providers
  without collision, and so idempotent upserts are possible (section 57).
- `data_ingestion_runs`: one row per ingestion attempt, used for
  observability or failure handling (sections 56-58).
- `data_quality_events`: structured output of the data quality layer
  (section 11) - these rows are informational only, they never cause the
  pipeline to silently mutate or drop data.

Plain PostgreSQL types are used throughout (no TimescaleDB), per SPEC.md
section 7.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.common.models import Base


class IngestionStatus(enum.StrEnum):
    running = "running"
    success = "success"
    failed = "failed"
    partial = "partial"


class QualityEventType(enum.StrEnum):
    schema = "schema"
    range = "range"
    duplicate = "duplicate"
    missing_data = "missing_data"
    outlier = "outlier"
    corporate_action = "corporate_action"


class QualitySeverity(enum.StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class OHLCVDaily(Base):
    """Daily OHLCV bar. See SPEC.md section 10 and 2.8 (adjustment policy).

    `close` is the raw, unadjusted close as reported by the source.
    `adjusted_close` is the source's adjusted close (splits/dividends per
    the source's own adjustment policy). The two are always stored
    separately - never collapse them into a single field.
    """

    __tablename__ = "ohlcv_daily"
    __table_args__ = (
        UniqueConstraint("instrument_id", "trading_date", "source", name="uq_ohlcv_daily_instrument_date_source"),
        Index("ix_ohlcv_daily_instrument_date", "instrument_id", "trading_date"),
        Index("ix_ohlcv_daily_trading_date", "trading_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
    )
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)

    open: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjusted_close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    data_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DataIngestionRun(Base):
    """One row per ingestion job attempt (SPEC.md sections 56-58)."""

    __tablename__ = "data_ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String(128), nullable=False)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, name="ingestion_status"), nullable=False, default=IngestionStatus.running
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataQualityEvent(Base):
    """Output of the data quality layer (SPEC.md section 11).

    These rows are purely observational - the quality layer never deletes
    or silently "fixes" data; it only records what it found here.
    """

    __tablename__ = "data_quality_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="SET NULL"), nullable=True
    )
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_ingestion_runs.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[QualityEventType] = mapped_column(Enum(QualityEventType, name="quality_event_type"), nullable=False)
    severity: Mapped[QualitySeverity] = mapped_column(Enum(QualitySeverity, name="quality_severity"), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
