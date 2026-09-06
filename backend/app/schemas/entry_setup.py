from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.displacement import DisplacementLeg
from app.schemas.fvg import GapZone
from app.schemas.liquidity import LiquidityInteraction
from app.schemas.order_block import OrderBlockZone
from app.schemas.signal import EntryZone
from app.schemas.structure import StructureBreakEvent
from app.schemas.types import Timeframe


class EntrySetupStatus(str, Enum):
    FORMING = "FORMING"
    WAITING_RETRACE = "WAITING_RETRACE"
    READY = "READY"
    INVALIDATED = "INVALIDATED"


class EntrySetupDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class SetupFVGSelectionPolicy(str, Enum):
    FIRST_CONFIRMED = "FIRST_CONFIRMED"
    NEAREST_TO_MSS_CLOSE = "NEAREST_TO_MSS_CLOSE"
    NARROWEST = "NARROWEST"
    WIDEST = "WIDEST"


class SetupRetestMode(str, Enum):
    TOUCH = "TOUCH"
    CLOSE_IN_ZONE = "CLOSE_IN_ZONE"
    REJECTION_CLOSE = "REJECTION_CLOSE"


class SetupEntryZoneSource(str, Enum):
    FVG = "FVG"
    ORDER_BLOCK = "ORDER_BLOCK"
    INTERSECTION = "INTERSECTION"


class SetupInvalidationSource(str, Enum):
    LIQUIDITY_SWEEP_EXTREME = "LIQUIDITY_SWEEP_EXTREME"
    ORDER_BLOCK_EXTREME = "ORDER_BLOCK_EXTREME"
    ENTRY_ZONE_EXTREME = "ENTRY_ZONE_EXTREME"


class EntrySetupReasonCode(str, Enum):
    DUAL_SWEEP_REJECTED = "DUAL_SWEEP_REJECTED"
    LIQUIDITY_TAKEN_BEFORE_MSS = "LIQUIDITY_TAKEN_BEFORE_MSS"
    MSS_STAGE_EXPIRED = "MSS_STAGE_EXPIRED"
    DISPLACEMENT_STAGE_EXPIRED = "DISPLACEMENT_STAGE_EXPIRED"
    FVG_UNAVAILABLE = "FVG_UNAVAILABLE"
    FVG_RETEST_EXPIRED = "FVG_RETEST_EXPIRED"
    SETUP_TOTAL_EXPIRED = "SETUP_TOTAL_EXPIRED"
    OPPOSITE_MSS = "OPPOSITE_MSS"
    FVG_TERMINAL = "FVG_TERMINAL"
    ENTRY_ZONE_UNAVAILABLE = "ENTRY_ZONE_UNAVAILABLE"
    INVALIDATION_SOURCE_UNAVAILABLE = "INVALIDATION_SOURCE_UNAVAILABLE"
    ATR_UNAVAILABLE = "ATR_UNAVAILABLE"
    INVALIDATION_LEVEL_INVALID = "INVALIDATION_LEVEL_INVALID"


class EntrySetupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_size: Decimal = Field(gt=0, allow_inf_nan=False)
    signal_allow_dual_sweep: bool
    signal_max_bars_sweep_to_mss: int = Field(ge=1)
    signal_max_bars_mss_to_displacement: int = Field(ge=1)
    signal_max_bars_fvg_to_retest: int = Field(ge=1)
    signal_fvg_selection_policy: SetupFVGSelectionPolicy
    signal_retest_mode: SetupRetestMode
    signal_entry_zone_source: SetupEntryZoneSource
    signal_allow_zero_width_entry_zone: bool
    signal_setup_max_total_bars: int = Field(ge=1)
    setup_invalidation_source: SetupInvalidationSource
    setup_invalidation_buffer_ticks: int = Field(ge=0)
    setup_invalidation_buffer_atr_ratio: Decimal = Field(
        ge=0, allow_inf_nan=False
    )


class CompositeEntrySetup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    setup_id: str
    setup_status: EntrySetupStatus
    direction: EntrySetupDirection
    liquidity_event: LiquidityInteraction
    structure_event: StructureBreakEvent | None
    displacement_event: DisplacementLeg | None
    fvg: GapZone | None
    order_block: OrderBlockZone | None
    entry_zone: EntryZone | None
    invalidation_level: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    retest_timestamp: UtcDateTime | None
    confirmed_at: UtcDateTime
    reason_codes: tuple[EntrySetupReasonCode, ...]

    @model_validator(mode="after")
    def validate_setup(self) -> "CompositeEntrySetup":
        if self.setup_status is EntrySetupStatus.WAITING_RETRACE and self.fvg is None:
            raise ValueError("WAITING_RETRACE requires a selected FVG")
        if self.setup_status is EntrySetupStatus.READY:
            if any(
                item is None
                for item in (
                    self.structure_event,
                    self.displacement_event,
                    self.fvg,
                    self.entry_zone,
                    self.invalidation_level,
                    self.retest_timestamp,
                )
            ):
                raise ValueError("READY requires the complete setup sequence and levels")
            assert self.entry_zone is not None
            assert self.invalidation_level is not None
            if self.direction is EntrySetupDirection.BULLISH:
                if self.invalidation_level >= self.entry_zone.low:
                    raise ValueError("bullish invalidation must be below the entry zone")
            elif self.invalidation_level <= self.entry_zone.high:
                raise ValueError("bearish invalidation must be above the entry zone")
        elif self.entry_zone is not None or self.invalidation_level is not None:
            raise ValueError("only READY setups may expose entry and invalidation levels")
        return self


class EntrySetupAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    config: EntrySetupConfig
    candle_count: int = Field(ge=0)
    data_cutoff_at: UtcDateTime | None
    setups: list[CompositeEntrySetup]
