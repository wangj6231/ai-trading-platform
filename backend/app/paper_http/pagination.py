"""Authenticated opaque transport cursors. A cursor is NOT an auth credential."""
import base64
from datetime import datetime
from hashlib import sha256
import hmac
import json

from pydantic import Field

from app.core.time import UtcDateTime
from app.execution.models import Identifier, StrictModel, canonical_json
from app.paper_http.errors import ErrorCode, error
from app.paper_http.models import MAX_CURSOR_LENGTH


class Cursor(StrictModel):
    version: int = Field(default=1, ge=1, le=1, strict=True)
    scope: str = Field(pattern=r'^[a-f0-9]{64}$')
    as_of: UtcDateTime
    after_at: UtcDateTime
    after_id: Identifier
    membership_hash: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class CursorCodec:
    def __init__(self, key: bytes):
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError('cursor signing key requires at least 32 server-owned bytes')
        self.key = key

    def encode(self, cursor: Cursor) -> str:
        payload = canonical_json(cursor).encode('utf-8')
        signature = hmac.digest(self.key, payload, sha256)
        token = base64.urlsafe_b64encode(signature + payload).decode('ascii').rstrip('=')
        if len(token) > MAX_CURSOR_LENGTH:
            raise error(ErrorCode.EXECUTION_INTERNAL_ERROR, 500)
        return token

    def decode(self, token: str, *, scope: str, now: datetime) -> Cursor:
        try:
            if len(token) > MAX_CURSOR_LENGTH or not token or not token.isascii():
                raise ValueError('cursor length')
            raw = base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True)
            signature, payload = raw[:32], raw[32:]
            if not hmac.compare_digest(signature, hmac.digest(self.key, payload, sha256)):
                raise ValueError('signature')
            cursor = Cursor.model_validate(json.loads(payload))
            if cursor.scope != scope or cursor.as_of > now or cursor.after_at > cursor.as_of:
                raise ValueError('scope/cutoff')
            return cursor
        except (ValueError, TypeError, UnicodeError):
            raise error(ErrorCode.VALIDATION_ERROR, 422) from None
