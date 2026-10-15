"""add_instrument_profile_and_about_fields

Revision ID: adf2bb95b124
Revises: 248cbed763ea
Create Date: 2026-10-13 14:36:35.844099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'adf2bb95b124'
down_revision: Union[str, Sequence[str], None] = '248cbed763ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('instruments', sa.Column('description', sa.String(), nullable=True))
    op.add_column('instruments', sa.Column('ai_summary', sa.String(), nullable=True))
    op.add_column('instruments', sa.Column('key_points', sa.String(), nullable=True))
    op.add_column('instruments', sa.Column('website_url', sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column('instruments', 'website_url')
    op.drop_column('instruments', 'key_points')
    op.drop_column('instruments', 'ai_summary')
    op.drop_column('instruments', 'description')
