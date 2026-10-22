"""Fundamentals ORM model (SPEC.md sections 12, 13, 45).

`FundamentalSnapshot` stores exactly the raw reported values listed in
SPEC.md section 12's `fundamental_snapshot` table - never a derived
number (see `packages/fundamentals/derive.py` for everything computed on
top). Every financial column is nullable: yfinance's coverage for NSE
tickers is inconsistent, and a missing field must be stored as `NULL`,
never backfilled with 0 or any other placeholder (SPEC.md section 81
rule 8).

`dividend_yield` is the one field here that is not from the
income/balance/cashflow statements - it is yfinance's current,
point-in-time `Ticker.info["dividendYield"]`, refreshed on every sync
alongside the fiscal-period snapshot it's attached to. It is still a raw
provider-reported value (not derived by this codebase), which is why it
lives here rather than in `derive.py`. See SCORING.md / DATA_SOURCES.md.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from packages.common.models import Base


class FundamentalSnapshot(Base):
    __tablename__ = "fundamental_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "period_end", "period_type", "source", name="uq_fundamental_snapshot_period_source"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(8), nullable=False)  # "FY" or "TTM"

    revenue: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    ebitda: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    ebit: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    pat: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    eps: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    operating_cash_flow: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    free_cash_flow: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    total_assets: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    total_liabilities: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    cash: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    equity: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    # Added for the Fundamental Score's Leverage sub-score (SCORING.md,
    # migration b7a1c9d4e821) - empirically confirmed available from
    # yfinance. `interest_expense` is populated even for banks
    # (HDFCBANK). `current_assets`/`current_liabilities` are NULL for
    # banks specifically (their balance sheets have no current/
    # non-current split at all) - see DATA_SOURCES.md. Raw reported
    # values only, same nullable-by-default convention as every other
    # column here.
    interest_expense: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    current_assets: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    current_liabilities: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    # IMPORTANT unit note (verified against live yfinance data, Oct 2026):
    # `dividend_yield` is a raw passthrough of yfinance's `Ticker.info["dividendYield"]`,
    # which is already expressed in *percentage-point* units (e.g. 0.51
    # means "0.51%"), unlike every ratio this codebase derives itself
    # (ROE, growth rates, margins), which are plain fractions (0.0893 =
    # "8.93%"). Never multiply this field by 100 before displaying it -
    # see SCORING.md and `apps/web/components/FundamentalsPanel.tsx`.
    dividend_yield: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Per-field provenance (SPEC.md section 2.1 evidence-before-opinion /
    # section 13 "never overwrite raw source data"). `source` above
    # remains the *primary* provider for this row; `field_sources` is an
    # optional {field_name: provider_name} map recording which provider
    # actually supplied each individual value when a composite/fallback
    # provider filled in a field the primary provider left `NULL` (see
    # packages/fundamentals/providers/composite_provider.py). `NULL`/empty
    # for ordinary single-provider rows - this column exists so a filled
    # gap is always inspectable, never silently blurred into `source`.
    field_sources: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RawProviderScrape(Base):
    """Raw HTML backup ('Data Lake Bronze Layer') for a provider page.
    Allows re-parsing historical pages without re-fetching from the internet.
    """
    __tablename__ = "raw_provider_scrapes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    html_content: Mapped[str] = mapped_column(String, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())


class StructuredProviderData(Base):
    """Structured JSONB extraction of all tables from a provider page.
    ('Data Lake Silver Layer')
    """
    __tablename__ = "structured_provider_data"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())
    source_scrape_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_provider_scrapes.id", ondelete="SET NULL"), nullable=True
    )


class InstitutionalHolding(Base):
    """Institutional & Shareholding flow metrics (FII, DII, Promoter) extracted per instrument."""
    __tablename__ = "institutional_holdings"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
    )
    latest_quarter: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fii_current: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    fii_qoq_change: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True, index=True)
    dii_current: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    dii_qoq_change: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    promoter_current: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    promoter_qoq_change: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    public_current: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
