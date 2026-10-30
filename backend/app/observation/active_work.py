"""V1 logical projection of canonical work, not a copied order/financial ledger.

Keep this DDL version immutable: migration 0012 imports it. Future revisions
must introduce a new version rather than changing the historical definition.
"""
from sqlalchemy import Connection, text

VERSION = 'OBSERVATION_ACTIVE_WORK_V1'
VIEW = 'observation_active_work_v1'
PENDING = """state->>'submission_status' = 'ACKNOWLEDGED'
    AND state->>'cancelled_at' IS NULL
    AND (state->>'filled_quantity')::numeric < (intent->>'quantity')::numeric"""
OPEN_POSITIONS = "jsonb_path_exists(state, '$.positions[*] ? (@.quantity != \"0\")')"
VIEW_SQL = f"""CREATE OR REPLACE VIEW {VIEW} AS
    SELECT o.order_id AS work_id, o.account_id, a.execution_provider,
           o.intent->>'symbol' AS symbol, 'PENDING_ORDER'::text AS work_type,
           CASE WHEN o.state->>'last_observation_at' IS NOT NULL
             THEN (o.state->>'last_observation_at')::timestamptz + interval '1 minute'
             ELSE date_trunc('minute', o.accepted_at AT TIME ZONE 'UTC')
                  AT TIME ZONE 'UTC' + interval '1 minute' END AS next_open_at
    FROM execution_orders o JOIN execution_accounts a USING (account_id)
    WHERE {PENDING.replace('state', 'o.state').replace('intent', 'o.intent')}
    UNION ALL
    SELECT a.account_id || '/' || (p->>'symbol'), a.account_id, a.execution_provider,
           p->>'symbol', 'POSITION_MARK'::text, NULL::timestamptz
    FROM execution_accounts a CROSS JOIN LATERAL jsonb_array_elements(a.state->'positions') p
    WHERE {OPEN_POSITIONS.replace('state', 'a.state')}
      AND (p->>'quantity')::numeric <> 0
"""
INDEXES = (
    f"CREATE INDEX ix_observation_pending_symbol ON execution_orders ((intent->>'symbol'), account_id, accepted_at) WHERE {PENDING}",
)
FINGERPRINT_SQL = f"""SELECT encode(sha256(convert_to(
    pg_get_viewdef('{VIEW}'::regclass, true) ||
    pg_get_indexdef('ix_observation_pending_symbol'::regclass), 'UTF8')), 'hex')"""


def install_v1(connection: Connection) -> None:
    """Operator/migration-only atomic rebuild; canonical facts are untouched.

Caller owns a maintenance transaction. DDL locks can block writes; this is
not an HTTP operation or an automatic fallback on worker errors.
"""
    connection.execute(text("""CREATE TABLE IF NOT EXISTS observation_work_schema (
        singleton integer PRIMARY KEY CHECK (singleton = 1),
        version text NOT NULL, definition_hash text NOT NULL)"""))
    connection.execute(text(VIEW_SQL))
    for name in ('ix_observation_pending_symbol',):
        connection.execute(text(f'DROP INDEX IF EXISTS {name}'))
    for statement in INDEXES:
        connection.execute(text(statement))
    digest = connection.scalar(text(FINGERPRINT_SQL))
    connection.execute(text("""INSERT INTO observation_work_schema VALUES (1, :version, :digest)
        ON CONFLICT (singleton) DO UPDATE SET version=excluded.version, definition_hash=excluded.definition_hash"""),
        {'version': VERSION, 'digest': digest})


def remove_v1(connection: Connection) -> None:
    connection.execute(text(f'DROP VIEW {VIEW}'))
    for name in ('ix_observation_pending_symbol',):
        connection.execute(text(f'DROP INDEX {name}'))
    connection.execute(text('DROP TABLE observation_work_schema'))
