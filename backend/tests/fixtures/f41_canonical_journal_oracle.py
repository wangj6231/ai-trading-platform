"""Frozen public attachment reader over the original canonical Journal oracle."""
from tests.fixtures.f4_canonical_journal_oracle import JournalService as CanonicalJournal
from tests.fixtures.f41_canonical_attachment_oracle import AttachmentReader


class JournalService(CanonicalJournal):
    def list_attachments(self, account_id, trade_id, query):
        return AttachmentReader(self.database, self.execution, self.clock).page(account_id, trade_id, query)
