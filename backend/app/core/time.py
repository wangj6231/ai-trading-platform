from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer


def normalize_utc_datetime(value: Any) -> datetime:
    """Return one explicit instant in UTC without inferring a local timezone."""

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

    normalized = normalize_utc_datetime(value)
    return normalized.isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    """Server-owned aware UTC clock for operational timestamps."""

    return datetime.now(UTC)


UtcDateTime = Annotated[
    datetime,
    BeforeValidator(normalize_utc_datetime),
    PlainSerializer(canonical_utc_iso, return_type=str, when_used="json"),
]

