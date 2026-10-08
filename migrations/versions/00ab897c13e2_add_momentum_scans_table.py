"""add momentum_scans table (Stage 2 Momentum Scanner)

Revision ID: 00ab897c13e2
Revises: 9cb01451f334
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '00ab897c13e2'
down_revision: Union[str, Sequence[str], None] = '9cb01451f334'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'momentum_scans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('instrument_id', sa.UUID(), nullable=False),
        sa.Column('scan_date', sa.Date(), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=True),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('distance_from_52w_high_pct', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('rs_rank', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('sma200_trend_lookback_days', sa.Integer(), nullable=False),
        sa.Column('methodology_version', sa.String(length=32), nullable=False),
        sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_momentum_scans_instrument_id'), 'momentum_scans', ['instrument_id'], unique=False)
    op.create_index(op.f('ix_momentum_scans_scan_date'), 'momentum_scans', ['scan_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_momentum_scans_scan_date'), table_name='momentum_scans')
    op.drop_index(op.f('ix_momentum_scans_instrument_id'), table_name='momentum_scans')
    op.drop_table('momentum_scans')
