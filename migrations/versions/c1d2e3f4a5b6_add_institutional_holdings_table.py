"""add_institutional_holdings_table

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-10-19 16:50:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'institutional_holdings',
        sa.Column('instrument_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('instruments.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('latest_quarter', sa.String(length=32), nullable=True),
        sa.Column('fii_current', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('fii_qoq_change', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('dii_current', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('dii_qoq_change', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('promoter_current', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('promoter_qoq_change', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('public_current', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_institutional_holdings_fii_qoq_change', 'institutional_holdings', ['fii_qoq_change'])


def downgrade() -> None:
    op.drop_index('ix_institutional_holdings_fii_qoq_change', table_name='institutional_holdings')
    op.drop_table('institutional_holdings')
