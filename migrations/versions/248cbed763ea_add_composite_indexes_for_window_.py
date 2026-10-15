"""Add composite indexes for window functions

Revision ID: 248cbed763ea
Revises: a8386d45bba3
Create Date: 2026-10-11 01:00:58.345810

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '248cbed763ea'
down_revision: Union[str, Sequence[str], None] = 'a8386d45bba3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_vcp_scans_instrument_id_computed_at', 'vcp_scans', ['instrument_id', sa.text('computed_at DESC')])
    op.create_index('ix_research_scores_instrument_id_computed_at', 'research_scores', ['instrument_id', sa.text('computed_at DESC')])
    op.create_index('ix_momentum_scans_instrument_id_computed_at', 'momentum_scans', ['instrument_id', sa.text('computed_at DESC')])
    op.create_index('ix_ml_forecasts_instrument_id_created_at', 'ml_forecasts', ['instrument_id', sa.text('created_at DESC')])
    op.create_index('ix_fundamental_snapshots_instrument_id_period_end', 'fundamental_snapshots', ['instrument_id', sa.text('period_end DESC')])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_fundamental_snapshots_instrument_id_period_end', table_name='fundamental_snapshots')
    op.drop_index('ix_ml_forecasts_instrument_id_created_at', table_name='ml_forecasts')
    op.drop_index('ix_momentum_scans_instrument_id_computed_at', table_name='momentum_scans')
    op.drop_index('ix_research_scores_instrument_id_computed_at', table_name='research_scores')
    op.drop_index('ix_vcp_scans_instrument_id_computed_at', table_name='vcp_scans')
