"""Shared SQLAlchemy declarative base + the instrument master model.

Model layout decision (documented here and in README.md):
- `packages/common/models.py` holds the ORM `Base` and cross-cutting
  tables that other packages reference (currently: `instruments`).
- `packages/market_data/models.py` holds market-data-specific tables
  (`ohlcv_daily`, `data_ingestion_runs`, `data_quality_events`) and
  imports `Base`/`Instrument` from here.

This keeps a single declarative `Base` (required for Alembic autogenerate
to see all tables) while letting each domain package own its own tables.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func, Float, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Instrument(Base):
    """Instrument master (SPEC.md section 9).

    ISIN is preferred as the stable identifier where available, but the
    enforced uniqueness constraint is (exchange, symbol) per the spec.
    Company name must never be used as a primary identifier.
    """

    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("exchange", "symbol", name="uq_instruments_exchange_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True, unique=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(32), nullable=False, default="EQUITY")
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    lot_size: Mapped[int] = mapped_column(default=1)
    tick_size: Mapped[float] = mapped_column(Numeric(10, 4), default=0.05)
    listing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delisting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Company overview & profiles (scraped from Screener.in + AI generated summaries)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    key_points: Mapped[str | None] = mapped_column(String, nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<Instrument {self.exchange}:{self.symbol}>"


class InstrumentAlias(Base):
    """Minimal `instrument_aliases` table (SPEC.md section 45).

    Exists so a renamed/symbol-changed instrument (SPEC.md section 11's
    "symbol changes" corporate-action type - see
    `packages/market_data/corporate_actions.py`) can still be found by
    its *old* symbol without duplicating the instrument row or losing
    the history/evidence/scores already attached to it. Deliberately
    minimal: just enough to resolve an old symbol to the current
    `instruments.id` - this is not a general-purpose corporate-actions
    history table (that's `corporate_actions` per SPEC.md section 45,
    not yet built).
    """

    __tablename__ = "instrument_aliases"
    __table_args__ = (UniqueConstraint("exchange", "symbol", name="uq_instrument_aliases_exchange_symbol"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE")
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:  # pragma: no cover - debug convenience only
        return f"<InstrumentAlias {self.exchange}:{self.symbol} -> {self.instrument_id}>"

from sqlalchemy.dialects.postgresql import JSONB

class MLForecast(Base):
    __tablename__ = "ml_forecasts"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    trajectory: Mapped[dict] = mapped_column(JSONB, nullable=False)
    actual_trajectory: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    directional_accuracy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
