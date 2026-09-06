from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

from app.core.time import normalize_utc_datetime


class UtcTimestamp(TypeDecorator[datetime]):
    """Timezone-aware instant with explicit SQLite roundtrip handling.

    SQLite's DateTime adapter discards tzinfo on retrieval. The bind processor
    accepts only aware values and stores them in UTC, so the SQLite-only result
    branch restores that declared storage timezone. Other dialects must return
    an aware value and fail closed if they do not.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None
        return normalize_utc_datetime(value)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None
        if value.utcoffset() is None:
            if dialect.name != "sqlite":
                raise ValueError("database returned a naive trusted timestamp")
            return datetime(
                value.year,
                value.month,
                value.day,
                value.hour,
                value.minute,
                value.second,
                value.microsecond,
                tzinfo=UTC,
                fold=value.fold,
            )
        return normalize_utc_datetime(value)


class CanonicalDecimal(TypeDecorator[Decimal]):
    """Exact finite Decimal with a string-backed SQLite representation.

    PostgreSQL uses arbitrary-precision NUMERIC. SQLite's numeric affinity can
    silently round through binary float, so tests store the canonical decimal
    text and restore it exactly.
    """

    impl = Numeric
    cache_ok = True

    def __init__(self, sqlite_max_length: int = 128) -> None:
        super().__init__()
        self.sqlite_max_length = sqlite_max_length

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(self.sqlite_max_length))
        return dialect.type_descriptor(Numeric())

    def process_bind_param(self, value: Decimal | None, dialect: Dialect):
        if value is None:
            return None
        parsed = Decimal(value)
        if not parsed.is_finite():
            raise ValueError("persisted execution decimal must be finite")
        return format(parsed, "f") if dialect.name == "sqlite" else parsed

    def process_result_value(self, value: object, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))
