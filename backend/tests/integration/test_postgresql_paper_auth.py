"""Real server credentials and account ownership on isolated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.auth.records import PaperAccountOwnershipRecord
from app.auth.service import PaperAuthService
from tests.integration import test_execution_ledger as execution_pg
from tests.unit import test_paper_auth as cases

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    yield from execution_pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', [
    cases.test_rotation_preserves_subject_and_server_account_scope,
    cases.test_mounted_paper_routes_resolve_credentials_not_client_identity,
    cases.test_revocation_rotation_and_expiry_use_current_server_state,
    cases.test_legacy_account_requires_explicit_provision_and_removal_takes_effect,
    cases.test_duplicate_authorization_headers_fail_closed,
    cases.test_authorized_commands_retries_versions_and_foreign_children_unchanged,
    cases.test_auth_infrastructure_failure_is_redacted_and_not_authenticated,
    cases.test_server_provisioning_rejects_missing_targets_and_invalid_expiry,
    cases.test_custom_verifier_cannot_supply_unregistered_subject,
], ids=lambda scenario: scenario.__name__)
def test_real_auth_contract_on_postgresql(gateway, scenario):
    scenario(gateway)


def test_secret_storage_and_redaction_on_postgresql(gateway, caplog):
    cases.test_raw_secret_not_stored_logged_or_exposed(gateway, caplog)


@pytest.mark.parametrize('suffix,method,body', [('', 'GET', None),
    ('/orders', 'POST', dict(command_id='foreign', symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='1')),
    ('/journal/absent/metadata', 'PATCH', {'expected_version': 0}),
    ('/analytics', 'GET', None), ('/trades/absent/attachments', 'GET', None)])
def test_owned_accounts_are_isolated_on_postgresql(gateway, suffix, method, body):
    cases.test_every_route_denies_another_owners_account(gateway, suffix, method, body)


def test_concurrent_provisioning_has_exactly_one_owner(gateway):
    execution, clock, database = gateway
    auth = PaperAuthService(database, clock=lambda: clock[0])
    subjects = (auth.create_subject(), auth.create_subject())
    account = execution.create_account(execution_source='concurrent-ownership')
    def bind(subject):
        try:
            auth.bind_account(subject, account.account_id)
            return subject
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        owners = list(pool.map(bind, subjects))
    assert sum(owner is not None for owner in owners) == 1
    for subject in subjects:
        issued = auth.issue_credential(subject)
        principal = auth.authenticate('Bearer ' + issued.token.get_secret_value())
        assert (account.account_id in principal.account_ids) == (subject in owners)


def test_database_rejects_second_owner_and_unknown_subject(gateway):
    execution, clock, database = gateway
    auth = PaperAuthService(database, clock=lambda: clock[0])
    subject = auth.create_subject()
    other = auth.create_subject()
    account = execution.create_account(execution_source='db-owner-constraint')
    auth.bind_account(subject, account.account_id)
    with pytest.raises(IntegrityError), database.transaction() as session:
        session.add(PaperAccountOwnershipRecord(account_id=account.account_id, subject_id=other, created_at=clock[0]))
    orphan = execution.create_account(execution_source='db-orphan-constraint')
    with pytest.raises(IntegrityError), database.transaction() as session:
        session.add(PaperAccountOwnershipRecord(account_id=orphan.account_id, subject_id='missing', created_at=clock[0]))
    with database.read_session() as session:
        assert session.scalar(select(PaperAccountOwnershipRecord.subject_id).where(
            PaperAccountOwnershipRecord.account_id == account.account_id)) == subject


def test_auth_migration_downgrade_reupgrade_does_not_claim_existing_accounts(gateway):
    from alembic import command
    from alembic.config import Config
    from tests.integration.test_postgresql_persistence import BACKEND_ROOT
    execution, _, database = gateway
    account = execution.create_account(execution_source='roundtrip-legacy')
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('sqlalchemy.url', database.engine.url.render_as_string(hide_password=False))
    command.downgrade(config, '20261009_0009')
    assert 'auth_subjects' not in inspect(database.engine).get_table_names()
    command.upgrade(config, 'head')
    auth = PaperAuthService(database)
    subject = auth.create_subject()
    issued = auth.issue_credential(subject)
    assert account.account_id not in auth.authenticate('Bearer ' + issued.token.get_secret_value()).account_ids
    assert execution.get_account(account.account_id).cash_balance == account.cash_balance
    with database.read_session() as session:
        from alembic.script import ScriptDirectory
        assert session.scalar(text('SELECT version_num FROM alembic_version')) == ScriptDirectory.from_config(config).get_current_head()
