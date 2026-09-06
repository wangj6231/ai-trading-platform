import asyncio
import copy
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.core.errors import AppError, MarketDataUpstreamError
from app.market_data.base import ParsedProviderCandle
from app.market_data.exceptions import (
    InvalidProviderPayloadError,
    UnsupportedSymbolError,
)
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.market_data.service import MarketDataService
from app.schemas.market import MarketDataQuery
from app.schemas.types import MarketSymbol, Timeframe


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "binance_klines_1m.json"
FIXED_NOW = datetime(2025, 1, 1, 1, 0, tzinfo=UTC)


def fixture_rows() -> list[list]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def fetch_with_payload(payload: object) -> tuple[list, httpx.Request]:
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        if payload is None:
            return httpx.Response(
                200,
                content=b"null",
                headers={"content-type": "application/json"},
            )
        return httpx.Response(200, json=payload)

    async def execute() -> list:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://binance.test") as client:
            provider = BinancePublicMarketDataProvider(client=client, now=lambda: FIXED_NOW)
            return list(
                await provider.get_historical_candles(
                    MarketSymbol.BTCUSDT,
                    Timeframe.ONE_MINUTE,
                    3,
                )
            )

    candles = asyncio.run(execute())
    assert captured_request is not None
    return candles, captured_request


def fetch_validated_with_payload(payload: object, *, limit: int = 3):
    async def execute():
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://binance.test",
        ) as client:
            provider = BinancePublicMarketDataProvider(
                client=client,
                now=lambda: FIXED_NOW,
            )
            service = MarketDataService([provider], now=lambda: FIXED_NOW)
            return await service.get_historical_candles(
                MarketDataQuery(
                    symbol=MarketSymbol.BTCUSDT,
                    timeframe=Timeframe.ONE_MINUTE,
                    limit=limit,
                )
            )

    return asyncio.run(execute())


def fetch_validated_with_handler(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    limit: int = 3,
    max_attempts: int = 2,
    retry_backoff_seconds: float = 0,
    sleep: Callable[[float], Awaitable[None]] | None = None,
):
    async def execute():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://binance.test",
        ) as client:
            provider = BinancePublicMarketDataProvider(
                client=client,
                now=lambda: FIXED_NOW,
                max_attempts=max_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
                sleep=sleep,
            )
            service = MarketDataService([provider], now=lambda: FIXED_NOW)
            return await service.get_historical_candles(
                MarketDataQuery(
                    symbol=MarketSymbol.BTCUSDT,
                    timeframe=Timeframe.ONE_MINUTE,
                    limit=limit,
                )
            )

    return asyncio.run(execute())


def test_rate_limit_has_dedicated_fail_closed_error_contract() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "7"})

    with pytest.raises(AppError) as captured:
        fetch_validated_with_handler(handler)

    assert captured.value.code == "MARKET_DATA_RATE_LIMITED"
    assert captured.value.status_code == 429
    assert captured.value.details == {
        "provider": "binance_spot_public",
        "retry_after_seconds": 7,
    }
    assert attempts == 1


def test_transient_server_failure_uses_bounded_retry() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    with pytest.raises(MarketDataUpstreamError):
        fetch_validated_with_handler(handler)

    assert attempts == 2


def test_retry_backoff_is_bounded_and_deterministic() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    with pytest.raises(MarketDataUpstreamError):
        fetch_validated_with_handler(
            handler,
            max_attempts=3,
            retry_backoff_seconds=0.5,
            sleep=record_sleep,
        )

    assert attempts == 3
    assert delays == [0.5, 1.0]


def test_provider_timeout_retries_then_returns_distinct_timeout() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(AppError) as captured:
        fetch_validated_with_handler(handler)

    assert attempts == 2
    assert captured.value.status_code == 504
    assert captured.value.code == "MARKET_DATA_UPSTREAM_TIMEOUT"
    assert captured.value.details == {"provider": "binance_spot_public"}


def test_provider_connection_failure_retries_then_fails_closed() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_handler(handler)

    assert attempts == 2
    assert captured.value.details["reason"] == "ProviderRequestError"


@pytest.mark.parametrize(
    "retry_after",
    [None, "", "-1", "1.5", "86401", "tomorrow", "9" * 10_000],
)
def test_invalid_retry_after_is_not_exposed_as_trusted_delay(
    retry_after: str | None,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        headers = {} if retry_after is None else {"Retry-After": retry_after}
        return httpx.Response(429, headers=headers)

    with pytest.raises(AppError) as captured:
        fetch_validated_with_handler(handler)

    assert captured.value.code == "MARKET_DATA_RATE_LIMITED"
    assert captured.value.details == {"provider": "binance_spot_public"}


def test_malformed_json_is_not_retried_or_converted_to_empty_data() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_handler(handler)

    assert attempts == 1
    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_non_retryable_http_error_is_attempted_once() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400)

    with pytest.raises(MarketDataUpstreamError):
        fetch_validated_with_handler(handler)

    assert attempts == 1


def test_transient_failure_can_recover_without_changing_valid_payload() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=fixture_rows())

    result = fetch_validated_with_handler(handler)

    assert attempts == 2
    assert [candle.timestamp.minute for candle in result.candles] == [0, 1, 2]


def test_rate_limit_exception_does_not_include_raw_response_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="secret-upstream-body")

    with pytest.raises(AppError) as captured:
        fetch_validated_with_handler(handler)

    assert "secret-upstream-body" not in str(captured.value)


def test_out_of_order_upstream_payload_is_not_silently_sorted() -> None:
    rows = fixture_rows()
    payload = [rows[0], rows[2], rows[1]]

    decoded, _ = fetch_with_payload(payload)
    assert [candle.timestamp.minute for candle in decoded] == [0, 2, 1]

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(payload)

    assert captured.value.details["reason"] == "OutOfOrderTimestampError"


def test_unexpected_forming_row_is_not_silently_dropped() -> None:
    rows = fixture_rows()
    forming = copy.deepcopy(rows[2])
    forming[0] = int(FIXED_NOW.timestamp() * 1000)
    forming[6] = forming[0] + 60_000 - 1
    payload = [rows[0], rows[1], forming]

    decoded, _ = fetch_with_payload(payload)
    assert len(decoded) == 3
    assert decoded[-1].timestamp == FIXED_NOW

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(payload)

    assert captured.value.details["reason"] == "UnclosedCandleError"


def test_binance_fixture_is_decoded_without_changing_received_order() -> None:
    rows = fixture_rows()

    candles, request = fetch_with_payload(rows)

    assert [candle.timestamp.minute for candle in candles] == [0, 1, 2]
    assert all(isinstance(candle, ParsedProviderCandle) for candle in candles)
    assert candles[0].candle_payload() == {
        "timestamp": datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        "open": Decimal("100.00"),
        "high": Decimal("102.00"),
        "low": Decimal("99.00"),
        "close": Decimal("101.00"),
        "volume": Decimal("10.00"),
    }
    assert request.url.params["symbol"] == "BTCUSDT"
    assert request.url.params["interval"] == "1m"
    assert request.url.params["limit"] == "3"
    assert request.url.params["endTime"] == "1735693199999"


def test_binance_duplicate_timestamps_are_rejected() -> None:
    rows = fixture_rows()
    rows[1] = copy.deepcopy(rows[0])

    decoded, _ = fetch_with_payload(rows)
    assert len(decoded) == 3
    assert decoded[0].timestamp == decoded[1].timestamp

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(rows)

    assert captured.value.details["reason"] == "DuplicateTimestampError"


def test_binance_invalid_ohlc_is_rejected() -> None:
    rows = fixture_rows()
    rows[0][2] = "99.50"

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(rows)

    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_binance_missing_candle_is_rejected() -> None:
    rows = fixture_rows()
    del rows[1]

    decoded, _ = fetch_with_payload(rows)
    assert len(decoded) == 2
    assert [candle.timestamp.minute for candle in decoded] == [0, 2]

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(rows, limit=2)

    assert captured.value.details["reason"] == "MissingCandleError"


def test_binance_close_time_must_match_requested_timeframe() -> None:
    rows = fixture_rows()
    rows[0][6] += 1

    with pytest.raises(InvalidProviderPayloadError, match="close time does not match"):
        fetch_with_payload(rows)


@pytest.mark.parametrize("payload", [None, {}, "not-a-list"])
def test_binance_response_requires_list_wire_shape(payload: object) -> None:
    with pytest.raises(InvalidProviderPayloadError, match="response must be a list"):
        fetch_with_payload(payload)


@pytest.mark.parametrize("row", [None, {}, "not-a-row", 123])
def test_binance_rejects_non_list_rows(row: object) -> None:
    with pytest.raises(InvalidProviderPayloadError, match="invalid shape"):
        fetch_with_payload([row])


@pytest.mark.parametrize("row_length", [0, 6, 7, 11, 13])
def test_binance_row_requires_the_exact_wire_shape(row_length: int) -> None:
    source = fixture_rows()[0]
    row = source[:row_length] if row_length <= len(source) else [*source, "unexpected"]

    with pytest.raises(InvalidProviderPayloadError, match="invalid shape"):
        fetch_with_payload([row])


@pytest.mark.parametrize(
    ("field_index", "value"),
    [
        (0, "1735689600000"),
        (0, None),
        (0, 1735689600000.0),
        (0, True),
        (0, 10**30),
        (6, "1735689659999"),
    ],
)
def test_binance_rejects_malformed_epoch_values(
    field_index: int,
    value: object,
) -> None:
    rows = fixture_rows()
    rows[0][field_index] = value

    with pytest.raises(InvalidProviderPayloadError, match="time|timestamp"):
        fetch_with_payload(rows)


@pytest.mark.parametrize(
    "value",
    ["", None, "garbage", "NaN", "Infinity", True, 1.5, " 100"],
)
def test_binance_rejects_invalid_numeric_wire_values(value: object) -> None:
    rows = fixture_rows()
    rows[1][1] = value

    with pytest.raises(InvalidProviderPayloadError, match="open"):
        fetch_with_payload(rows)


def test_malformed_middle_row_is_not_silently_dropped() -> None:
    rows = fixture_rows()
    rows[1][4] = "not-a-price"

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(rows)

    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_off_grid_timestamp_remains_visible_to_service_validation() -> None:
    rows = fixture_rows()
    rows[0][0] += 1_000
    rows[0][6] += 1_000

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(rows)

    assert captured.value.details["reason"] == "TimeframeAlignmentError"


def test_negative_volume_is_parsed_then_rejected_by_trusted_candle_validation() -> None:
    rows = fixture_rows()
    rows[0][5] = "-1"

    decoded, _ = fetch_with_payload(rows)
    assert decoded[0].volume == Decimal("-1")

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(rows)

    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_extra_provider_record_is_not_blindly_truncated_to_limit() -> None:
    rows = fixture_rows()
    extra = copy.deepcopy(rows[-1])
    extra[0] += 60_000
    extra[6] += 60_000
    payload = [*rows, extra]

    decoded, _ = fetch_with_payload(payload)
    assert len(decoded) == 4

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch_validated_with_payload(payload, limit=3)

    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_short_contiguous_response_preserves_requested_and_received_counts() -> None:
    result = fetch_validated_with_payload(fixture_rows()[:2], limit=3)

    assert result.provenance.requested_candles == 3
    assert result.provenance.received_candles == 2
    assert len(result.candles) == 2


def test_valid_wire_payload_has_identical_trusted_ohlcv() -> None:
    result = fetch_validated_with_payload(fixture_rows())

    assert [candle.timestamp.minute for candle in result.candles] == [0, 1, 2]
    assert result.candles[0].model_dump(mode="python") == {
        "timestamp": datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        "open": Decimal("100.00"),
        "high": Decimal("102.00"),
        "low": Decimal("99.00"),
        "close": Decimal("101.00"),
        "volume": Decimal("10.00"),
    }
    assert result.provenance.validated is True
    assert result.provenance.received_candles == 3


def test_binance_provider_rejects_xauusd_without_http_request() -> None:
    async def execute() -> None:
        async with httpx.AsyncClient(base_url="https://binance.test") as client:
            provider = BinancePublicMarketDataProvider(client=client, now=lambda: FIXED_NOW)
            await provider.get_historical_candles(MarketSymbol.XAUUSD, Timeframe.ONE_MINUTE, 1)

    with pytest.raises(UnsupportedSymbolError):
        asyncio.run(execute())
