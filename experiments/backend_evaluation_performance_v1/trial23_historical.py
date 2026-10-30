from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from threading import Lock

import anyio

from app.core.time import canonical_utc_iso, normalize_utc_datetime, utc_now
from app.market_data.base import (
    HistoricalRangeMarketDataProvider,
    ParsedProviderCandle,
)
from app.market_data.exceptions import (
    HistoricalBootstrapError,
    HistoricalCacheCorruptionError,
    HistoricalOverlapConflictError,
    HistoricalPaginationError,
    HistoricalRangeUnsupportedError,
)
from app.market_data.timeframes import timeframe_bucket_start, timeframe_duration
from app.schemas.candle import Candle
from app.schemas.types import MarketSymbol, Timeframe


HISTORICAL_CACHE_SCHEMA_VERSION = 1
DEFAULT_HISTORICAL_PAGE_LIMIT = 1000
_MAX_VALIDATED_CANDLES = 100_000
_CANDLE_INPUT_FIELDS = ('timestamp', 'open', 'high', 'low', 'close', 'volume')


async def _owned_cache_work(function, *args, **kwargs):
    """Keep unchanged finite cache work off ASGI, and own its completion."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    finally:
        # Thread cancellation cannot stop a running file write or validator.
        # Finish this owned operation before propagating request cancellation.
        with anyio.CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()


@dataclass(frozen=True, slots=True)
class HistoricalBootstrapProvenance:
    provider: str
    symbol: MarketSymbol
    timeframe: Timeframe
    requested_start: datetime
    requested_end: datetime
    retrieved_at: datetime
    page_count: int
    cache_hit: bool
    rebootstrap: bool
    content_hash: str


@dataclass(frozen=True, slots=True)
class HistoricalBootstrapResult:
    candles: tuple[Candle, ...]
    provenance: HistoricalBootstrapProvenance


@dataclass(frozen=True, slots=True)
class _CachedHistory:
    provider: str
    symbol: MarketSymbol
    timeframe: Timeframe
    retrieved_at: datetime
    candles: tuple[Candle, ...]
    content_hash: str


class FileHistoricalCandleCache:
    """Atomic, server-owned cache for validated canonical candle histories."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._validated_rows: OrderedDict[tuple[Any, ...], Candle] = OrderedDict()
        self._rows_lock = Lock()

    def _validated_candle(self, row: Any, *, provider: Any,
        symbol: MarketSymbol, timeframe: Timeframe) -> Candle:
        # Only exact complete string inputs produced by the existing file
        # codec can hit this memo. Other shapes/types run the original validator.
        if (type(row) is not dict or set(row) != set(_CANDLE_INPUT_FIELDS)
            or type(provider) is not str
            or any(type(row[name]) is not str for name in _CANDLE_INPUT_FIELDS)):
            return Candle.model_validate(row)
        validator = Candle.model_validate
        key = (provider, symbol, timeframe, HISTORICAL_CACHE_SCHEMA_VERSION,
            Candle.__pydantic_validator__, getattr(validator, '__func__', validator),
            tuple(row[name] for name in _CANDLE_INPUT_FIELDS))
        with self._rows_lock:
            known = self._validated_rows.get(key)
            if known is not None:
                self._validated_rows.move_to_end(key)
        if known is None:
            known = validator(row)
            with self._rows_lock:
                self._validated_rows[key] = known
                self._validated_rows.move_to_end(key)
                while len(self._validated_rows) > _MAX_VALIDATED_CANDLES:
                    self._validated_rows.popitem(last=False)
        # The memo owns the validated original; callers receive separate model
        # dictionaries/field sets. All six normalized leaf values are immutable.
        return known.model_copy()

    def path_for(self, symbol: MarketSymbol, timeframe: Timeframe) -> Path:
        return self._root / f"{symbol.value.lower()}_{timeframe.value}.json"

    def load(self, symbol: MarketSymbol, timeframe: Timeframe) -> _CachedHistory | None:
        path = self.path_for(symbol, timeframe)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return _parse_cached_payload(payload, symbol, timeframe,
                candle_validator=lambda row: self._validated_candle(row,
                    provider=payload.get('provider'), symbol=symbol, timeframe=timeframe))
        except HistoricalCacheCorruptionError:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HistoricalCacheCorruptionError(
                f"historical cache is unreadable: {path.name}"
            ) from exc

    def save(
        self,
        *,
        provider: str,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        retrieved_at: datetime,
        candles: tuple[Candle, ...],
    ) -> str:
        if not candles:
            raise HistoricalBootstrapError("cannot cache an empty historical candle set")
        content_hash = _history_hash(provider, symbol, timeframe, candles)
        payload = {
            "schema_version": HISTORICAL_CACHE_SCHEMA_VERSION,
            "provider": provider,
            "symbol": symbol.value,
            "timeframe": timeframe.value,
            "retrieved_at": canonical_utc_iso(retrieved_at),
            "first_candle_at": canonical_utc_iso(candles[0].timestamp),
            "last_candle_at": canonical_utc_iso(candles[-1].timestamp),
            "received_candles": len(candles),
            "content_hash": content_hash,
            "candles": [_candle_payload(candle) for candle in candles],
        }
        self._root.mkdir(parents=True, exist_ok=True)
        destination = self.path_for(symbol, timeframe)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=self._root,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        return content_hash


class HistoricalBootstrapService:
    """PIT-safe pagination and cache boundary for canonical historical data."""

    def __init__(
        self,
        provider: HistoricalRangeMarketDataProvider,
        cache: FileHistoricalCandleCache,
        *,
        page_limit: int = DEFAULT_HISTORICAL_PAGE_LIMIT,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if page_limit < 1 or page_limit > DEFAULT_HISTORICAL_PAGE_LIMIT:
            raise ValueError("historical page_limit must be between 1 and 1000")
        self._provider = provider
        self._cache = cache
        self._page_limit = page_limit
        self._now = now or utc_now

    async def ensure_history(
        self,
        *,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        required_candles: int,
        end_at: datetime | None = None,
    ) -> HistoricalBootstrapResult:
        if required_candles < 1:
            raise ValueError("required_candles must be at least one")
        resolved_end = self._resolve_end(timeframe, end_at)
        duration = timeframe_duration(timeframe)
        requested_start = resolved_end - required_candles * duration
        existing: _CachedHistory | None
        rebootstrap = False
        try:
            existing = await _owned_cache_work(self._cache.load, symbol, timeframe)
        except HistoricalCacheCorruptionError:
            existing = None
            rebootstrap = True

        provider_name = getattr(self._provider, "name", "unknown")
        if existing is not None and existing.provider != provider_name:
            existing = None
            rebootstrap = True

        if existing is not None and await _owned_cache_work(_covers, existing.candles, requested_start, resolved_end, duration):
            selected = await _owned_cache_work(_slice_history, existing.candles, requested_start, resolved_end)
            selected_hash = await _owned_cache_work(_history_hash, provider_name, symbol, timeframe, selected)
            return HistoricalBootstrapResult(
                candles=selected,
                provenance=HistoricalBootstrapProvenance(
                    provider=provider_name,
                    symbol=symbol,
                    timeframe=timeframe,
                    requested_start=requested_start,
                    requested_end=resolved_end,
                    retrieved_at=existing.retrieved_at,
                    page_count=0,
                    cache_hit=True,
                    rebootstrap=False,
                    content_hash=selected_hash,
                ),
            )

        merged: dict[datetime, Candle] = {}
        if existing is not None:
            for candle in existing.candles:
                merged[candle.timestamp] = candle

        page_count = 0
        ranges: list[tuple[datetime, datetime]] = []
        if existing is None:
            ranges.append((requested_start, resolved_end))
        else:
            existing_start = existing.candles[0].timestamp
            existing_end = existing.candles[-1].timestamp + duration
            if requested_start < existing_start:
                ranges.append((requested_start, existing_start))
            if resolved_end > existing_end:
                ranges.append((existing_end, resolved_end))

        for range_start, range_end in ranges:
            fetched, pages = await self._fetch_range(
                symbol=symbol,
                timeframe=timeframe,
                start=range_start,
                end=range_end,
            )
            page_count += pages
            for candle in fetched:
                previous = merged.get(candle.timestamp)
                if previous is not None and previous != candle:
                    raise HistoricalOverlapConflictError(
                        f"conflicting candle at {candle.timestamp.isoformat()}"
                    )
                merged[candle.timestamp] = candle

        def validated_history():
            ordered = tuple(sorted(merged.values(), key=lambda candle: candle.timestamp))
            _validate_complete_range(ordered, ordered[0].timestamp,
                ordered[-1].timestamp+duration, duration)
            selected = _slice_history(ordered, requested_start, resolved_end)
            _validate_complete_range(selected, requested_start, resolved_end, duration)
            return ordered, selected
        ordered, selected = await _owned_cache_work(validated_history)
        retrieved_at = normalize_utc_datetime(self._now())
        await _owned_cache_work(self._cache.save,
            provider=provider_name,
            symbol=symbol,
            timeframe=timeframe,
            retrieved_at=retrieved_at,
            candles=ordered,
        )
        selected_hash = await _owned_cache_work(_history_hash, provider_name, symbol, timeframe, selected)
        return HistoricalBootstrapResult(
            candles=selected,
            provenance=HistoricalBootstrapProvenance(
                provider=provider_name,
                symbol=symbol,
                timeframe=timeframe,
                requested_start=requested_start,
                requested_end=resolved_end,
                retrieved_at=retrieved_at,
                page_count=page_count,
                cache_hit=False,
                rebootstrap=rebootstrap,
                content_hash=selected_hash,
            ),
        )

    def _resolve_end(self, timeframe: Timeframe, end_at: datetime | None) -> datetime:
        try:
            now = normalize_utc_datetime(self._now())
            resolved_end = (
                normalize_utc_datetime(end_at)
                if end_at is not None
                else timeframe_bucket_start(now, timeframe)
            )
        except ValueError as exc:
            raise HistoricalBootstrapError("historical cutoff must include a UTC offset") from exc
        if timeframe_bucket_start(resolved_end - timeframe_duration(timeframe), timeframe) + timeframe_duration(timeframe) != resolved_end:
            raise HistoricalBootstrapError("historical cutoff must align to a closed timeframe boundary")
        if resolved_end > timeframe_bucket_start(now, timeframe):
            raise HistoricalBootstrapError("historical cutoff cannot include a partial or future candle")
        return resolved_end

    async def _fetch_range(
        self,
        *,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[tuple[Candle, ...], int]:
        provider_method = getattr(self._provider, "get_historical_candles_between", None)
        if provider_method is None:
            raise HistoricalRangeUnsupportedError(
                "provider does not expose a bounded historical range capability"
            )
        duration = timeframe_duration(timeframe)
        cursor = start
        merged: dict[datetime, Candle] = {}
        page_count = 0
        while cursor < end:
            page_count += 1
            remaining = int((end - cursor) / duration)
            requested_limit = min(self._page_limit, max(1, remaining))
            raw_page = tuple(
                await provider_method(symbol, timeframe, cursor, end, requested_limit)
            )
            if not raw_page:
                raise HistoricalPaginationError(
                    f"provider returned an empty page before {end.isoformat()}"
                )
            if len(raw_page) > requested_limit:
                raise HistoricalPaginationError("provider returned more rows than page limit")
            page_max: datetime | None = None
            for raw in raw_page:
                candle = _trusted_provider_candle(raw, timeframe, start, end)
                page_max = candle.timestamp if page_max is None else max(page_max, candle.timestamp)
                previous = merged.get(candle.timestamp)
                if previous is not None and previous != candle:
                    raise HistoricalOverlapConflictError(
                        f"conflicting candle at {candle.timestamp.isoformat()}"
                    )
                merged[candle.timestamp] = candle
            assert page_max is not None
            next_cursor = page_max + duration
            if next_cursor <= cursor:
                raise HistoricalPaginationError("historical pagination did not advance")
            cursor = next_cursor

        ordered = tuple(sorted(merged.values(), key=lambda candle: candle.timestamp))
        _validate_complete_range(ordered, start, end, duration)
        return ordered, page_count


def _trusted_provider_candle(
    raw: object,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
) -> Candle:
    if not isinstance(raw, ParsedProviderCandle):
        raise HistoricalPaginationError("provider range returned an untrusted row type")
    try:
        candle = Candle.model_validate(raw.candle_payload())
    except (TypeError, ValueError) as exc:
        raise HistoricalPaginationError("provider range returned invalid OHLCV") from exc
    if timeframe_bucket_start(candle.timestamp, timeframe) != candle.timestamp:
        raise HistoricalPaginationError("provider range returned an unaligned candle")
    if candle.timestamp < start or candle.timestamp >= end:
        raise HistoricalPaginationError("provider range returned a candle outside its bounds")
    if candle.timestamp + timeframe_duration(timeframe) > end:
        raise HistoricalPaginationError("provider range returned a partial candle")
    return candle


def _validate_complete_range(
    candles: tuple[Candle, ...],
    start: datetime,
    end: datetime,
    duration: timedelta,
) -> None:
    if not candles:
        raise HistoricalPaginationError("historical range contains no candles")
    expected_count = int((end - start) / duration)
    if len(candles) != expected_count:
        raise HistoricalPaginationError(
            f"historical range has a gap: expected {expected_count}, received {len(candles)}"
        )
    if candles[0].timestamp != start or candles[-1].timestamp + duration != end:
        raise HistoricalPaginationError("historical range boundaries are incomplete")
    if len({c.timestamp for c in candles}) != len(candles):
        raise HistoricalPaginationError("historical range has duplicate candles")
    if tuple(sorted(candles, key=lambda candle: candle.timestamp)) != candles:
        raise HistoricalPaginationError("historical range is not ordered")
    for previous, current in zip(candles, candles[1:], strict=False):
        if current.timestamp - previous.timestamp != duration:
            raise HistoricalPaginationError(
                f"historical range has a missing interval after {previous.timestamp.isoformat()}"
            )


def _covers(
    candles: tuple[Candle, ...],
    start: datetime,
    end: datetime,
    duration: timedelta,
) -> bool:
    return bool(candles) and candles[0].timestamp <= start and candles[-1].timestamp + duration >= end


def _slice_history(
    candles: tuple[Candle, ...],
    start: datetime,
    end: datetime,
) -> tuple[Candle, ...]:
    selected = tuple(candle for candle in candles if start <= candle.timestamp < end)
    return selected


def _candle_payload(candle: Candle) -> dict[str, str]:
    return {
        "timestamp": canonical_utc_iso(candle.timestamp),
        "open": format(candle.open, "f"),
        "high": format(candle.high, "f"),
        "low": format(candle.low, "f"),
        "close": format(candle.close, "f"),
        "volume": format(candle.volume, "f"),
    }


def _history_hash(
    provider: str,
    symbol: MarketSymbol,
    timeframe: Timeframe,
    candles: tuple[Candle, ...],
) -> str:
    payload = {
        "provider": provider,
        "symbol": symbol.value,
        "timeframe": timeframe.value,
        "candles": [_candle_payload(candle) for candle in candles],
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parse_cached_payload(
    payload: Any,
    symbol: MarketSymbol,
    timeframe: Timeframe,
    *,
    candle_validator: Callable[[Any], Candle] | None = None,
) -> _CachedHistory:
    if not isinstance(payload, dict):
        raise HistoricalCacheCorruptionError("historical cache root must be an object")
    if payload.get("schema_version") != HISTORICAL_CACHE_SCHEMA_VERSION:
        raise HistoricalCacheCorruptionError("historical cache schema version is unsupported")
    if payload.get("symbol") != symbol.value or payload.get("timeframe") != timeframe.value:
        raise HistoricalCacheCorruptionError("historical cache identity does not match request")
    provider = payload.get("provider")
    stored_hash = payload.get("content_hash")
    rows = payload.get("candles")
    if not isinstance(provider, str) or not provider or not isinstance(stored_hash, str) or not isinstance(rows, list):
        raise HistoricalCacheCorruptionError("historical cache metadata is malformed")
    try:
        retrieved_at = normalize_utc_datetime(payload["retrieved_at"])
        validate_candle = Candle.model_validate if candle_validator is None else candle_validator
        candles = tuple(validate_candle(row) for row in rows)
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalCacheCorruptionError("historical cache candle payload is invalid") from exc
    if not candles:
        raise HistoricalCacheCorruptionError("historical cache contains no candles")
    duration = timeframe_duration(timeframe)
    if timeframe_bucket_start(candles[0].timestamp, timeframe) != candles[0].timestamp:
        raise HistoricalCacheCorruptionError("historical cache contains an unaligned candle")
    _validate_complete_range(candles, candles[0].timestamp, candles[-1].timestamp + duration, duration)
    if payload.get("received_candles") != len(candles):
        raise HistoricalCacheCorruptionError("historical cache count does not match payload")
    if payload.get("first_candle_at") != canonical_utc_iso(candles[0].timestamp):
        raise HistoricalCacheCorruptionError("historical cache first timestamp does not match payload")
    if payload.get("last_candle_at") != canonical_utc_iso(candles[-1].timestamp):
        raise HistoricalCacheCorruptionError("historical cache last timestamp does not match payload")
    if stored_hash != _history_hash(provider, symbol, timeframe, candles):
        raise HistoricalCacheCorruptionError("historical cache content hash does not match payload")
    return _CachedHistory(
        provider=provider,
        symbol=symbol,
        timeframe=timeframe,
        retrieved_at=retrieved_at,
        candles=candles,
        content_hash=stored_hash,
    )
