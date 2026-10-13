"""Bounded-row, hash-only inventory; no object access and no purge capability."""
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.db import Base

from app.execution.models import canonical_json
from app.execution.records import (ExecutionAccountRecord, ExecutionOrderRecord, ExecutionFillRecord,
    ExecutionPositionRecord, ExecutionTradeRecord, ExecutionMarkRecord)
from app.journal.records import JournalTradeRecord, JournalFillRecord, JournalAttachmentRecord, JournalAnnotationRecord
from app.retention.models import InventoryEntry, LIFECYCLE_SCAN_BATCH_ROWS
from app.retention.records import AccountLifecycleEventRecord

# Infrastructure admission only for this optional manifest, not account/strategy
# history truncation. Oversized rows make the manifest NOT_READY.
MAX_INVENTORY_ROW_BYTES = 8 * 1024 * 1024


def canonical_inventory(session: Session, account_id: str) -> dict[str, InventoryEntry]:
    inventory = {}
    direct = (ExecutionAccountRecord, ExecutionOrderRecord, ExecutionFillRecord,
        ExecutionPositionRecord, ExecutionTradeRecord, ExecutionMarkRecord,
        JournalTradeRecord, AccountLifecycleEventRecord)
    indirect = (JournalFillRecord, JournalAttachmentRecord, JournalAnnotationRecord)
    trade_ids = select(JournalTradeRecord.trade_id).where(JournalTradeRecord.account_id == account_id)
    for model in (*direct, *indirect):
        table = Base.metadata.tables[model.__tablename__]
        predicate = table.c.account_id == account_id if model in direct else table.c.trade_id.in_(trade_ids)
        query = select(table).where(predicate).order_by(*table.primary_key.columns)
        digest, count = sha256(), 0
        for row in session.execute(query.execution_options(yield_per=LIFECYCLE_SCAN_BATCH_ROWS)):
            encoded = canonical_json(dict(row._mapping)).encode('utf-8')
            if len(encoded) > MAX_INVENTORY_ROW_BYTES:
                raise ValueError('inventory row exceeds manifest byte bound')
            digest.update(len(encoded).to_bytes(8, 'big'))
            digest.update(encoded)
            count += 1
        inventory[table.name] = InventoryEntry(rows=count, content_hash=digest.hexdigest())
    return inventory
