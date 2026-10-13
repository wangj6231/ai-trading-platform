"""Versioned bounded UTC alignment compute; never OHLC or execution authority."""
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import importlib
import json
from typing import Literal

from app.core.time import normalize_utc_datetime
from app.core.telemetry import DEFAULT_TELEMETRY, Telemetry
from app.market_data.exceptions import MarketDataError, TimeframeAlignmentError
from app.market_data.normalization import TimestampedCandle, validate_candle_alignment
from app.schemas.types import Timeframe

MAX_ITEMS = 4096
MAX_BATCH_SIZE = MAX_ITEMS
MAX_INPUT_BYTES = 131_072
MAX_OUTPUT_BYTES = 256
MIN_TIMESTAMP_US = -62_135_596_800_000_000
MAX_TIMESTAMP_US = 253_402_300_799_999_999
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
Implementation = Literal["python", "shadow", "rust"]


class RustComputeError(MarketDataError):
    def __init__(self, code: str) -> None:
        self.code = code if code in {"INVALID_INPUT", "INPUT_TOO_LARGE", "OUTPUT_TOO_LARGE",
            "INTERNAL_ERROR", "UNAVAILABLE", "SEMANTIC_MISMATCH", "INVALID_OUTPUT"} else "INTERNAL_ERROR"
        super().__init__(self.code)


@dataclass(frozen=True)
class RustComputeInputV1:
    timeframe: Timeframe
    timestamps_us: tuple[int, ...]
    contract_version: Literal["1"] = "1"

    def __post_init__(self) -> None:
        if (self.contract_version != "1" or not isinstance(self.timeframe, Timeframe)
                or type(self.timestamps_us) is not tuple or len(self.timestamps_us) > MAX_ITEMS
                or any(type(x) is not int or not MIN_TIMESTAMP_US <= x <= MAX_TIMESTAMP_US for x in self.timestamps_us)):
            raise RustComputeError("INVALID_INPUT")

    def encode(self) -> bytes:
        # Revalidate dataclass instances, including object.__setattr__ bypass attempts.
        self.__post_init__()
        result = json.dumps({"contract_version": self.contract_version, "timeframe": self.timeframe.value,
            "timestamps_us": self.timestamps_us}, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        if len(result) > MAX_INPUT_BYTES:
            raise RustComputeError("INPUT_TOO_LARGE")
        return result


@dataclass(frozen=True)
class RustComputeOutputV1:
    contract_version: Literal["1"]
    first_misaligned_index: int | None
    item_count: int


@dataclass(frozen=True)
class _Timestamp:
    timestamp: datetime


def python_alignment_oracle(value: RustComputeInputV1) -> RustComputeOutputV1:
    value.__post_init__()
    for index, timestamp in enumerate(value.timestamps_us):
        try:
            validate_candle_alignment((_Timestamp(EPOCH + timedelta(microseconds=timestamp)),), value.timeframe)
        except TimeframeAlignmentError:
            return RustComputeOutputV1("1", index, len(value.timestamps_us))
    return RustComputeOutputV1("1", None, len(value.timestamps_us))


def load_native() -> Callable[[bytes], bytes]:
    try:
        return importlib.import_module("_utc_alignment_core").align_v1
    except (ImportError, AttributeError):
        raise RustComputeError("UNAVAILABLE") from None


def evaluate_alignment(value: RustComputeInputV1, *, implementation: Implementation = "shadow",
                       native: Callable[[bytes], bytes] | None = None) -> RustComputeOutputV1:
    if implementation == "python":
        return python_alignment_oracle(value)
    if implementation not in {"shadow", "rust"}:
        raise RustComputeError("INVALID_INPUT")
    # Preserve platform-dependent legacy bucket failures, never "repair" them
    # with native integer arithmetic. Both native modes are oracle-gated in V1.
    oracle = python_alignment_oracle(value)
    payload = value.encode()
    try:
        raw = (load_native() if native is None else native)(payload)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        # PyO3 PanicException is a BaseException, not Exception. Never expose its text.
        code = "INTERNAL_ERROR"
        if isinstance(exc, ValueError) and len(exc.args) == 1:
            candidate = exc.args[0]
            if type(candidate) is str and len(candidate) <= 32:
                code = candidate
        if isinstance(exc, RustComputeError):
            code = exc.code
        raise RustComputeError(code) from None
    if type(raw) is not bytes or len(raw) > MAX_OUTPUT_BYTES:
        raise RustComputeError("INVALID_OUTPUT")
    try:
        pairs: list[tuple[str, object]] = json.loads(raw, object_pairs_hook=lambda entries: entries)
        if not isinstance(pairs, list) or len(pairs) != 3:
            raise ValueError
        document = dict(pairs)
        if len(document) != 3 or set(document) != {"contract_version", "first_misaligned_index", "item_count"}:
            raise ValueError
        version, count, index = document["contract_version"], document["item_count"], document["first_misaligned_index"]
        if (version != "1" or type(count) is not int or count != len(value.timestamps_us)
                or (index is not None and (type(index) is not int or not 0 <= index < count))):
            raise ValueError
        result = RustComputeOutputV1("1", index, count)
    except (ValueError, TypeError):
        raise RustComputeError("INVALID_OUTPUT") from None
    if result != oracle:
        raise RustComputeError("SEMANTIC_MISMATCH")
    if implementation == "shadow":
        return oracle
    return result


class MarketAlignmentValidator:
    """Only MarketDataService may opt into native compute; shared validators stay Python."""
    def __init__(self, implementation: Implementation = "shadow", *, telemetry: Telemetry | None = None,
                 native: Callable[[bytes], bytes] | None = None) -> None:
        if implementation not in {"python", "shadow", "rust"}:
            raise RustComputeError("INVALID_INPUT")
        self.implementation = implementation
        self.telemetry = telemetry or DEFAULT_TELEMETRY
        self.native = native
        if implementation != "python" and native is None:
            self.native = load_native()  # Missing wheel fails startup, not silent fallback.

    def __call__(self, candles: Iterable[TimestampedCandle], timeframe: Timeframe) -> None:
        if self.implementation == "python":
            validate_candle_alignment(candles, timeframe)
            return
        iterator = iter(candles)
        while True:
            batch = []
            pending: Exception | None = None
            for _ in range(MAX_BATCH_SIZE):
                try:
                    batch.append(next(iterator))
                except StopIteration:
                    break
                except Exception as exc:
                    pending = exc
                    break
            if not batch:
                if pending is not None:
                    raise pending
                return
            normalized: list[datetime] = []
            for candle in batch:
                try:
                    normalized.append(normalize_utc_datetime(candle.timestamp))
                except Exception as exc:
                    pending = exc
                    break
            integers = []
            for timestamp in normalized:
                delta = timestamp - EPOCH
                integers.append((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds)
            value = RustComputeInputV1(timeframe, tuple(integers))
            try:
                result = evaluate_alignment(value, implementation=self.implementation, native=self.native)
            except RustComputeError:
                self.telemetry.emit("error", outcome="error")
                raise
            if result.first_misaligned_index is not None:
                timestamp = normalized[result.first_misaligned_index]
                raise TimeframeAlignmentError(
                    f"Candle timestamp {timestamp.isoformat()} is not aligned to {timeframe.value}")
            if pending is not None:
                raise pending
