"""add ml_forecast_evaluations

Revision ID: 5dc87366c535
Revises: 29d76df982a6
Create Date: 2026-10-10 08:47:27.515328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dc87366c535'
down_revision: Union[str, Sequence[str], None] = '29d76df982a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ml_forecasts', sa.Column('actual_trajectory', sa.JSON(), nullable=True))
    op.add_column('ml_forecasts', sa.Column('mape', sa.Float(), nullable=True))
    op.add_column('ml_forecasts', sa.Column('directional_accuracy', sa.Boolean(), nullable=True))
    op.add_column('ml_forecasts', sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ml_forecasts', 'evaluated_at')
    op.drop_column('ml_forecasts', 'directional_accuracy')
    op.drop_column('ml_forecasts', 'mape')
    op.drop_column('ml_forecasts', 'actual_trajectory')
