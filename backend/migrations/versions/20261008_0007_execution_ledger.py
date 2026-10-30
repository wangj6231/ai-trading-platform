"""Internal provider-neutral PAPER execution ledger, separate from signals.

Revision ID: 20261008_0007
Revises: 20260904_0006
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261008_0007'
down_revision = '20260904_0006'
branch_labels = None
depends_on = None


def money(name, nullable=False):
    return sa.Column(name, sa.Numeric().with_variant(sa.String(128), 'sqlite'), nullable=nullable)


def doc(name):
    return sa.Column(name, sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=False)


def key(name, primary_key=False):
    return sa.Column(name, sa.String(128), primary_key=primary_key, nullable=False)


def instant(name, nullable=False, primary_key=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, primary_key=primary_key)


def upgrade():
    op.create_table('execution_accounts',
        key('account_id', True), key('execution_source'), key('execution_provider'),
        sa.Column('environment', sa.String(16), nullable=False),
        sa.Column('accounting_profile_version', sa.String(64), nullable=False),
        sa.Column('numeric_policy_version', sa.String(64), nullable=False),
        money('initial_balance'), money('cash_balance'), money('reserved_collateral'),
        instant('created_at'), sa.Column('last_sequence', sa.Integer(), nullable=False),
        sa.Column('command_sequence', sa.Integer(), nullable=False), doc('state'),
        sa.Column('state_hash', sa.String(64), nullable=False),
        sa.UniqueConstraint('account_id', 'execution_source'),
        sa.CheckConstraint("environment = 'PAPER'", name='execution_environment_paper'),
        sa.CheckConstraint('initial_balance > 0', name='execution_initial_positive'),
        sa.CheckConstraint('last_sequence >= 0 AND command_sequence >= 0', name='execution_sequences_nonnegative'))
    op.create_table('execution_orders', key('order_id', True), key('account_id'), key('execution_source'),
        key('command_id'), sa.Column('command_sequence', sa.Integer(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False), doc('intent'), doc('instrument_profile'), instant('accepted_at'), doc('state'),
        sa.UniqueConstraint('account_id', 'command_id'), sa.UniqueConstraint('account_id', 'command_sequence'),
        sa.UniqueConstraint('order_id', 'account_id', 'execution_source'),
        sa.ForeignKeyConstraint(['account_id', 'execution_source'], ['execution_accounts.account_id', 'execution_accounts.execution_source']),
        sa.CheckConstraint('command_sequence > 0', name='execution_command_positive'))
    op.create_table('execution_fills', key('event_id', True), key('account_id'), key('execution_source'),
        key('order_id'), key('external_fill_id'), sa.Column('execution_sequence', sa.Integer(), nullable=False),
        sa.Column('side', sa.String(8), nullable=False), money('price'), money('quantity'), money('fee'),
        sa.Column('fee_currency', sa.String(16), nullable=False), instant('filled_at'), instant('received_at'),
        sa.Column('economic_content_hash', sa.String(64), nullable=False), doc('payload'),
        sa.Column('processed', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('execution_source', 'account_id', 'external_fill_id', name='execution_fill_identity'),
        sa.UniqueConstraint('execution_source', 'account_id', 'execution_sequence', name='execution_fill_sequence'),
        sa.ForeignKeyConstraint(['order_id', 'account_id', 'execution_source'], ['execution_orders.order_id', 'execution_orders.account_id', 'execution_orders.execution_source']),
        sa.CheckConstraint('price > 0 AND quantity > 0 AND fee >= 0', name='execution_fill_positive'),
        sa.CheckConstraint('filled_at <= received_at', name='execution_fill_visible'),
        sa.CheckConstraint("side IN ('BUY', 'SELL') AND fee_currency = 'USDT'", name='execution_fill_units'),
        sa.CheckConstraint('execution_sequence > 0 AND processed', name='execution_fill_processed'))
    op.create_table('execution_positions', key('account_id', True), key('symbol', True),
        money('quantity'), money('remaining_cost_basis'), money('average_entry_price', True), doc('state'),
        sa.ForeignKeyConstraint(['account_id'], ['execution_accounts.account_id']),
        sa.CheckConstraint('quantity >= 0 AND remaining_cost_basis >= 0', name='execution_position_nonnegative'))
    op.create_table('execution_trades', key('trade_id', True), key('account_id'), money('gross_pnl'),
        money('total_fees'), money('net_pnl'), money('total_entry_notional'), money('pnl_percent', True),
        instant('closed_at', True), doc('state'),
        sa.ForeignKeyConstraint(['account_id'], ['execution_accounts.account_id']),
        sa.CheckConstraint('total_fees >= 0 AND total_entry_notional > 0', name='execution_trade_units'))
    op.create_table('execution_marks', key('account_id', True), key('symbol', True),
        instant('valuation_at', primary_key=True), money('price'), instant('received_at'),
        sa.Column('observation_hash', sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['execution_accounts.account_id']),
        sa.CheckConstraint('price > 0 AND valuation_at <= received_at', name='execution_mark_valid'))
    if op.get_bind().dialect.name == 'postgresql':
        _postgres_guards()


def _postgres_guards():
    op.execute("""
    CREATE FUNCTION protect_execution_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'execution ledger cannot be deleted' USING ERRCODE='23514';
      END IF;
      IF TG_TABLE_NAME IN ('execution_fills', 'execution_marks') AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'immutable confirmed execution fact' USING ERRCODE='23514';
      END IF;
      IF TG_TABLE_NAME = 'execution_accounts' AND
        (to_jsonb(NEW) - ARRAY['state','state_hash','cash_balance','reserved_collateral','last_sequence','command_sequence'])
        IS DISTINCT FROM
        (to_jsonb(OLD) - ARRAY['state','state_hash','cash_balance','reserved_collateral','last_sequence','command_sequence']) THEN
        RAISE EXCEPTION 'immutable account identity' USING ERRCODE='23514';
      END IF;
      IF TG_TABLE_NAME = 'execution_orders' THEN
        IF (to_jsonb(NEW) - 'state') IS DISTINCT FROM (to_jsonb(OLD) - 'state') OR
           (NEW.state - ARRAY['submission_status','external_order_id','rejection_reason','filled_quantity','cancelled_at','cancellation_status','last_observation_at'])
           IS DISTINCT FROM
           (OLD.state - ARRAY['submission_status','external_order_id','rejection_reason','filled_quantity','cancelled_at','cancellation_status','last_observation_at']) THEN
          RAISE EXCEPTION 'immutable order intent' USING ERRCODE='23514';
        END IF;
      END IF;
      IF TG_TABLE_NAME = 'execution_trades' THEN
        IF OLD.closed_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
          RAISE EXCEPTION 'immutable closed trade' USING ERRCODE='23514';
        END IF;
        IF (NEW.state - ARRAY['gross_pnl','total_fees','total_entry_notional','closed_at'])
           IS DISTINCT FROM (OLD.state - ARRAY['gross_pnl','total_fees','total_entry_notional','closed_at']) THEN
          RAISE EXCEPTION 'immutable trade origin/profile' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END; $$;
    """)
    for table in ('execution_accounts', 'execution_orders', 'execution_fills',
                  'execution_positions', 'execution_trades', 'execution_marks'):
        op.execute(f'CREATE TRIGGER {table}_history_guard BEFORE UPDATE OR DELETE ON {table} '
                   'FOR EACH ROW EXECUTE FUNCTION protect_execution_history()')
    # NUMERIC allows special values in PostgreSQL; reject them explicitly.
    columns = {
        'execution_accounts': ['initial_balance', 'cash_balance', 'reserved_collateral'],
        'execution_fills': ['price', 'quantity', 'fee'],
        'execution_positions': ['quantity', 'remaining_cost_basis', 'average_entry_price'],
        'execution_trades': ['gross_pnl', 'total_fees', 'net_pnl', 'total_entry_notional', 'pnl_percent'],
        'execution_marks': ['price'],
    }
    for table, names in columns.items():
        predicate = ' AND '.join(f"({name} IS NULL OR {name}::text NOT IN ('NaN','Infinity','-Infinity'))" for name in names)
        op.execute(f'ALTER TABLE {table} ADD CONSTRAINT {table}_finite CHECK ({predicate})')


def downgrade():
    for table in ('execution_marks', 'execution_trades', 'execution_positions',
                  'execution_fills', 'execution_orders', 'execution_accounts'):
        op.drop_table(table)
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP FUNCTION protect_execution_history()')
