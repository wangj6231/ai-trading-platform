import pytest
from datetime import UTC, datetime, timedelta
from dataclasses import asdict
from hashlib import sha256
import json
from types import SimpleNamespace

from app.market_data.rust_alignment import MarketAlignmentValidator, RustComputeError, RustComputeInputV1, evaluate_alignment, python_alignment_oracle
from app.market_data.exceptions import TimeframeAlignmentError
from app.market_data.rust_alignment import MAX_ITEMS, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, load_native
from tests.fixtures.rust_alignment_corpus import corpus
from app.schemas.types import Timeframe


def test_native_alignment_matches_existing_python_oracle() -> None:
    value = RustComputeInputV1(timeframe=Timeframe.ONE_MINUTE, timestamps_us=(0, 60_000_000))
    assert evaluate_alignment(value, implementation="shadow").first_misaligned_index is None


def test_native_error_objects_are_not_stringified() -> None:
    class Unprintable(ValueError):
        def __str__(self):
            raise AssertionError("sensitive exception must not be formatted")

    def unavailable(payload):
        raise Unprintable("private-provider-value")

    with pytest.raises(RustComputeError, match="INTERNAL_ERROR"):
        evaluate_alignment(RustComputeInputV1(Timeframe.ONE_MINUTE, (0,)), native=unavailable)


def test_existing_python_timestamp_failure_prevents_native_dispatch() -> None:
    value = RustComputeInputV1(Timeframe.ONE_MINUTE, (-62_135_596_800_000_000,))
    try:
        expected = python_alignment_oracle(value)
    except (OSError, ValueError, OverflowError) as error:
        def forbidden(payload):
            raise AssertionError("native must not repair a Python oracle failure")
        with pytest.raises(type(error)):
            evaluate_alignment(value, native=forbidden)
    else:
        # Platforms with a wider gmtime domain still use the exact same oracle.
        assert evaluate_alignment(value, implementation="python") == expected


def test_first_alignment_error_precedes_later_iterator_error() -> None:
    def rows():
        yield SimpleNamespace(timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC))
        raise RuntimeError("later input failure")
    with pytest.raises(TimeframeAlignmentError):
        MarketAlignmentValidator()(rows(), Timeframe.ONE_MINUTE)


@pytest.mark.parametrize("case", corpus(), ids=lambda row: row["label"])
def test_python_rust_corpus_exact_output_and_error_parity(case) -> None:
    value = RustComputeInputV1(Timeframe(case["input"]["timeframe"]), tuple(case["input"]["timestamps_us"]))
    assert sha256(value.encode()).hexdigest() == case["input_hash"]
    if case["expected_error"]:
        def forbidden(payload):
            raise AssertionError("cannot reinterpret oracle failure")
        expected = {"OSError": OSError, "ValueError": ValueError, "OverflowError": OverflowError}[case["expected_error"]]
        with pytest.raises(expected):
            evaluate_alignment(value, native=forbidden)
        return
    encoded = json.dumps(case["expected_output"], separators=(",", ":")).encode("ascii")
    assert sha256(encoded).hexdigest() == case["output_hash"]
    assert load_native()(value.encode()) == encoded
    assert asdict(evaluate_alignment(value)) == case["expected_output"]
    assert asdict(evaluate_alignment(value, implementation="rust")) == case["expected_output"]


@pytest.mark.parametrize("payload", [
    b"", b"null", b"[]", b"{}", b"invalid secret", b"[" * 200,
    b'{"contract_version":"2","timeframe":"1m","timestamps_us":[]}',
    b'{"contract_version":"1","timeframe":"unknown","timestamps_us":[]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":[true]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":[1.0]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":[null]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":["0"]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":[9223372036854775808]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":[253402300800000000]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":[-62135596800000001]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":[],"secret":"private"}',
    b'{"contract_version":"1","timeframe":"1m","timeframe":"3m","timestamps_us":[]}',
    b'{"contract_version":"1","timeframe":"1m","timestamps_us":[]} true',
])
def test_native_wire_rejects_malformed_input_with_only_fixed_error(payload) -> None:
    with pytest.raises(ValueError) as error:
        load_native()(payload)
    assert error.value.args == ("INVALID_INPUT",)


def test_native_item_and_byte_caps_and_maximum_valid_batch() -> None:
    accepted = RustComputeInputV1(Timeframe.ONE_MINUTE, (0,) * MAX_ITEMS)
    assert evaluate_alignment(accepted).item_count == MAX_ITEMS
    too_many = json.dumps({"contract_version": "1", "timeframe": "1m",
        "timestamps_us": [0] * (MAX_ITEMS + 1)}).encode()
    with pytest.raises(ValueError, match="^INVALID_INPUT$"):
        load_native()(too_many)
    with pytest.raises(ValueError, match="^INPUT_TOO_LARGE$"):
        load_native()(b" " * (MAX_INPUT_BYTES + 1))


@pytest.mark.parametrize("values", [(True,), (1.0,), (None,), ("0",), (-62_135_596_800_000_001,),
                                    (253_402_300_800_000_000,), (0,) * (MAX_ITEMS + 1)])
def test_python_input_is_strict_and_bounded(values) -> None:
    with pytest.raises(RustComputeError, match="INVALID_INPUT"):
        RustComputeInputV1(Timeframe.ONE_MINUTE, values)


@pytest.mark.parametrize("raw", [b"bad", b"{}", b"[]", b" " * (MAX_OUTPUT_BYTES + 1),
    b'{"contract_version":"1","first_misaligned_index":null,"item_count":true}',
    b'{"contract_version":"2","first_misaligned_index":null,"item_count":1}',
    b'{"contract_version":"1","first_misaligned_index":true,"item_count":1}',
    b'{"contract_version":"1","first_misaligned_index":1,"item_count":1}',
    b'{"contract_version":"1","first_misaligned_index":-1,"item_count":1}',
    b'{"contract_version":"1","first_misaligned_index":null,"item_count":2}',
    b'{"contract_version":"1","first_misaligned_index":null,"item_count":1,"extra":0}',
    b'{"contract_version":"1","first_misaligned_index":null,"item_count":1,"item_count":1}',
    "not bytes"])
def test_native_output_is_untrusted_until_strictly_validated(raw) -> None:
    with pytest.raises(RustComputeError, match="INVALID_OUTPUT"):
        evaluate_alignment(RustComputeInputV1(Timeframe.ONE_MINUTE, (0,)), native=lambda payload: raw)


def test_mismatch_fails_closed_with_bounded_telemetry() -> None:
    from app.core.telemetry import Telemetry
    telemetry = Telemetry(max_events=1)
    def native(payload):
        return b'{"contract_version":"1","first_misaligned_index":0,"item_count":1}'
    row = SimpleNamespace(timestamp=datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(RustComputeError, match="SEMANTIC_MISMATCH"):
        MarketAlignmentValidator(native=native, telemetry=telemetry)((row,), Timeframe.ONE_MINUTE)
    assert telemetry.snapshot()["events"] == [{"event": "error", "outcome": "error"}]


def test_panic_like_base_exception_is_redacted() -> None:
    class Panic(BaseException):
        pass
    def native(payload):
        raise Panic("private-key-backtrace")
    with pytest.raises(RustComputeError, match="^INTERNAL_ERROR$") as caught:
        evaluate_alignment(RustComputeInputV1(Timeframe.ONE_MINUTE, (0,)), native=native)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_process_control_is_not_swallowed(error) -> None:
    def native(payload):
        raise error()
    with pytest.raises(error):
        evaluate_alignment(RustComputeInputV1(Timeframe.ONE_MINUTE, (0,)), native=native)


def test_large_history_is_checked_in_bounded_batches_and_not_truncated() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = (SimpleNamespace(timestamp=start + timedelta(minutes=index)) for index in range(35_001))
    calls = []
    actual = load_native()
    def native(payload):
        calls.append(len(json.loads(payload)["timestamps_us"]))
        assert len(payload) <= MAX_INPUT_BYTES
        return actual(payload)
    MarketAlignmentValidator(native=native)(rows, Timeframe.ONE_MINUTE)
    assert calls == [4096] * 8 + [2233]


def test_offsets_microseconds_and_first_error_across_batch_boundary() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    offset = __import__("datetime").timezone(timedelta(hours=8))
    rows = [SimpleNamespace(timestamp=(start + timedelta(minutes=index)).astimezone(offset)) for index in range(MAX_ITEMS + 1)]
    rows[-1].timestamp += timedelta(microseconds=1)
    from app.market_data.normalization import validate_candle_alignment
    with pytest.raises(TimeframeAlignmentError) as oracle:
        validate_candle_alignment(rows, Timeframe.ONE_MINUTE)
    with pytest.raises(TimeframeAlignmentError) as actual:
        MarketAlignmentValidator()(rows, Timeframe.ONE_MINUTE)
    assert actual.value.args == oracle.value.args


def test_naive_timestamp_and_earlier_alignment_error_priority_preserved() -> None:
    bad = SimpleNamespace(timestamp=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC))
    naive = SimpleNamespace(timestamp=datetime(2026, 1, 1))
    with pytest.raises(TimeframeAlignmentError):
        MarketAlignmentValidator()((bad, naive), Timeframe.ONE_MINUTE)
    with pytest.raises(ValueError, match="include a UTC offset"):
        MarketAlignmentValidator()((naive,), Timeframe.ONE_MINUTE)


def test_empty_metadata_and_unknown_modes_do_not_infer_a_new_contract() -> None:
    MarketAlignmentValidator()((), Timeframe.ONE_WEEK)
    with pytest.raises(RustComputeError, match="INVALID_INPUT"):
        MarketAlignmentValidator("unknown")
    with pytest.raises(RustComputeError, match="INVALID_INPUT"):
        evaluate_alignment(RustComputeInputV1(Timeframe.ONE_MINUTE, ()), implementation="unknown")


def test_frozen_input_bypass_is_revalidated() -> None:
    value = RustComputeInputV1(Timeframe.ONE_MINUTE, (0,))
    object.__setattr__(value, "timestamps_us", (0,) * (MAX_ITEMS + 1))
    with pytest.raises(RustComputeError, match="INVALID_INPUT"):
        evaluate_alignment(value)


def test_explicit_native_selection_cannot_be_replaced_by_truthiness_fallback() -> None:
    class Native:
        def __bool__(self):
            return False
        def __call__(self, payload):
            raise ValueError("INTERNAL_ERROR")
    with pytest.raises(RustComputeError, match="INTERNAL_ERROR"):
        evaluate_alignment(RustComputeInputV1(Timeframe.ONE_MINUTE, (0,)), native=Native())
