"""add analyst_estimates table

Revision ID: 73b44834d950
Revises: b7a1c9d4e821
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '73b44834d950'
down_revision: Union[str, Sequence[str], None] = 'b7a1c9d4e821'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # One row per instrument (unique on instrument_id, upserted on every
    # sync) - a 1-year analyst price target is a continuously-refreshed
    # consensus, not tied to a reporting period, so this is deliberately
    # not an append-only history table like fundamental_snapshots/
    # research_scores. See packages/analyst_estimates/models.py.
    op.create_table(
        'analyst_estimates',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('instrument_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('target_mean_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('target_high_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('target_low_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('target_median_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('recommendation_mean', sa.Numeric(6, 4), nullable=True),
        sa.Column('recommendation_key', sa.String(32), nullable=True),
        sa.Column('number_of_analyst_opinions', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(64), nullable=False),
        sa.Column('source_timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('field_sources', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ingested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instrument_id', name='uq_analyst_estimates_instrument'),
    )
    op.create_index(op.f('ix_analyst_estimates_instrument_id'), 'analyst_estimates', ['instrument_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_analyst_estimates_instrument_id'), table_name='analyst_estimates')
    op.drop_table('analyst_estimates')
