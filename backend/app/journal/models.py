from datetime import timedelta
from typing import Literal
from enum import Enum
import unicodedata

from pydantic import Field, field_validator, model_validator

from app.core.time import UtcDateTime
from app.execution.models import ExecutionEvent, Identifier, Money, StrictModel

MAX_NOTE_LENGTH = 4000
MAX_TAG_COUNT = 20
MAX_TAG_LENGTH = 40
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class JournalResult(str, Enum):
    WIN = 'WIN'
    LOSS = 'LOSS'
    BREAKEVEN = 'BREAKEVEN'


class AttachmentCompletion(StrictModel):
    status: Literal['READY', 'FAILED']
    storage_key: str | None = Field(default=None, min_length=1, max_length=512)
    mime_type: Literal['image/png', 'image/jpeg', 'image/webp'] | None = None
    file_size: int | None = Field(default=None, gt=0, le=MAX_ATTACHMENT_BYTES, strict=True)
    failure_reason: Literal['RENDERER_NOT_CONFIGURED', 'RENDER_FAILED', 'STORAGE_FAILED'] | None = None

    @model_validator(mode='after')
    def completion_shape(self):
        values = (self.storage_key, self.mime_type, self.file_size)
        if self.status == 'READY':
            if any(v is None for v in values) or self.failure_reason is not None:
                raise ValueError('READY requires bounded stored object metadata')
        elif any(v is not None for v in values) or self.failure_reason is None:
            raise ValueError('FAILED requires redacted reason and no object metadata')
        return self


class AnnotationPatch(StrictModel):
    notes: str = Field(default='', max_length=MAX_NOTE_LENGTH)
    tags: tuple[str, ...] = Field(default=(), max_length=MAX_TAG_COUNT)

    @field_validator('notes')
    @classmethod
    def safe_notes(cls, value):
        if any(unicodedata.category(c).startswith('C') and c not in '\n\r\t' for c in value):
            raise ValueError('control character in journal note')
        return value

    @field_validator('tags')
    @classmethod
    def safe_tags(cls, value):
        if (len(set(value)) != len(value) or any(not tag.strip() or tag != tag.strip()
            or len(tag) > MAX_TAG_LENGTH or any(unicodedata.category(c).startswith('C') for c in tag) for tag in value)):
            raise ValueError('invalid journal tags')
        return value


class Annotations(AnnotationPatch):
    version: int = Field(ge=1, strict=True)
    created_at: UtcDateTime
    updated_at: UtcDateTime


class FillReference(StrictModel):
    role: Literal['ENTRY', 'EXIT']
    event: ExecutionEvent


class Attachment(StrictModel):
    attachment_id: Identifier
    trade_id: Identifier
    type: Literal['ENTRY_CHART', 'EXIT_CHART', 'USER_UPLOAD']
    status: Literal['PENDING', 'READY', 'FAILED']
    created_at: UtcDateTime
    snapshot_time: UtcDateTime | None = None
    timeframe: None = None
    storage_key: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    completed_at: UtcDateTime | None = None
    failure_reason: str | None = None

    @model_validator(mode='after')
    def status_shape(self):
        if self.status != 'PENDING':
            AttachmentCompletion.model_validate(dict(status=self.status, storage_key=self.storage_key,
                mime_type=self.mime_type, file_size=self.file_size, failure_reason=self.failure_reason))
            if self.completed_at is None or self.completed_at < self.created_at:
                raise ValueError('invalid attachment completion time')
        elif any(v is not None for v in (self.storage_key, self.mime_type, self.file_size,
                                         self.completed_at, self.failure_reason)):
            raise ValueError('PENDING attachment has no completion evidence')
        return self


class JournalTrade(StrictModel):
    trade_id: Identifier
    journal_trade_id: Identifier
    trading_account_id: Identifier
    execution_source: Identifier
    symbol: Identifier
    side: Literal['LONG', 'SHORT']
    status: Literal['OPEN', 'PARTIALLY_CLOSED', 'CLOSED']
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None
    finalized_at: UtcDateTime | None
    quantity: Money
    remaining_quantity: Money
    average_entry_price: Money
    average_exit_price: Money | None
    gross_pnl: Money
    total_fees: Money
    net_pnl: Money
    pnl_percent: Money | None
    r_multiple: None = None
    result: JournalResult | None
    holding_duration: timedelta | None
    strategy_attribution: None = None
    accounting_profile_version: Identifier
    numeric_policy_version: Identifier
    fills: tuple[FillReference, ...]
    attachments: tuple[Attachment, ...] = ()
    annotations: Annotations | None = None
