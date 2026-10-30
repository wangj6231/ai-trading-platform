"""Isolated replay of the existing public recovery regression, no shared DB DDL."""
import os
from tests.fixtures.foundation_capacity import owned_database
from tests.integration.test_execution_ledger import gateway
from tests.unit.test_journal_capture import test_rebuild_missing_references_preserves_notes_and_attachments


if __name__ == '__main__':
    with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, _nonce):
        test_rebuild_missing_references_preserves_notes_and_attachments(gateway.__wrapped__(database))
