"""Renderer contract only. No rendering, storage IO, worker, or retry execution."""
from typing import Literal, Protocol

from pydantic import Field, model_validator

from app.core.time import UtcDateTime
from app.execution.models import Identifier, StrictModel
from app.journal.models import AttachmentCompletion
from app.journal.storage import validate_storage_key
from app.schemas.types import Timeframe

SnapshotType = Literal['ENTRY_CHART', 'EXIT_CHART']


class SnapshotOrigin(StrictModel):
    """Confirmed execution reference, NOT strategy or rendered-market evidence."""
    trigger_event_id: Identifier
    execution_source: Identifier
    provider: Identifier
    adapter_version: Identifier


class SnapshotRequest(StrictModel):
    snapshot_job_id: Identifier
    trade_id: Identifier
    trading_account_id: Identifier
    type: SnapshotType
    symbol: Identifier
    timeframe: Timeframe | None = None
    snapshot_time: UtcDateTime
    origin: SnapshotOrigin


class RendererProvenance(StrictModel):
    renderer: Identifier
    version: Identifier


class SnapshotRenderResult(AttachmentCompletion):
    """Internal receipt contract. Not accepted by legacy completion persistence."""
    snapshot_job_id: Identifier
    trade_id: Identifier
    trading_account_id: Identifier
    attempt: int = Field(ge=1, strict=True)
    attempted_at: UtcDateTime
    finished_at: UtcDateTime
    rendered_at: UtcDateTime | None = None
    renderer_provenance: RendererProvenance | None = None

    @model_validator(mode='after')
    def render_shape(self):
        if self.finished_at < self.attempted_at:
            raise ValueError('render attempt times out of order')
        if self.status == 'READY':
            if (self.rendered_at is None or self.renderer_provenance is None
                    or not self.attempted_at <= self.rendered_at <= self.finished_at):
                raise ValueError('READY requires timed renderer provenance')
            assert self.storage_key is not None
            validate_storage_key(self.trading_account_id, self.trade_id, self.storage_key)
        elif self.rendered_at is not None:
            raise ValueError('FAILED cannot claim rendered evidence')
        return self


class JournalSnapshotRenderer(Protocol):
    def render(self, request: SnapshotRequest) -> SnapshotRenderResult:
        """Implementations must revalidate requests and return bounded safe receipts."""
        ...


def validate_render_result(request: SnapshotRequest, result: SnapshotRenderResult) -> SnapshotRenderResult:
    """Future trusted worker seam: never discard fields to fit legacy completion."""
    request = SnapshotRequest.model_validate(request.model_dump(mode='python'))
    result = SnapshotRenderResult.model_validate(result.model_dump(mode='python'))
    if ((result.snapshot_job_id, result.trade_id, result.trading_account_id)
            != (request.snapshot_job_id, request.trade_id, request.trading_account_id)
            or result.attempted_at < request.snapshot_time):
        raise ValueError('renderer receipt/request binding mismatch')
    return result
