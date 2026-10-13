from __future__ import annotations

from datetime import UTC, datetime
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer


_temporal_memo: ContextVar[dict[tuple[datetime, int], str] | None] = ContextVar("evaluation_temporal_memo", default=None)


@contextmanager
def evaluation_temporal_scope() -> Iterator[None]:
    """Memoize pure UTC serialization for this one invocation, then discard."""
    if _temporal_memo.get() is not None:
        yield
        return
    token = _temporal_memo.set({})
    try:
        yield
    finally:
        _temporal_memo.reset(token)


def normalize_utc_datetime(value: Any) -> datetime:
    """Return one explicit instant in UTC without inferring a local timezone."""

    # An exact native datetime with the UTC singleton is already aware and
    # normalized. Subclasses retain their original offset/conversion checks.
    if type(value) is datetime and value.tzinfo is UTC:
        return value
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "trusted datetime must be a valid ISO-8601 datetime with UTC offset"
            ) from exc
    else:
        raise ValueError(
            "trusted datetime must be an aware datetime or ISO-8601 datetime string"
        )

    try:
        offset = parsed.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise ValueError("trusted datetime has an invalid UTC offset") from exc
    if offset is None:
        raise ValueError("trusted datetime must include a UTC offset")
    return parsed.astimezone(UTC)


def canonical_utc_iso(value: datetime) -> str:
    """Serialize a trusted instant deterministically while preserving microseconds."""

    memo = _temporal_memo.get()
    key = (value, value.fold) if memo is not None and type(value) is datetime and value.tzinfo is UTC else None
    if key is not None:
        assert memo is not None
        known = memo.get(key)
        if known is not None:
            return known
    normalized = normalize_utc_datetime(value)
    encoded = normalized.isoformat().replace("+00:00", "Z")
    if key is not None:
        assert memo is not None
        memo[key] = encoded
    return encoded


def utc_now() -> datetime:
    """Server-owned aware UTC clock for operational timestamps."""

    return datetime.now(UTC)


UtcDateTime = Annotated[
    datetime,
    BeforeValidator(normalize_utc_datetime),
    PlainSerializer(canonical_utc_iso, return_type=str, when_used="json"),
]
