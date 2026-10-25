"""Add covering composite index for ohlcv_daily 52-week and price calculations

Revision ID: e2f3a4b5c6d7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-25 15:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_ohlcv_inst_date_high_close 
        ON ohlcv_daily (instrument_id, trading_date DESC) 
        INCLUDE (high, close, adjusted_close);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ohlcv_inst_date_high_close;")
