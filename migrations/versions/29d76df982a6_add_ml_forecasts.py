"""add_ml_forecasts

Revision ID: 29d76df982a6
Revises: c9d7eff3b859
Create Date: 2026-10-10 08:44:31.456269

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29d76df982a6'
down_revision: Union[str, Sequence[str], None] = 'c9d7eff3b859'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'ml_forecasts',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('instrument_id', sa.UUID(), sa.ForeignKey('instruments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('as_of_date', sa.Date(), nullable=False),
        sa.Column('horizon_days', sa.Integer(), nullable=False),
        sa.Column('trajectory', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('instrument_id', 'model_name', 'as_of_date', name='uq_ml_forecasts_inst_model_date')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ml_forecasts')
