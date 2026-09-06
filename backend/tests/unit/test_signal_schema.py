from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.signal import SignalCreate


def base_signal(decision: str) -> dict:
    return {
        "symbol": "ETHUSDT",
        "timeframe": "15m",
        "decision": decision,
        "reason_codes": ["TEST_FIXTURE_ONLY"],
        "data_cutoff_at": datetime(2026, 1, 1, tzinfo=UTC),
    }


def test_no_trade_rejects_trade_levels() -> None:
    payload = base_signal("NO_TRADE")
    payload["take_profit"] = "110"

    with pytest.raises(ValidationError, match="NO_TRADE must not include"):
        SignalCreate.model_validate(payload)


def test_long_requires_exactly_one_complete_level_set() -> None:
    payload = base_signal("LONG")

    with pytest.raises(ValidationError, match="LONG and SHORT require"):
        SignalCreate.model_validate(payload)


def test_long_level_order_is_validated() -> None:
    payload = base_signal("LONG") | {
        "entry_zone": {"low": "100", "high": "102"},
        "stop_loss": "103",
        "take_profit": "110",
        "risk_reward": "2",
    }

    with pytest.raises(ValidationError, match="LONG levels must satisfy"):
        SignalCreate.model_validate(payload)
