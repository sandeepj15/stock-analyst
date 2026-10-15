import uuid
from datetime import date as date_
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.common.models import Base

class VcpScan(Base):
    __tablename__ = "vcp_scans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_date: Mapped[date_] = mapped_column(Date, nullable=False, index=True)
    is_vcp_setup: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pivot_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    stop_loss_price: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    risk_reward_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    num_contractions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contractions_depth: Mapped[list] = mapped_column(JSONB, nullable=True)
    vdu_flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
