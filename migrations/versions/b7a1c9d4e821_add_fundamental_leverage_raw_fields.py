"""add interest_expense, current_assets, current_liabilities to fundamental_snapshots

Revision ID: b7a1c9d4e821
Revises: 00ab897c13e2
Create Date: 2026-10-05 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7a1c9d4e821'
down_revision: Union[str, Sequence[str], None] = '00ab897c13e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # New raw fields for the Fundamental Score's Leverage sub-score
    # (SCORING.md) - interest coverage and current ratio. Nullable, same
    # convention as every other fundamental_snapshots column: a missing
    # value (e.g. current_assets/current_liabilities for a bank, whose
    # balance sheet has no current/non-current split at all - see
    # DATA_SOURCES.md) stays NULL, never backfilled.
    op.add_column('fundamental_snapshots', sa.Column('interest_expense', sa.Numeric(24, 4), nullable=True))
    op.add_column('fundamental_snapshots', sa.Column('current_assets', sa.Numeric(24, 4), nullable=True))
    op.add_column('fundamental_snapshots', sa.Column('current_liabilities', sa.Numeric(24, 4), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('fundamental_snapshots', 'current_liabilities')
    op.drop_column('fundamental_snapshots', 'current_assets')
    op.drop_column('fundamental_snapshots', 'interest_expense')
