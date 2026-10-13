"""Opaque object keys, never filesystem paths or public/signed URLs."""
import re

from app.execution.models import content_hash

MAX_STORAGE_KEY_LENGTH = 512


def storage_prefix(account_id: str, trade_id: str) -> str:
    return f'journal/{content_hash(account_id)}/{content_hash(trade_id)}/'


def validate_storage_key(account_id: str, trade_id: str, key: str) -> str:
    if (not 1 <= len(key) <= MAX_STORAGE_KEY_LENGTH
            or not key.startswith(storage_prefix(account_id, trade_id))
            or re.fullmatch(r'[A-Za-z0-9_/.-]+', key) is None
            or any(part in ('', '.', '..') for part in key.split('/'))):
        raise ValueError('invalid account-scoped storage key')
    return key
