from pydantic import BaseModel, ConfigDict, Field


class StrategyIdentity(BaseModel):
    """Server-generated identity of one deterministic strategy evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_version: str = Field(min_length=1, max_length=64)
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    algorithm_build_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
