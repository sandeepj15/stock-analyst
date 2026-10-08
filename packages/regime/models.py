"""Market regime ORM model (SPEC.md sections 15, 45, 47).

One row per `(date, rule_version)` - a new `rule_version` (e.g.
`regime_v2`) is additive, never a mutation of historical `regime_v1` rows
(SPEC.md section 47).
"""
from __future__ import annotations

import enum
import uuid
from datetime import date as date_
from datetime import datetime

from sqlalchemy import Date, DateTime, Enum, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.common.models import Base


class MarketRegimeLabel(enum.StrEnum):
    bullish_trend = "BULLISH_TREND"
    bearish_trend = "BEARISH_TREND"
    sideways = "SIDEWAYS"
    high_volatility = "HIGH_VOLATILITY"
    low_volatility = "LOW_VOLATILITY"
    transition = "TRANSITION"


class MarketRegime(Base):
    __tablename__ = "market_regimes"
    __table_args__ = (UniqueConstraint("date", "rule_version", name="uq_market_regimes_date_rule_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date: Mapped[date_] = mapped_column(Date, nullable=False, index=True)
    regime: Mapped[MarketRegimeLabel] = mapped_column(Enum(MarketRegimeLabel, name="market_regime_label"), nullable=False)
    nifty_close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    nifty_vs_200dma_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    breadth_above_50dma_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    breadth_above_200dma_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    rolling_volatility_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
