from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, Index, JSON, Numeric, String, event, func, inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.types import CanonicalDecimal, UtcTimestamp


JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
IMMUTABLE_DECISION_FIELDS = (
    "id",
    "symbol",
    "timeframe",
    "direction",
    "entry_min",
    "entry_max",
    "take_profit",
    "stop_loss",
    "risk_reward",
    "algorithm_score",
    "ai_confidence",
    "algorithm_decision",
    "ai_decision",
    "final_decision",
    "ai_validation_status",
    "ai_validation_evidence_schema_version",
    "ai_validation_evidence",
    "ai_validation_evidence_hash",
    "created_at",
    "execution_evidence_schema_version",
    "entry_reference",
    "planned_risk",
)
IMMUTABLE_SNAPSHOT_FIELDS = (
    "snapshot_schema_version",
    "strategy_version",
    "config_hash",
    "algorithm_build_hash",
    "analysis_snapshot",
    "analysis_snapshot_hash",
)

TERMINAL_STATUSES = frozenset({"TP_HIT", "SL_HIT", "CANCELLED", "AMBIGUOUS"})
ENTRY_EXECUTION_FIELDS = (
    "execution_policy",
    "requested_entry_price",
    "base_entry_execution_price",
    "executed_entry_price",
    "entry_executed_at",
    "entry_source_bar_timestamp",
    "entry_execution_reason",
    "entry_gap_detected",
    "entry_slippage",
    "spread_cost",
    "actual_entry_risk",
)
EXIT_EXECUTION_FIELDS = (
    "requested_exit_price",
    "base_exit_execution_price",
    "executed_exit_price",
    "exit_executed_at",
    "exit_source_bar_timestamp",
    "exit_execution_reason",
    "exit_gap_detected",
    "exit_slippage",
    "total_slippage",
    "gap_slippage",
    "commission_cost",
)
FINANCIAL_RESULT_FIELDS = (
    "gross_pnl",
    "net_pnl",
    "gross_r",
    "net_r",
    "financial_outcome",
)
LIFECYCLE_FIELDS = (
    "status",
    "activated_at",
    "closed_at",
    "result",
    "pnl_r",
    "lifecycle_events",
    *ENTRY_EXECUTION_FIELDS,
    *EXIT_EXECUTION_FIELDS,
    *FINANCIAL_RESULT_FIELDS,
)


class SignalRecord(Base):
    """Immutable signal reasoning plus mutable execution lifecycle state."""

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "entry_min IS NULL OR entry_max IS NULL OR entry_min <= entry_max",
            name="ck_signals_entry_order",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 100)",
            name="ck_signals_ai_confidence_range",
        ),
        CheckConstraint(
            "algorithm_decision != 'NO_TRADE' OR final_decision = 'NO_TRADE'",
            name="ck_signals_ai_cannot_upgrade_no_trade",
        ),
        CheckConstraint(
            "final_decision = 'NO_TRADE' OR "
            "(final_decision = algorithm_decision "
            "AND (ai_decision IS NULL OR final_decision = ai_decision))",
            name="ck_signals_trade_requires_matching_decisions",
        ),
        CheckConstraint(
            "(final_decision = 'NO_TRADE' AND direction IS NULL "
            "AND entry_min IS NULL AND entry_max IS NULL AND take_profit IS NULL "
            "AND stop_loss IS NULL AND risk_reward IS NULL AND status IS NULL) OR "
            "(final_decision IN ('LONG', 'SHORT') AND direction = final_decision "
            "AND entry_min IS NOT NULL AND entry_max IS NOT NULL "
            "AND take_profit IS NOT NULL AND stop_loss IS NOT NULL "
            "AND risk_reward IS NOT NULL AND status IS NOT NULL)",
            name="ck_signals_trade_field_presence",
        ),
        CheckConstraint(
            "direction IS NULL OR "
            "(direction = 'LONG' AND stop_loss < entry_min AND entry_min <= entry_max "
            "AND entry_max < take_profit) OR "
            "(direction = 'SHORT' AND take_profit < entry_min AND entry_min <= entry_max "
            "AND entry_max < stop_loss)",
            name="ck_signals_directional_levels",
        ),
        CheckConstraint(
            "status IS NULL OR status IN "
            "('WAITING', 'ACTIVE', 'TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS')",
            name="ck_signals_status",
        ),
        CheckConstraint(
            "symbol IN ('XAUUSD', 'BTCUSDT', 'ETHUSDT')",
            name="ck_signals_symbol_domain",
        ),
        CheckConstraint(
            "timeframe IN ('1m', '3m', '5m', '15m', '1h')",
            name="ck_signals_timeframe_domain",
        ),
        CheckConstraint(
            "(direction IS NULL OR direction IN ('LONG', 'SHORT')) AND "
            "algorithm_decision IN ('LONG', 'SHORT', 'NO_TRADE') AND "
            "(ai_decision IS NULL OR ai_decision IN ('LONG', 'SHORT', 'NO_TRADE')) AND "
            "final_decision IN ('LONG', 'SHORT', 'NO_TRADE')",
            name="ck_signals_decision_domains",
        ),
        CheckConstraint(
            "(ai_validation_evidence_schema_version IS NULL "
            "AND ai_validation_status IS NULL AND ai_validation_evidence IS NULL "
            "AND ai_validation_evidence_hash IS NULL) OR "
            "(ai_validation_evidence_schema_version = '1' "
            "AND ai_validation_status IN ('NOT_REQUESTED', "
            "'SKIPPED_ALGORITHM_NO_TRADE', 'DISABLED', 'UNAVAILABLE', "
            "'CONFIRMED', 'REJECTED', 'REDUCED_CONFIDENCE', "
            "'CONSTRAINT_REJECTED', 'TIMEOUT', 'INVALID_RESPONSE', 'API_ERROR') "
            "AND ai_validation_evidence IS NOT NULL "
            "AND length(ai_validation_evidence_hash) = 64)",
            name="ck_signals_ai_provenance_presence",
        ),
        CheckConstraint(
            "ai_validation_evidence_schema_version IS NULL OR "
            "(ai_validation_status = 'CONFIRMED' AND final_decision = algorithm_decision "
            "AND ai_decision = algorithm_decision AND ai_confidence IS NOT NULL) OR "
            "(ai_validation_status = 'NOT_REQUESTED' "
            "AND final_decision = algorithm_decision "
            "AND ai_decision IS NULL AND ai_confidence IS NULL) OR "
            "(ai_validation_status NOT IN ('CONFIRMED', 'NOT_REQUESTED') "
            "AND final_decision = 'NO_TRADE')",
            name="ck_signals_ai_provenance_decision",
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('WIN', 'LOSS', 'CANCELLED', 'AMBIGUOUS')",
            name="ck_signals_result",
        ),
        CheckConstraint(
            "(status IN ('WAITING', 'ACTIVE') AND closed_at IS NULL AND result IS NULL "
            "AND pnl_r IS NULL) OR status IS NULL OR "
            "(status IN ('TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS') "
            "AND closed_at IS NOT NULL AND result IS NOT NULL)",
            name="ck_signals_terminal_fields",
        ),
        CheckConstraint(
            "(activated_at IS NULL OR created_at <= activated_at) AND "
            "(closed_at IS NULL OR created_at <= closed_at) AND "
            "(activated_at IS NULL OR closed_at IS NULL OR activated_at <= closed_at)",
            name="ck_signals_lifecycle_time_order",
        ),
        CheckConstraint(
            "(status IS NULL AND activated_at IS NULL AND closed_at IS NULL "
            "AND result IS NULL AND pnl_r IS NULL) OR "
            "(status = 'WAITING' AND activated_at IS NULL AND closed_at IS NULL "
            "AND result IS NULL AND pnl_r IS NULL) OR "
            "(status = 'ACTIVE' AND activated_at IS NOT NULL AND closed_at IS NULL "
            "AND result IS NULL AND pnl_r IS NULL) OR "
            "(status = 'TP_HIT' AND activated_at IS NOT NULL AND closed_at IS NOT NULL "
            "AND result = 'WIN' AND abs(pnl_r - risk_reward) < 0.00000001) OR "
            "(status = 'SL_HIT' AND activated_at IS NOT NULL AND closed_at IS NOT NULL "
            "AND result = 'LOSS' AND pnl_r = -1) OR "
            "(status = 'CANCELLED' AND activated_at IS NULL AND closed_at IS NOT NULL "
            "AND result = 'CANCELLED' AND pnl_r = 0) OR "
            "(status = 'AMBIGUOUS' AND closed_at IS NOT NULL "
            "AND result = 'AMBIGUOUS' AND pnl_r IS NULL)",
            name="ck_signals_lifecycle_state_fields",
        ),
        CheckConstraint(
            "(entry_min IS NULL OR entry_min > 0) AND "
            "(entry_max IS NULL OR entry_max > 0) AND "
            "(take_profit IS NULL OR take_profit > 0) AND "
            "(stop_loss IS NULL OR stop_loss > 0) AND "
            "(risk_reward IS NULL OR risk_reward > 0) AND "
            "(entry_reference IS NULL OR entry_reference > 0) AND "
            "(planned_risk IS NULL OR planned_risk > 0) AND "
            "(requested_entry_price IS NULL OR requested_entry_price > 0) AND "
            "(base_entry_execution_price IS NULL OR base_entry_execution_price > 0) AND "
            "(executed_entry_price IS NULL OR executed_entry_price > 0) AND "
            "(actual_entry_risk IS NULL OR actual_entry_risk > 0) AND "
            "(requested_exit_price IS NULL OR requested_exit_price > 0) AND "
            "(base_exit_execution_price IS NULL OR base_exit_execution_price > 0) AND "
            "(executed_exit_price IS NULL OR executed_exit_price > 0)",
            name="ck_signals_positive_planned_values",
        ),
        CheckConstraint(
            "length(config_hash) = 64 AND length(algorithm_build_hash) = 64 "
            "AND length(analysis_snapshot_hash) = 64",
            name="ck_signals_hash_lengths",
        ),
        CheckConstraint(
            "execution_evidence_schema_version IS NULL "
            "OR execution_evidence_schema_version = '1'",
            name="ck_signals_execution_evidence_version",
        ),
        CheckConstraint(
            "(execution_policy IS NULL OR execution_policy = 'CONSERVATIVE_MARKET_FILL') AND "
            "(entry_execution_reason IS NULL OR entry_execution_reason IN "
            "('OPEN_INSIDE_ZONE', 'BOUNDARY_TOUCH_FROM_BELOW', "
            "'BOUNDARY_TOUCH_FROM_ABOVE')) AND "
            "(exit_execution_reason IS NULL OR exit_execution_reason IN "
            "('TAKE_PROFIT', 'STOP_LOSS')) AND "
            "(financial_outcome IS NULL OR financial_outcome IN "
            "('PROFIT', 'LOSS', 'FLAT'))",
            name="ck_signals_execution_domains",
        ),
        CheckConstraint(
            "(execution_evidence_schema_version IS NULL "
            "AND entry_reference IS NULL AND planned_risk IS NULL) OR "
            "(execution_evidence_schema_version = '1' "
            "AND direction IN ('LONG', 'SHORT') AND status IS NOT NULL "
            "AND entry_reference IS NOT NULL AND planned_risk IS NOT NULL "
            "AND planned_risk > 0 "
            "AND planned_risk = abs(entry_reference - stop_loss))",
            name="ck_signals_execution_v1_plan",
        ),
        CheckConstraint(
            "(entry_slippage IS NULL OR entry_slippage >= 0) AND "
            "(spread_cost IS NULL OR spread_cost >= 0) AND "
            "(exit_slippage IS NULL OR exit_slippage >= 0) AND "
            "(total_slippage IS NULL OR total_slippage >= 0) AND "
            "(gap_slippage IS NULL OR gap_slippage >= 0) AND "
            "(commission_cost IS NULL OR commission_cost >= 0)",
            name="ck_signals_execution_costs_nonnegative",
        ),
        Index("ix_signals_symbol_timeframe_created", "symbol", "timeframe", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)

    entry_min: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    entry_max: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(28, 10), nullable=True)

    risk_reward: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    algorithm_score: Mapped[int] = mapped_column(nullable=False)
    ai_confidence: Mapped[int | None] = mapped_column(nullable=True)

    algorithm_decision: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ai_decision: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    final_decision: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ai_validation_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ai_validation_evidence_schema_version: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    ai_validation_evidence: Mapped[dict | None] = mapped_column(
        JSON_DOCUMENT, nullable=True
    )
    ai_validation_evidence_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    status: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcTimestamp(), nullable=False, server_default=func.now(), index=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        UtcTimestamp(), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        UtcTimestamp(), nullable=True
    )

    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pnl_r: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    execution_evidence_schema_version: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    entry_reference: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    planned_risk: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    execution_policy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_entry_price: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    base_entry_execution_price: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    executed_entry_price: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    entry_executed_at: Mapped[datetime | None] = mapped_column(
        UtcTimestamp(), nullable=True
    )
    entry_source_bar_timestamp: Mapped[datetime | None] = mapped_column(
        UtcTimestamp(), nullable=True
    )
    entry_execution_reason: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    entry_gap_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    entry_slippage: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    spread_cost: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    actual_entry_risk: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )

    requested_exit_price: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    base_exit_execution_price: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    executed_exit_price: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    exit_executed_at: Mapped[datetime | None] = mapped_column(
        UtcTimestamp(), nullable=True
    )
    exit_source_bar_timestamp: Mapped[datetime | None] = mapped_column(
        UtcTimestamp(), nullable=True
    )
    exit_execution_reason: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    exit_gap_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exit_slippage: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    total_slippage: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    gap_slippage: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    commission_cost: Mapped[Decimal | None] = mapped_column(
        CanonicalDecimal(), nullable=True
    )
    gross_pnl: Mapped[Decimal | None] = mapped_column(CanonicalDecimal(), nullable=True)
    net_pnl: Mapped[Decimal | None] = mapped_column(CanonicalDecimal(), nullable=True)
    gross_r: Mapped[Decimal | None] = mapped_column(CanonicalDecimal(), nullable=True)
    net_r: Mapped[Decimal | None] = mapped_column(CanonicalDecimal(), nullable=True)
    financial_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)

    analysis_snapshot: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    snapshot_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    lifecycle_events: Mapped[list[dict]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_build_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)


@event.listens_for(SignalRecord, "before_update")
def prevent_orm_history_mutation(
    _mapper: object,
    _connection: object,
    target: SignalRecord,
) -> None:
    """Application guard; PostgreSQL triggers remain the final boundary."""

    state = inspect(target)
    changed_snapshot = [
        field_name
        for field_name in IMMUTABLE_SNAPSHOT_FIELDS
        if state.attrs[field_name].history.has_changes()
    ]
    if changed_snapshot:
        raise ValueError(
            "historical signal snapshot is immutable: "
            + ", ".join(changed_snapshot)
        )
    changed_decision = [
        field_name
        for field_name in IMMUTABLE_DECISION_FIELDS
        if state.attrs[field_name].history.has_changes()
    ]
    if changed_decision:
        raise ValueError(
            "historical signal decision and evidence are immutable: "
            + ", ".join(changed_decision)
        )

    status_history = state.attrs.status.history
    previous_status = (
        status_history.deleted[0]
        if status_history.deleted
        else target.status
    )
    if previous_status in TERMINAL_STATUSES:
        changed_lifecycle = [
            field_name
            for field_name in LIFECYCLE_FIELDS
            if state.attrs[field_name].history.has_changes()
        ]
        if changed_lifecycle:
            raise ValueError(
                "terminal signal lifecycle is immutable: "
                + ", ".join(changed_lifecycle)
            )

    activated_history = state.attrs.activated_at.history
    if activated_history.deleted and activated_history.deleted[0] is not None:
        raise ValueError("activated_at is immutable after activation")
    if previous_status in {"ACTIVE", *TERMINAL_STATUSES}:
        changed_entry = [
            field_name
            for field_name in ENTRY_EXECUTION_FIELDS
            if state.attrs[field_name].history.has_changes()
        ]
        if changed_entry:
            raise ValueError(
                "entry execution evidence is immutable after activation: "
                + ", ".join(changed_entry)
            )
    closed_history = state.attrs.closed_at.history
    if closed_history.deleted and closed_history.deleted[0] is not None:
        raise ValueError("closed_at is immutable after terminal transition")
