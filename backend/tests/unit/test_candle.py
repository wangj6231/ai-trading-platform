from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.candle import Candle


def candle_payload() -> dict:
    return {
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
        "open": "100.0",
        "high": "110.0",
        "low": "90.0",
        "close": "105.0",
        "volume": "12.5",
    }


def test_valid_candle_uses_decimal_and_normalizes_to_utc() -> None:
    payload = candle_payload()
    payload["timestamp"] = datetime(2026, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=8)))

    candle = Candle.model_validate(payload)

    assert candle.open == Decimal("100.0")
    assert candle.timestamp == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("high", "99.0", "high must be greater than or equal to open and close"),
        ("low", "106.0", "low must be less than or equal to open and close"),
        ("open", "0", "greater than 0"),
        ("volume", "-1", "greater than or equal to 0"),
    ],
)
def test_invalid_ohlc_is_rejected(field: str, value: str, message: str) -> None:
    payload = candle_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        Candle.model_validate(payload)


def test_naive_timestamp_is_rejected() -> None:
    payload = candle_payload()
    payload["timestamp"] = datetime(2026, 1, 1)

    with pytest.raises(ValidationError, match="must include a UTC offset"):
        Candle.model_validate(payload)
