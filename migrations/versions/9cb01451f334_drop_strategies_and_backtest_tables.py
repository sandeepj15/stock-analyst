"""drop strategies and backtest tables

Revision ID: 9cb01451f334
Revises: 24e15ddb9323
Create Date: 2026-10-05 17:11:51.367043

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9cb01451f334'
down_revision: Union[str, Sequence[str], None] = '24e15ddb9323'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOTE: hand-reordered from the raw `alembic revision --autogenerate`
    # output. Autogenerate does not topologically sort drops by FK
    # dependency, so it emitted `drop_table('strategy_versions')` before
    # `drop_table('backtests')` (which has a FK to it) and
    # `drop_table('strategies')` before `drop_table('backtest_trades')`
    # (which transitively depends on it via `backtests`). Postgres
    # refuses to DROP TABLE while a dependent FK constraint still exists,
    # so children must be dropped before their parents:
    # backtest_trades -> backtests -> strategy_versions -> strategies.
    op.drop_index(op.f('ix_backtest_trades_backtest_id'), table_name='backtest_trades')
    op.drop_table('backtest_trades')
    op.drop_index(op.f('ix_backtests_strategy_version_id'), table_name='backtests')
    op.drop_table('backtests')
    op.drop_index(op.f('ix_strategy_versions_strategy_id'), table_name='strategy_versions')
    op.drop_table('strategy_versions')
    op.drop_table('strategies')
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # NOTE: hand-reordered (see upgrade()) so parents are created before
    # the children whose FKs reference them: strategies ->
    # strategy_versions -> backtests -> backtest_trades.
    op.create_table('strategies',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(length=128), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('strategies_pkey'))
    )
    op.create_table('strategy_versions',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('strategy_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('version_number', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('definition', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['strategy_id'], ['strategies.id'], name=op.f('strategy_versions_strategy_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('strategy_versions_pkey')),
    sa.UniqueConstraint('strategy_id', 'version_number', name=op.f('uq_strategy_versions_strategy_version'), postgresql_include=[], postgresql_nulls_not_distinct=False)
    )
    op.create_index(op.f('ix_strategy_versions_strategy_id'), 'strategy_versions', ['strategy_id'], unique=False)
    op.create_table('backtests',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('strategy_version_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('instrument_ids', postgresql.ARRAY(sa.VARCHAR(length=64)), autoincrement=False, nullable=False),
    sa.Column('start_date', sa.DATE(), autoincrement=False, nullable=False),
    sa.Column('end_date', sa.DATE(), autoincrement=False, nullable=False),
    sa.Column('initial_capital', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('cost_config', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('position_sizing_config', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('status', sa.VARCHAR(length=16), autoincrement=False, nullable=False),
    sa.Column('methodology_version', sa.VARCHAR(length=32), autoincrement=False, nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('integrity_report', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('benchmark', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('overfitting_warning', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('equity_curve', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=False),
    sa.Column('error_message', sa.VARCHAR(length=1024), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['strategy_version_id'], ['strategy_versions.id'], name=op.f('backtests_strategy_version_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('backtests_pkey'))
    )
    op.create_index(op.f('ix_backtests_strategy_version_id'), 'backtests', ['strategy_version_id'], unique=False)
    op.create_table('backtest_trades',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('backtest_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('instrument_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('symbol', sa.VARCHAR(length=32), autoincrement=False, nullable=False),
    sa.Column('entry_date', sa.DATE(), autoincrement=False, nullable=False),
    sa.Column('entry_price', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=False),
    sa.Column('exit_date', sa.DATE(), autoincrement=False, nullable=True),
    sa.Column('exit_price', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('quantity', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('pnl', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
    sa.Column('exit_reason', sa.VARCHAR(length=32), autoincrement=False, nullable=True),
    sa.Column('holding_period_days', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['backtest_id'], ['backtests.id'], name=op.f('backtest_trades_backtest_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('backtest_trades_pkey'))
    )
    op.create_index(op.f('ix_backtest_trades_backtest_id'), 'backtest_trades', ['backtest_id'], unique=False)
    # ### end Alembic commands ###
