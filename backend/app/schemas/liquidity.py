from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime, normalize_utc_datetime
from app.schemas.types import Timeframe


class LiquidityDirection(str, Enum):
    BUY_SIDE = "BUY_SIDE"
    SELL_SIDE = "SELL_SIDE"


class LiquidityFormation(str, Enum):
    SWING = "SWING"
    EQUAL = "EQUAL"
    RELATIVE_EQUAL = "RELATIVE_EQUAL"


class LiquidityEventType(str, Enum):
    BUY_SIDE_LIQUIDITY = "BUY_SIDE_LIQUIDITY"
    SELL_SIDE_LIQUIDITY = "SELL_SIDE_LIQUIDITY"
    EQUAL_HIGHS = "EQUAL_HIGHS"
    EQUAL_LOWS = "EQUAL_LOWS"


class LiquidityPoolState(str, Enum):
    ACTIVE = "ACTIVE"
    SWEPT = "SWEPT"
    TAKEN = "TAKEN"
    EXPIRED = "EXPIRED"


class LiquidityTerminationReason(str, Enum):
    CLOSE_THROUGH = "CLOSE_THROUGH"
    MAX_AGE_EXCEEDED = "MAX_AGE_EXCEEDED"


class LiquidityPoolHistoryEventType(str, Enum):
    CREATED = "CREATED"
    MEMBERS_UPDATED = "MEMBERS_UPDATED"
    TOUCHED = "TOUCHED"
    SWEPT = "SWEPT"
    TAKEN = "TAKEN"
    EXPIRED = "EXPIRED"


class LiquidityInteractionType(str, Enum):
    TOUCH = "TOUCH"
    SWEEP = "SWEEP"
    TAKEN = "TAKEN"


class LiquidityConfirmation(str, Enum):
    CONFIRMED_SWING = "CONFIRMED_SWING"
    CONFIRMED_EQUAL_CLUSTER = "CONFIRMED_EQUAL_CLUSTER"
    CONFIRMED_RELATIVE_EQUAL_CLUSTER = "CONFIRMED_RELATIVE_EQUAL_CLUSTER"
    BOUNDARY_TOUCH = "BOUNDARY_TOUCH"
    CLOSE_BACK = "CLOSE_BACK"
    CLOSE_THROUGH = "CLOSE_THROUGH"


class LiquidityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_size: Decimal = Field(gt=0, allow_inf_nan=False)
    liquidity_include_single_swing_pools: bool
    liquidity_single_pool_half_width_ticks: int = Field(ge=0)
    liquidity_equal_tolerance_ticks: Decimal = Field(ge=0, allow_inf_nan=False)
    liquidity_relative_equal_atr_ratio: Decimal = Field(ge=0, allow_inf_nan=False)
    liquidity_cluster_min_touches: int = Field(ge=2)
    liquidity_cluster_padding_ticks: int = Field(ge=0)
    liquidity_sweep_min_penetration_ticks: int = Field(ge=0)
    liquidity_taken_buffer_ticks: int = Field(ge=0)
    liquidity_pool_max_age_bars: int = Field(ge=1)
    signal_allow_dual_sweep: bool


class LiquidityInteraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    type: LiquidityInteractionType
    direction: LiquidityDirection
    level: Decimal = Field(gt=0, allow_inf_nan=False)
    created_at: UtcDateTime
    swept_at: UtcDateTime | None
    confirmation: LiquidityConfirmation
    source_structure: tuple[str, ...]
    pool_id: str
    timestamp: UtcDateTime
    confirmed_at: UtcDateTime

    @model_validator(mode="after")
    def validate_times(self) -> "LiquidityInteraction":
        if self.confirmed_at <= self.timestamp:
            raise ValueError("confirmed_at must be later than the interaction candle timestamp")
        if self.type is LiquidityInteractionType.SWEEP and self.swept_at != self.confirmed_at:
            raise ValueError("a sweep event must expose its own confirmation as swept_at")
        if self.type is not LiquidityInteractionType.SWEEP and self.swept_at is not None:
            raise ValueError("only a sweep interaction may set swept_at")
        return self


class LiquidityPoolHistoryEntry(BaseModel):
    """One immutable, fully materialized pool state available at a cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=0)
    event_type: LiquidityPoolHistoryEventType
    available_at: UtcDateTime
    type: LiquidityEventType
    formation: LiquidityFormation
    level: Decimal = Field(gt=0, allow_inf_nan=False)
    lower_bound: Decimal = Field(gt=0, allow_inf_nan=False)
    upper_bound: Decimal = Field(gt=0, allow_inf_nan=False)
    state: LiquidityPoolState
    terminal_reason: LiquidityTerminationReason | None
    confirmation: LiquidityConfirmation
    source_structure: tuple[str, ...]
    source_prices: tuple[Decimal, ...]
    source_pivot_timestamps: tuple[UtcDateTime, ...]
    members_available_at: tuple[UtcDateTime, ...]
    swept_at: UtcDateTime | None
    interaction_event_id: str | None = None

    @model_validator(mode="after")
    def validate_history_entry(self) -> "LiquidityPoolHistoryEntry":
        if self.lower_bound > self.upper_bound:
            raise ValueError("history lower_bound must not exceed upper_bound")
        member_count = len(self.source_structure)
        if member_count == 0:
            raise ValueError("history entry must contain source members")
        if not (
            member_count
            == len(self.source_prices)
            == len(self.source_pivot_timestamps)
            == len(self.members_available_at)
        ):
            raise ValueError("history member fields must have matching counts")
        if any(available_at > self.available_at for available_at in self.members_available_at):
            raise ValueError("history cannot expose a member before it was confirmed")
        return self


class LiquidityPool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pool_id: str
    type: LiquidityEventType
    direction: LiquidityDirection
    formation: LiquidityFormation
    level: Decimal = Field(gt=0, allow_inf_nan=False)
    lower_bound: Decimal = Field(gt=0, allow_inf_nan=False)
    upper_bound: Decimal = Field(gt=0, allow_inf_nan=False)
    state: LiquidityPoolState
    terminal_reason: LiquidityTerminationReason | None
    created_at: UtcDateTime
    confirmed_at: UtcDateTime
    updated_at: UtcDateTime
    swept_at: UtcDateTime | None
    confirmation: LiquidityConfirmation
    source_structure: tuple[str, ...]
    source_prices: tuple[Decimal, ...]
    source_pivot_timestamps: tuple[UtcDateTime, ...]
    members_available_at: tuple[UtcDateTime, ...]
    interactions: tuple[LiquidityInteraction, ...]
    history: tuple[LiquidityPoolHistoryEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pool(self) -> "LiquidityPool":
        if self.lower_bound > self.upper_bound:
            raise ValueError("liquidity pool lower_bound must not exceed upper_bound")
        member_count = len(self.source_structure)
        if member_count == 0:
            raise ValueError("liquidity pool must reference source structure")
        if not (
            member_count
            == len(self.source_prices)
            == len(self.source_pivot_timestamps)
            == len(self.members_available_at)
        ):
            raise ValueError("liquidity pool member fields must have matching counts")
        if self.confirmed_at != self.created_at:
            raise ValueError("pool confirmed_at must equal its creation confirmation")
        if self.state is LiquidityPoolState.SWEPT and self.swept_at is None:
            raise ValueError("a swept pool must set swept_at")
        expected_sequences = tuple(range(len(self.history)))
        if tuple(entry.sequence for entry in self.history) != expected_sequences:
            raise ValueError("liquidity history sequence must be contiguous and append-only")
        if self.history[0].event_type is not LiquidityPoolHistoryEventType.CREATED:
            raise ValueError("liquidity history must begin with CREATED")
        if self.history[0].available_at != self.created_at:
            raise ValueError("first liquidity history entry must be available at created_at")
        if any(
            current.available_at < previous.available_at
            for previous, current in zip(self.history, self.history[1:], strict=False)
        ):
            raise ValueError("liquidity history must be chronological")
        latest = self.history[-1]
        final_state = (
            latest.type,
            latest.formation,
            latest.level,
            latest.lower_bound,
            latest.upper_bound,
            latest.state,
            latest.terminal_reason,
            latest.confirmation,
            latest.source_structure,
            latest.source_prices,
            latest.source_pivot_timestamps,
            latest.members_available_at,
            latest.swept_at,
            latest.available_at,
        )
        exposed_state = (
            self.type,
            self.formation,
            self.level,
            self.lower_bound,
            self.upper_bound,
            self.state,
            self.terminal_reason,
            self.confirmation,
            self.source_structure,
            self.source_prices,
            self.source_pivot_timestamps,
            self.members_available_at,
            self.swept_at,
            self.updated_at,
        )
        if final_state != exposed_state:
            raise ValueError("top-level pool state must equal its latest history entry")
        return self

    def snapshot_at(self, cutoff: UtcDateTime) -> "LiquidityPool | None":
        """Return exactly the state that was available at ``cutoff``."""

        cutoff = normalize_utc_datetime(cutoff)
        visible_history = tuple(
            entry for entry in self.history if entry.available_at <= cutoff
        )
        if not visible_history:
            return None
        latest = visible_history[-1]
        return LiquidityPool(
            pool_id=self.pool_id,
            type=latest.type,
            direction=self.direction,
            formation=latest.formation,
            level=latest.level,
            lower_bound=latest.lower_bound,
            upper_bound=latest.upper_bound,
            state=latest.state,
            terminal_reason=latest.terminal_reason,
            created_at=self.created_at,
            confirmed_at=self.confirmed_at,
            updated_at=latest.available_at,
            swept_at=latest.swept_at,
            confirmation=latest.confirmation,
            source_structure=latest.source_structure,
            source_prices=latest.source_prices,
            source_pivot_timestamps=latest.source_pivot_timestamps,
            members_available_at=latest.members_available_at,
            interactions=tuple(
                interaction
                for interaction in self.interactions
                if interaction.confirmed_at <= cutoff
            ),
            history=visible_history,
        )


class DualSweepGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["DUAL_SWEEP"] = "DUAL_SWEEP"
    group_id: str
    timestamp: UtcDateTime
    confirmed_at: UtcDateTime
    buy_side_event_ids: tuple[str, ...]
    sell_side_event_ids: tuple[str, ...]


class LiquidityAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    config: LiquidityConfig
    candle_count: int = Field(ge=0)
    data_cutoff_at: UtcDateTime | None
    pools: list[LiquidityPool]
    interactions: list[LiquidityInteraction]
    dual_sweeps: list[DualSweepGroup]
