from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.time import canonical_utc_iso, normalize_utc_datetime
from app.market_data.exceptions import SessionCalendarCoverageError
from app.market_data.timeframes import timeframe_duration
from app.schemas.market_schedule import MarketScheduleMode
from app.schemas.types import Timeframe


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_MAX_EXPECTED_CANDLES = 1_000_000


class SessionCalendarDefinitionError(ValueError):
    """A server-owned calendar definition is invalid and cannot be trusted."""


@dataclass(frozen=True, slots=True)
class MarketSession:
    """One explicit venue session, normalized to UTC instants.

    Callers may construct boundaries with an IANA ``ZoneInfo`` timezone. Their
    offsets, including DST, are resolved before the session is stored.
    """

    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        try:
            opens_at = normalize_utc_datetime(self.opens_at)
            closes_at = normalize_utc_datetime(self.closes_at)
        except ValueError as exc:
            raise SessionCalendarDefinitionError(
                "session boundaries must be timezone-aware instants"
            ) from exc
        if closes_at <= opens_at:
            raise SessionCalendarDefinitionError(
                "session close must be after session open"
            )
        object.__setattr__(self, "opens_at", opens_at)
        object.__setattr__(self, "closes_at", closes_at)


@dataclass(frozen=True, slots=True)
class VersionedMarketSessionCalendar:
    """Finite, immutable schedule supplied by a configured market-data source.

    The schedule contains explicit UTC-resolved sessions. Missing dates are
    closures, not inferred gaps. A real provider must source these intervals
    from its venue/vendor contract and change ``version`` when they change.
    """

    calendar_id: str
    version: str
    timezone_name: str
    coverage_start: datetime
    coverage_end: datetime
    sessions: tuple[MarketSession, ...]
    calendar_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not _IDENTIFIER_PATTERN.fullmatch(self.calendar_id):
            raise SessionCalendarDefinitionError("calendar_id is invalid")
        if not _IDENTIFIER_PATTERN.fullmatch(self.version):
            raise SessionCalendarDefinitionError("calendar version is invalid")
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise SessionCalendarDefinitionError(
                "calendar timezone_name must be a valid IANA timezone"
            ) from exc
        try:
            coverage_start = normalize_utc_datetime(self.coverage_start)
            coverage_end = normalize_utc_datetime(self.coverage_end)
        except ValueError as exc:
            raise SessionCalendarDefinitionError(
                "calendar coverage must use timezone-aware instants"
            ) from exc
        if coverage_end <= coverage_start:
            raise SessionCalendarDefinitionError(
                "calendar coverage_end must be after coverage_start"
            )

        sessions = tuple(self.sessions)
        if any(not isinstance(item, MarketSession) for item in sessions):
            raise SessionCalendarDefinitionError(
                "calendar sessions must be MarketSession values"
            )
        if tuple(sorted(sessions, key=lambda item: item.opens_at)) != sessions:
            raise SessionCalendarDefinitionError(
                "calendar sessions must be in ascending order"
            )
        for previous, current in zip(sessions, sessions[1:], strict=False):
            if current.opens_at < previous.closes_at:
                raise SessionCalendarDefinitionError(
                    "calendar sessions must not overlap"
                )
        if any(
            item.opens_at < coverage_start or item.closes_at > coverage_end
            for item in sessions
        ):
            raise SessionCalendarDefinitionError(
                "calendar session falls outside declared coverage"
            )

        object.__setattr__(self, "coverage_start", coverage_start)
        object.__setattr__(self, "coverage_end", coverage_end)
        object.__setattr__(self, "sessions", sessions)
        object.__setattr__(self, "calendar_hash", self._content_hash())

    @property
    def identity(self) -> str:
        return f"{self.calendar_id}@{self.version}"

    def expected_candle_opens(
        self,
        start: datetime,
        end: datetime,
        timeframe: Timeframe,
    ) -> tuple[datetime, ...]:
        resolved_start, resolved_end = self._validated_range(start, end)
        duration = timeframe_duration(timeframe)
        expected: list[datetime] = []
        for item in self.sessions:
            if item.closes_at <= resolved_start or item.opens_at >= resolved_end:
                continue
            current = item.opens_at
            while current + duration <= item.closes_at:
                if resolved_start <= current < resolved_end:
                    expected.append(current)
                    if len(expected) > _MAX_EXPECTED_CANDLES:
                        raise SessionCalendarDefinitionError(
                            "calendar query exceeds the deterministic candle bound"
                        )
                current += duration
        return tuple(expected)

    def latest_closed_candle_cutoff(
        self,
        at: datetime,
        timeframe: Timeframe,
    ) -> datetime:
        resolved_at = normalize_utc_datetime(at)
        if not self.coverage_start < resolved_at <= self.coverage_end:
            raise SessionCalendarCoverageError(
                "retrieval time is outside session-calendar coverage"
            )
        duration = timeframe_duration(timeframe)
        latest: datetime | None = None
        for item in self.sessions:
            if item.opens_at >= resolved_at:
                break
            current = item.opens_at
            while current + duration <= item.closes_at:
                close = current + duration
                if close > resolved_at:
                    break
                latest = close
                current += duration
        if latest is None:
            raise SessionCalendarCoverageError(
                "calendar coverage has no closed candle at retrieval time"
            )
        return latest

    def _validated_range(
        self,
        start: datetime,
        end: datetime,
    ) -> tuple[datetime, datetime]:
        resolved_start = normalize_utc_datetime(start)
        resolved_end = normalize_utc_datetime(end)
        if resolved_end < resolved_start:
            raise SessionCalendarCoverageError("calendar query range is reversed")
        if (
            resolved_start < self.coverage_start
            or resolved_end > self.coverage_end
        ):
            raise SessionCalendarCoverageError(
                "calendar query is outside declared coverage"
            )
        return resolved_start, resolved_end

    def _content_hash(self) -> str:
        payload = {
            "calendar_id": self.calendar_id,
            "version": self.version,
            "timezone_name": self.timezone_name,
            "coverage_start": canonical_utc_iso(self.coverage_start),
            "coverage_end": canonical_utc_iso(self.coverage_end),
            "sessions": [
                {
                    "opens_at": canonical_utc_iso(item.opens_at),
                    "closes_at": canonical_utc_iso(item.closes_at),
                }
                for item in self.sessions
            ],
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderMarketSchedule:
    mode: MarketScheduleMode
    calendar: VersionedMarketSessionCalendar | None = None

    def __post_init__(self) -> None:
        if self.mode is MarketScheduleMode.CONTINUOUS_24_7:
            if self.calendar is not None:
                raise SessionCalendarDefinitionError(
                    "continuous schedule cannot contain a session calendar"
                )
        elif self.calendar is None:
            raise SessionCalendarDefinitionError(
                "session-calendar schedule requires a calendar"
            )

    @classmethod
    def session_calendar(
        cls,
        calendar: VersionedMarketSessionCalendar,
    ) -> ProviderMarketSchedule:
        return cls(mode=MarketScheduleMode.SESSION_CALENDAR, calendar=calendar)


CONTINUOUS_24_7_SCHEDULE = ProviderMarketSchedule(
    mode=MarketScheduleMode.CONTINUOUS_24_7
)
