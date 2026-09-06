from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import TypeAdapter, ValidationError

from app.database.db import Base, Database
from app.database.signal_repository import SignalPersistenceError, SignalRepository
from app.database.snapshot_integrity import (
    SignalPersistenceAuthority,
    canonical_sha256,
)
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.analysis_snapshot import (
    AnalysisSnapshot,
    AnalysisSnapshotPayloadV2,
    LegacyAnalysisSnapshotV1,
    NON_DECISION_METADATA_MAX_CANONICAL_BYTES,
    NON_DECISION_METADATA_MAX_CONTAINER_ITEMS,
    NON_DECISION_METADATA_MAX_DEPTH,
    NON_DECISION_METADATA_MAX_KEY_LENGTH,
    NON_DECISION_METADATA_MAX_NODES,
    NON_DECISION_METADATA_MAX_STRING_LENGTH,
    PersistedAnalysisSnapshot,
)
from app.schemas.signal import SignalDecision
from app.schemas.signal_persistence import SignalPersistenceCreate
from app.schemas.types import MarketSymbol, Timeframe
from tests.factories import (
    TEST_STRATEGY_CONFIG,
    make_analysis_snapshot,
    make_engine_candidate,
    make_not_requested_ai_validation,
)


CUTOFF = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
FUTURE = CUTOFF + timedelta(minutes=1)


def snapshot_dict() -> dict:
    return make_engine_candidate(CUTOFF).analysis_snapshot.model_dump(mode="python")


def snapshot_with_metadata(metadata: dict) -> AnalysisSnapshot:
    raw = make_analysis_snapshot(CUTOFF).model_dump(mode="python")
    raw["payload"]["non_decision_metadata"] = metadata
    return AnalysisSnapshot.model_validate(raw)


def test_valid_fully_typed_snapshot_is_v2_and_accepted() -> None:
    snapshot = make_engine_candidate(CUTOFF).analysis_snapshot

    assert snapshot.schema_version == "2"
    assert snapshot.payload.indicators is not None
    assert snapshot.payload.smc_ict is not None
    assert snapshot.payload.multi_timeframe is not None
    assert snapshot.payload.signal_score is not None
    assert snapshot.payload.risk is not None
    assert snapshot.payload.decision.deterministic_decision is SignalDecision.LONG


def test_snapshot_cutoff_requires_timezone_and_unknown_top_level_is_rejected() -> None:
    naive = snapshot_dict()
    naive["data_cutoff_at"] = CUTOFF.replace(tzinfo=None)
    with pytest.raises(ValidationError, match="UTC offset"):
        AnalysisSnapshot.model_validate(naive)

    unknown = snapshot_dict()
    unknown["trusted_but_unknown"] = {}
    with pytest.raises(ValidationError, match="extra"):
        AnalysisSnapshot.model_validate(unknown)


def test_snapshot_hash_is_deterministic_after_utc_normalization() -> None:
    original = make_engine_candidate(CUTOFF).analysis_snapshot
    shifted = original.model_dump(mode="python")
    event = shifted["payload"]["market_structure"]["1m"]["structure_events"][0]
    instant = event["confirmed_at"]
    event["confirmed_at"] = instant.astimezone(timezone(timedelta(hours=8))).isoformat()
    normalized = AnalysisSnapshot.model_validate(shifted)

    assert normalized.payload.market_structure["1m"].structure_events[0].confirmed_at.tzinfo is UTC
    assert canonical_sha256(normalized) == canonical_sha256(original)


def test_nested_naive_timestamp_is_rejected() -> None:
    raw = snapshot_dict()
    raw["payload"]["market_structure"]["1m"]["structure_events"][0][
        "confirmed_at"
    ] = "2026-08-29T07:50:00"
    with pytest.raises((ValidationError, TypeError)):
        AnalysisSnapshot.model_validate(raw)


def test_future_structure_confirmation_is_rejected() -> None:
    raw = snapshot_dict()
    raw["payload"]["market_structure"]["1m"]["structure_events"][0][
        "confirmed_at"
    ] = FUTURE
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_liquidity_sweep_and_expanded_bounds_are_rejected() -> None:
    raw = snapshot_dict()
    pools = raw["payload"]["smc_ict"]["liquidity"]["pools"]
    pool = next(item for item in pools if item["swept_at"] is not None)
    pool["swept_at"] = FUTURE
    pool["updated_at"] = FUTURE
    pool["upper_bound"] += 1
    history = pool["history"][-1]
    history["swept_at"] = FUTURE
    history["available_at"] = FUTURE
    history["upper_bound"] = pool["upper_bound"]

    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_fvg_creation_is_rejected() -> None:
    raw = snapshot_dict()
    zone = raw["payload"]["smc_ict"]["fvg"]["zones"][0]
    zone["created_at"] = FUTURE
    zone["confirmed_at"] = FUTURE
    zone["last_updated_at"] = FUTURE
    zone["lifecycle"][0]["occurred_at"] = FUTURE
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_fvg_partial_mitigation_state_is_rejected() -> None:
    raw = snapshot_dict()
    zone = raw["payload"]["smc_ict"]["fvg"]["zones"][-1]
    zone["last_updated_at"] = FUTURE
    zone["lifecycle"][-1]["occurred_at"] = FUTURE
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_order_block_validation_is_rejected() -> None:
    raw = snapshot_dict()
    zone = raw["payload"]["smc_ict"]["order_blocks"]["order_blocks"][1]
    zone["validated_at"] = FUTURE
    validation = next(
        event for event in zone["lifecycle"] if event["type"] == "OB_VALIDATED"
    )
    validation["confirmed_at"] = FUTURE
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_order_block_invalidation_state_is_rejected() -> None:
    raw = snapshot_dict()
    zone = raw["payload"]["smc_ict"]["order_blocks"]["order_blocks"][1]
    zone["status"] = "INVALIDATED"
    zone["invalidated_at"] = FUTURE
    zone["lifecycle"] = (*zone["lifecycle"], {
            "event_id": "future-invalidation",
            "type": "OB_INVALIDATED",
            "zone_id": zone["zone_id"],
            "bar_timestamp": CUTOFF,
            "confirmed_at": FUTURE,
            "from_status": "VALIDATED",
            "to_status": "INVALIDATED",
            "mean_threshold_held": None,
        })
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_breaker_conversion_cannot_appear_early() -> None:
    raw = snapshot_dict()
    analysis = raw["payload"]["smc_ict"]["order_blocks"]
    origin = analysis["order_blocks"][1]
    breaker_id = f"BREAKER:bearish:{origin['zone_id']}"
    analysis["breaker_blocks"].append(
        {
            "zone_id": breaker_id,
            "origin_order_block_id": origin["zone_id"],
            "direction": "bearish",
            "zone_low": origin["zone_low"],
            "zone_high": origin["zone_high"],
            "mean_threshold": origin["mean_threshold"],
            "created_at": FUTURE,
            "activated_at": None,
            "invalidated_at": None,
            "status": "CANDIDATE",
            "lifecycle": [
                {
                    "event_id": "future-breaker",
                    "type": "BREAKER_CREATED",
                    "zone_id": breaker_id,
                    "bar_timestamp": CUTOFF,
                    "confirmed_at": FUTURE,
                    "from_status": None,
                    "to_status": "CANDIDATE",
                    "mean_threshold_held": None,
                }
            ],
        }
    )
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_displacement_timestamp_is_rejected() -> None:
    raw = snapshot_dict()
    leg = raw["payload"]["smc_ict"]["displacement"]["legs"][0]
    leg["end_timestamp"] = FUTURE
    leg["timestamp"] = FUTURE
    leg["confirmed_at"] = FUTURE + timedelta(minutes=1)
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_nested_mtf_close_watermark_is_rejected() -> None:
    raw = snapshot_dict()
    timeframe = raw["payload"]["multi_timeframe"]["timeframes"]["3m"]
    timeframe["source_bar_close_time"] = FUTURE
    timeframe["latest_closed_bar_at"] = FUTURE
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_indicator_cutoff_is_rejected() -> None:
    raw = snapshot_dict()
    raw["payload"]["indicators"]["data_cutoff_at"] = FUTURE
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_future_risk_and_score_evidence_are_rejected() -> None:
    risk = snapshot_dict()
    risk["payload"]["risk"]["decision_time"] = FUTURE
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(risk)

    score = snapshot_dict()
    score["payload"]["signal_score"]["evidence"]["components"]["mss"][
        "confirmed_at"
    ] = FUTURE
    with pytest.raises(ValidationError):
        AnalysisSnapshot.model_validate(score)


def test_unclosed_market_data_watermark_is_rejected() -> None:
    raw = snapshot_dict()
    series = raw["payload"]["market_data"]["series"]["1m"]
    series["last_candle_at"] = CUTOFF
    series["last_candle_close_at"] = FUTURE
    with pytest.raises(ValidationError, match="unclosed candle"):
        AnalysisSnapshot.model_validate(raw)


def test_fvg_and_order_block_status_must_match_lifecycle() -> None:
    fvg = snapshot_dict()
    fvg["payload"]["smc_ict"]["fvg"]["zones"][-1]["status"] = "OPEN"
    with pytest.raises(ValidationError, match="public status"):
        AnalysisSnapshot.model_validate(fvg)

    ob_missing_time = snapshot_dict()
    ob_missing_time["payload"]["smc_ict"]["order_blocks"]["order_blocks"][0][
        "mitigated_at"
    ] = None
    with pytest.raises(ValidationError):
        AnalysisSnapshot.model_validate(ob_missing_time)

    ob_wrong_status = snapshot_dict()
    ob_wrong_status["payload"]["smc_ict"]["order_blocks"]["order_blocks"][0][
        "status"
    ] = "VALIDATED"
    with pytest.raises(ValidationError, match="latest lifecycle"):
        AnalysisSnapshot.model_validate(ob_wrong_status)


def test_liquidity_swept_status_requires_swept_at() -> None:
    raw = snapshot_dict()
    pools = raw["payload"]["smc_ict"]["liquidity"]["pools"]
    pool = next(item for item in pools if item["state"] == "SWEPT")
    pool["swept_at"] = None
    pool["history"][-1]["swept_at"] = None
    with pytest.raises(ValidationError, match="swept"):
        AnalysisSnapshot.model_validate(raw)


def _set_swing_times(raw: dict, *, confirmed_at: datetime) -> None:
    swing = raw["payload"]["market_structure"]["1m"]["confirmed_swings"][0]
    swing["pivot_timestamp"] = CUTOFF - timedelta(minutes=10)
    swing["candidate_at"] = CUTOFF - timedelta(minutes=9)
    swing["confirmed_at"] = confirmed_at
    swing["left_evidence_timestamps"] = (CUTOFF - timedelta(minutes=11),)
    swing["right_evidence_timestamps"] = (confirmed_at - timedelta(minutes=1),)


@pytest.mark.parametrize(
    "confirmed_at",
    (CUTOFF, CUTOFF - timedelta(minutes=1)),
)
def test_pivot_before_confirmation_is_valid(confirmed_at: datetime) -> None:
    raw = snapshot_dict()
    _set_swing_times(raw, confirmed_at=confirmed_at)
    accepted = AnalysisSnapshot.model_validate(raw)
    swing = accepted.payload.market_structure["1m"].confirmed_swings[0]

    assert swing.pivot_timestamp < swing.confirmed_at <= CUTOFF


def test_pivot_before_cutoff_but_future_confirmation_is_rejected() -> None:
    raw = snapshot_dict()
    _set_swing_times(raw, confirmed_at=FUTURE)
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(raw)


def test_unknown_trusted_nested_field_is_rejected() -> None:
    raw = snapshot_dict()
    raw["payload"]["smc_ict"]["fvg"]["zones"][0]["mitigated_at"] = CUTOFF
    with pytest.raises(ValidationError, match="extra"):
        AnalysisSnapshot.model_validate(raw)


@pytest.mark.parametrize("key", ("timestamp", "confirmed_at", "availability_time"))
def test_generic_metadata_cannot_hide_temporal_fields(key: str) -> None:
    raw = make_analysis_snapshot(CUTOFF).model_dump(mode="python")
    raw["payload"]["non_decision_metadata"]["nested"] = {key: FUTURE.isoformat()}
    with pytest.raises(ValidationError, match="temporal fields"):
        AnalysisSnapshot.model_validate(raw)


@pytest.mark.parametrize(
    "key",
    (
        "time",
        "timestamp",
        "datetime",
        "date",
        "created",
        "created_at",
        "createdAt",
        "CreatedAt",
        "created-at",
        "CREATED_AT",
        "updatedAt",
        "confirmed",
        "confirmed_at",
        "validatedAt",
        "activated_at",
        "eventTime",
        "closedAt",
        "executed_at",
        "pivot_timestamp",
        "source_bar_close_time",
        "mitigation_time",
        "mitigated_at",
        "sweep_time",
        "swept_at",
        "invalidatedAt",
        "converted_at",
    ),
)
def test_generic_metadata_rejects_temporal_semantic_aliases(key: str) -> None:
    raw = make_analysis_snapshot(CUTOFF).model_dump(mode="python")
    raw["payload"]["non_decision_metadata"]["nested"] = {
        key: FUTURE.isoformat()
    }

    with pytest.raises(ValidationError, match="temporal fields"):
        AnalysisSnapshot.model_validate(raw)


def test_generic_metadata_rejects_excessively_long_string() -> None:
    raw = make_analysis_snapshot(CUTOFF).model_dump(mode="python")
    raw["payload"]["non_decision_metadata"]["note"] = "A" * 1_000_000

    with pytest.raises(ValidationError, match="string length"):
        AnalysisSnapshot.model_validate(raw)


def test_harmless_non_decision_metadata_is_accepted() -> None:
    raw = make_analysis_snapshot(CUTOFF).model_dump(mode="python")
    raw["payload"]["non_decision_metadata"]["labels"] = {
        "fixture": True,
        "source": "unit-test",
    }
    accepted = AnalysisSnapshot.model_validate(raw)

    assert accepted.payload.non_decision_metadata["labels"]["fixture"] is True


def test_empty_and_nested_safe_metadata_are_accepted_with_original_keys() -> None:
    assert snapshot_with_metadata({}).payload.non_decision_metadata == {}

    metadata = {
        "Build-Label": "research",
        "debug_category": "snapshot",
        "details": {
            "enabled": True,
            "attempts": 2,
            "ratio": 0.25,
            "optional": None,
            "tags": ["safe", False, 3],
        },
    }
    accepted = snapshot_with_metadata(metadata)

    assert accepted.payload.non_decision_metadata["Build-Label"] == "research"
    assert accepted.payload.non_decision_metadata["details"]["tags"] == [
        "safe",
        False,
        3,
    ]


@pytest.mark.parametrize(
    "key",
    (
        "take_profit",
        "takeProfit",
        "stop_loss",
        "entry_zone",
        "entryPrice",
        "BOS",
        "mss",
        "choch",
        "liquidity",
        "FVG",
        "IFVG",
        "orderBlock",
        "displacement",
        "risk_reward",
        "score",
        "direction",
        "decision",
        "signal",
    ),
)
def test_generic_metadata_rejects_typed_decision_evidence_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="decision evidence fields"):
        snapshot_with_metadata({"info": {key: "hidden"}})


def test_deep_temporal_and_decision_evidence_cannot_escape_validation() -> None:
    with pytest.raises(ValidationError, match="temporal fields"):
        snapshot_with_metadata(
            {"a": {"b": [{"source_bar_close_time": FUTURE.isoformat()}]}}
        )
    with pytest.raises(ValidationError, match="decision evidence fields"):
        snapshot_with_metadata({"analysis": {"info": {"takeProfit": 110}}})
    with pytest.raises(ValidationError, match="decision evidence fields"):
        snapshot_with_metadata({"analysis": {"bos": "bullish"}})


def test_incidental_character_sequences_do_not_trigger_reserved_tokens() -> None:
    metadata = {
        "runtime_engine": "python",
        "estimated_cost": "low",
        "updateable_label": "yes",
        "debug_category": "runtime",
        "implementation_label": "deterministic",
    }

    accepted = snapshot_with_metadata(metadata)

    assert dict(accepted.payload.non_decision_metadata) == metadata


def test_iso_looking_text_is_allowed_only_as_untrusted_text() -> None:
    note = "Observed label 2026-08-31T12:00:00Z; not evidence."

    accepted = snapshot_with_metadata({"note": note})

    assert accepted.payload.non_decision_metadata["note"] == note


@pytest.mark.parametrize("key", ("", "   "))
def test_empty_or_whitespace_metadata_key_is_rejected(key: str) -> None:
    with pytest.raises(ValidationError, match="empty or whitespace"):
        snapshot_with_metadata({key: "value"})


def test_excessively_long_and_control_character_keys_are_rejected() -> None:
    with pytest.raises(ValidationError, match="key length"):
        snapshot_with_metadata(
            {"x" * (NON_DECISION_METADATA_MAX_KEY_LENGTH + 1): "value"}
        )
    for key in ("bad\x00key", "bad\nkey", "bad\u200bkey"):
        with pytest.raises(ValidationError, match="control characters"):
            snapshot_with_metadata({key: "value"})


def test_ambiguous_normalized_keys_are_rejected_without_rewriting_keys() -> None:
    with pytest.raises(ValidationError, match="ambiguous normalized keys"):
        snapshot_with_metadata({"safe-key": 1, "safe_key": 2})


def test_dictionary_and_list_item_limits_are_enforced() -> None:
    too_many = NON_DECISION_METADATA_MAX_CONTAINER_ITEMS + 1
    with pytest.raises(ValidationError, match="maximum object size"):
        snapshot_with_metadata({f"label_{index}": index for index in range(too_many)})
    with pytest.raises(ValidationError, match="maximum list size"):
        snapshot_with_metadata({"items": list(range(too_many))})


def test_depth_and_total_node_limits_are_enforced_independently() -> None:
    nested: object = "leaf"
    for index in range(NON_DECISION_METADATA_MAX_DEPTH + 1):
        nested = {f"level_{index}": nested}
    with pytest.raises(ValidationError, match="nesting depth"):
        snapshot_with_metadata({"nested": nested})

    node_heavy = {
        f"group_{index}": list(range(NON_DECISION_METADATA_MAX_CONTAINER_ITEMS))
        for index in range(4)
    }
    assert 1 + len(node_heavy) + sum(len(items) for items in node_heavy.values()) > (
        NON_DECISION_METADATA_MAX_NODES
    )
    with pytest.raises(ValidationError, match="node count"):
        snapshot_with_metadata(node_heavy)


def test_total_canonical_size_limit_is_enforced_without_truncation() -> None:
    value = "A" * (NON_DECISION_METADATA_MAX_STRING_LENGTH - 24)
    metadata = {f"note_{index}": value for index in range(18)}
    assert all(len(item) <= NON_DECISION_METADATA_MAX_STRING_LENGTH for item in metadata.values())

    with pytest.raises(ValidationError, match="canonical size"):
        snapshot_with_metadata(metadata)

    assert NON_DECISION_METADATA_MAX_CANONICAL_BYTES == 16_384


@pytest.mark.parametrize(
    "value",
    (
        datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        date(2026, 8, 31),
        Decimal("1.25"),
        b"bytes",
    ),
)
def test_non_json_metadata_value_types_are_rejected(value: object) -> None:
    with pytest.raises(ValidationError, match="accepts only JSON"):
        snapshot_with_metadata({"note": value})


def test_custom_object_metadata_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="accepts only JSON"):
        snapshot_with_metadata({"note": object()})


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_non_finite_metadata_numbers_are_rejected(value: float) -> None:
    with pytest.raises(ValidationError, match="must be finite"):
        snapshot_with_metadata({"metric": value})


def test_metadata_number_magnitude_is_bounded() -> None:
    with pytest.raises(ValidationError, match="number exceeds"):
        snapshot_with_metadata({"metric": 10**19})
    with pytest.raises(ValidationError, match="number exceeds"):
        snapshot_with_metadata({"metric": 1e19})


def test_safe_metadata_hash_is_deterministic_and_content_sensitive() -> None:
    first = snapshot_with_metadata({"note": "safe", "labels": ["a", "b"]})
    same = snapshot_with_metadata({"labels": ["a", "b"], "note": "safe"})
    changed = snapshot_with_metadata({"note": "different", "labels": ["a", "b"]})

    assert canonical_sha256(first) == canonical_sha256(same)
    assert canonical_sha256(first) != canonical_sha256(changed)
    assert first.payload.strategy_identity == changed.payload.strategy_identity


def test_builder_metadata_passes_the_same_v2_validator() -> None:
    snapshot = make_engine_candidate(CUTOFF).analysis_snapshot

    assert snapshot.payload.non_decision_metadata == {
        "producer": "ConcreteDeterministicStrategyEngine",
        "openai_used": False,
    }


def test_constructed_unsafe_metadata_is_rejected_before_hash_or_persistence() -> None:
    valid = make_analysis_snapshot(CUTOFF)
    payload = valid.payload.model_dump(mode="python")
    payload["non_decision_metadata"] = {
        "analysis": {"eventTime": FUTURE.isoformat()}
    }
    forged_payload = AnalysisSnapshotPayloadV2.model_construct(**payload)
    forged = AnalysisSnapshot.model_construct(
        schema_version="2",
        captured_at=CUTOFF,
        data_cutoff_at=CUTOFF,
        payload=forged_payload,
    )
    create = SignalPersistenceCreate.model_construct(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        algorithm_score=0,
        algorithm_decision=SignalDecision.NO_TRADE,
        final_decision=SignalDecision.NO_TRADE,
        analysis_snapshot=forged,
    )
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    try:
        repository = SignalRepository(SignalPersistenceAuthority(TEST_STRATEGY_CONFIG))
        with patch("app.database.signal_repository.canonical_sha256") as hasher:
            with database.session_factory.begin() as session:
                with pytest.warns(UserWarning, match="serializer warnings"):
                    with pytest.raises(
                        SignalPersistenceError,
                        match="trusted V2 validation",
                    ):
                        repository.create(session, create)
            hasher.assert_not_called()
        with database.session_factory() as session:
            assert repository.list(session) == []
    finally:
        database.dispose()


def test_safe_metadata_persists_and_hashes_through_repository() -> None:
    metadata = {
        "producer": "unit-test",
        "debug_category": "persistence",
        "tags": ["safe", 2],
    }
    raw = make_engine_candidate(CUTOFF).analysis_snapshot.model_dump(mode="python")
    raw["payload"]["non_decision_metadata"] = metadata
    snapshot = AnalysisSnapshot.model_validate(raw)
    decision = snapshot.payload.decision
    assert decision.entry_zone is not None
    assert decision.take_profit is not None
    assert decision.stop_loss is not None
    assert decision.risk_reward is not None
    create = SignalPersistenceCreate(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        direction=decision.deterministic_decision.value,
        entry_min=decision.entry_zone.low,
        entry_max=decision.entry_zone.high,
        take_profit=decision.take_profit,
        stop_loss=decision.stop_loss,
        risk_reward=decision.risk_reward,
        algorithm_score=decision.score,
        algorithm_decision=decision.deterministic_decision,
        final_decision=decision.deterministic_decision,
        ai_validation=make_not_requested_ai_validation(snapshot.captured_at),
        status="WAITING",
        analysis_snapshot=snapshot,
    )
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    try:
        repository = SignalRepository(SignalPersistenceAuthority(TEST_STRATEGY_CONFIG))
        with database.session_factory.begin() as session:
            record = repository.create(session, create)
            signal_id = record.id
        with database.session_factory() as session:
            stored = repository.get(session, signal_id)
            assert stored.analysis_snapshot["payload"]["non_decision_metadata"] == metadata
            assert stored.analysis_snapshot_hash == canonical_sha256(
                stored.analysis_snapshot
            )
    finally:
        database.dispose()


def test_trusted_builder_output_is_deeply_immutable() -> None:
    snapshot = make_engine_candidate(CUTOFF).analysis_snapshot
    with pytest.raises(TypeError, match="immutable"):
        snapshot.payload.market_structure["1m"].structure_events.append(
            snapshot.payload.market_structure["1m"].structure_events[-1]
        )
    with pytest.raises(TypeError, match="immutable"):
        snapshot.payload.non_decision_metadata["producer"] = "caller"


def test_public_analysis_request_rejects_caller_snapshot_evidence() -> None:
    with pytest.raises(ValidationError, match="analysis_snapshot"):
        ProductionAnalysisRequest.model_validate(
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "analysis_snapshot": snapshot_dict(),
            }
        )


def test_repository_revalidates_constructed_snapshot_and_blocks_bypass() -> None:
    forged = AnalysisSnapshot.model_construct(
        schema_version="2",
        captured_at=CUTOFF,
        data_cutoff_at=CUTOFF,
        payload={"arbitrary": "untyped"},
    )
    create = SignalPersistenceCreate.model_construct(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        algorithm_score=0,
        algorithm_decision=SignalDecision.NO_TRADE,
        final_decision=SignalDecision.NO_TRADE,
        analysis_snapshot=forged,
    )
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    try:
        repository = SignalRepository(SignalPersistenceAuthority(TEST_STRATEGY_CONFIG))
        with database.session_factory.begin() as session:
            with pytest.warns(UserWarning, match="serializer warnings"):
                with pytest.raises(SignalPersistenceError, match="trusted V2 validation"):
                    repository.create(session, create)
    finally:
        database.dispose()


def test_raw_generic_snapshot_dict_cannot_enter_new_write_schema() -> None:
    payload = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "algorithm_score": 0,
        "algorithm_decision": "NO_TRADE",
        "final_decision": "NO_TRADE",
        "analysis_snapshot": {
            "schema_version": "2",
            "captured_at": CUTOFF,
            "data_cutoff_at": CUTOFF,
            "payload": {"arbitrary": {"timestamp": FUTURE}},
        },
    }
    with pytest.raises(ValidationError):
        SignalPersistenceCreate.model_validate(payload)


def test_legacy_v1_is_readable_but_not_accepted_for_new_writes() -> None:
    legacy_raw = {
        "schema_version": "1",
        "captured_at": CUTOFF,
        "data_cutoff_at": CUTOFF,
        "payload": {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "as_of": CUTOFF,
            "indicator": {"legacy": True},
            "market_structure": {"legacy": True},
            "smc_ict": {"legacy": True},
            "multi_timeframe": {"legacy": True},
            "score": 0,
            "score_result": {"legacy": True},
            "risk": {"legacy": True},
            "pipeline_config": {"legacy": True},
        },
    }
    parsed = TypeAdapter(PersistedAnalysisSnapshot).validate_python(legacy_raw)
    assert isinstance(parsed, LegacyAnalysisSnapshotV1)

    with pytest.raises(ValidationError):
        SignalPersistenceCreate.model_validate(
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "algorithm_score": 0,
                "algorithm_decision": "NO_TRADE",
                "final_decision": "NO_TRADE",
                "analysis_snapshot": legacy_raw,
            }
        )


def test_builder_contains_no_evidence_after_cutoff() -> None:
    snapshot = make_engine_candidate(CUTOFF).analysis_snapshot
    reparsed = AnalysisSnapshot.model_validate(
        deepcopy(snapshot.model_dump(mode="python"))
    )

    assert reparsed == snapshot
