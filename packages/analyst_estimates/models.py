"""Analyst-estimate ORM model.

`AnalystEstimate` stores exactly one row per instrument (unique on
`instrument_id`, upserted on every sync - see
`packages/analyst_estimates/ingestion.py`) holding the current analyst
consensus: this is deliberately **not** an append-only historical table
like `research_scores`/`fundamental_snapshots` - a 1-year price target
is a continuously-refreshed consensus, not tied to a specific reporting
period, so only the latest value is ever meaningful. `upside_pct`
(target vs. current price) is **not** stored here: it depends on the
always-changing current close price and is computed at request time by
`apps/api/routes/analyst.py`, consistent with how valuation metrics
elsewhere in this codebase are also computed on demand rather than
persisted (see `packages/fundamentals/derive.py::compute_valuation_metrics`).

Every numeric field is nullable - coverage is genuinely partial (many
mid/small-cap NSE names have zero analyst coverage); a missing field is
always `NULL`, never fabricated (SPEC.md section 81 rule 8).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.common.models import Base


class AnalystEstimate(Base):
    __tablename__ = "analyst_estimates"
    __table_args__ = (UniqueConstraint("instrument_id", name="uq_analyst_estimates_instrument"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )

    target_mean_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    target_high_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    target_low_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    target_median_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    # 1 (Strong Buy) - 5 (Sell), Wall-Street analyst scale (yfinance's
    # `recommendationMean` convention) - NOT a technical indicator score.
    recommendation_mean: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    recommendation_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    number_of_analyst_opinions: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Primary source for the headline `target_mean_price` (whichever
    # provider actually supplied it - see providers/composite_provider.py).
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Per-field provenance (same pattern as
    # `FundamentalSnapshot.field_sources`) - e.g.
    # {"target_mean_price": "tradingview_ta", "recommendation_mean": "yfinance"}.
    field_sources: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
