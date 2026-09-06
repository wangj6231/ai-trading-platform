import asyncio
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.strategy_config import load_strategy_config
from app.market_data.exceptions import (
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
)
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.market_data.sessions import CONTINUOUS_24_7_SCHEDULE
from app.market_data.service import MarketDataService
from app.schemas.candle import Candle
from app.schemas.types import MarketSymbol, Timeframe
from app.services.strategy_evaluation import (
    build_strategy_evaluation_service,
    get_strategy_evaluation_service,
)


START = datetime(2025, 1, 1, tzinfo=UTC)
BULLISH_PRICES = (
    (100, 110, 90, 100),
    (100, 108, 94, 105),
    (105, 109, 96, 108),
    (108, 120, 100, 118),
    (118, 125, 105, 120),
    (120, 121, 100, 110),
    (110, 114, 100, 112),
    (112, 115, 101, 113),
    (113, 114, 97, 105),
    (105, 300, 103, 120),
    (120, 126, 108, 115),
    (115, 128, 109, 120),
    (120, 124, 104, 110),
    (110, 126, 106, 120),
    (120, 122, 102, 105),
    (105, 132, 105, 131),
    (131, 172, 130, 170),
    (174, 190, 174, 188),
    (188, 190, 150, 180),
    (180, 190, 150, 180),
)


def candles_from(
    prices: Sequence[tuple[int, int, int, int]],
    *,
    start: datetime = START,
) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            timestamp=start + timedelta(minutes=index),
            open=Decimal(open_),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal("1"),
        )
        for index, (open_, high, low, close) in enumerate(prices)
    )


def binance_rows_from(candles: Sequence[Candle]) -> list[list[object]]:
    rows: list[list[object]] = []
    for candle in candles:
        open_time_ms = int(candle.timestamp.timestamp() * 1000)
        rows.append(
            [
                open_time_ms,
                str(candle.open),
                str(candle.high),
                str(candle.low),
                str(candle.close),
                str(candle.volume),
                open_time_ms + 60_000 - 1,
                "0",
                1,
                "0",
                "0",
                "0",
            ]
        )
    return rows


def mirrored_prices() -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (400 - open_, 400 - low, 400 - high, 400 - close)
        for open_, high, low, close in BULLISH_PRICES
    )


class StaticProvider:
    name = "integration_static_provider"
    supported_symbols = frozenset({MarketSymbol.BTCUSDT, MarketSymbol.ETHUSDT})
    market_schedule = CONTINUOUS_24_7_SCHEDULE

    def __init__(
        self,
        candles: Sequence[Candle],
        *,
        error: Exception | None = None,
    ) -> None:
        self.candles = tuple(candles)
        self.error = error
        self.calls: list[tuple[MarketSymbol, Timeframe, int]] = []

    async def get_historical_candles(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        limit: int,
    ) -> Sequence[Candle]:
        self.calls.append((symbol, timeframe, limit))
        if self.error is not None:
            raise self.error
        return self.candles[-limit:]


@contextmanager
def server_owned_strategy(
    client: TestClient,
    settings: Settings,
    candles: Sequence[Candle],
    *,
    retrieved_at: datetime,
    config_transform: Callable | None = None,
    provider_error: Exception | None = None,
):
    provider = StaticProvider(candles, error=provider_error)
    market_data = MarketDataService([provider], now=lambda: retrieved_at)
    if config_transform is None:
        service = build_strategy_evaluation_service(settings, market_data)
    else:
        base = load_strategy_config(settings.strategy_config_path)
        configs = {
            symbol: config_transform(config)
            for symbol, config in base.pipelines.items()
        }
        strategy_config = base.model_copy(update={"pipelines": configs})
        service = build_strategy_evaluation_service(
            settings,
            market_data,
            strategy_config,
        )
    client.app.dependency_overrides[get_strategy_evaluation_service] = lambda: service
    try:
        yield provider
    finally:
        client.app.dependency_overrides.pop(get_strategy_evaluation_service, None)


@pytest.mark.parametrize(
    ("symbol", "prices", "expected"),
    (
        (MarketSymbol.BTCUSDT, BULLISH_PRICES, "LONG"),
        (MarketSymbol.ETHUSDT, mirrored_prices(), "SHORT"),
    ),
)
def test_signal_api_uses_real_orchestrator_and_server_market_data(
    client: TestClient,
    test_settings: Settings,
    symbol: MarketSymbol,
    prices,
    expected: str,
) -> None:
    candles = candles_from(prices)
    retrieved_at = candles[-1].timestamp + timedelta(minutes=1, seconds=30)
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=retrieved_at,
    ) as provider:
        response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": symbol.value, "timeframe": "1m"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == expected
    assert payload["entry_min"] is not None
    assert payload["entry_max"] is not None
    assert payload["take_profit"] is not None
    assert payload["stop_loss"] is not None
    assert payload["risk_reward"] is not None
    assert payload["algorithm_score"] is not None
    assert payload["score_breakdown"]
    assert payload["decision_mode"] == "DETERMINISTIC_ONLY"
    assert payload["ai_validation_status"] == "NOT_REQUESTED"
    assert payload["ai_decision"] is None
    assert payload["confidence"] is None
    assert payload["symbol"] == symbol.value
    assert payload["timeframe"] == "1m"
    assert payload["source"] == "integration_static_provider"
    assert payload["provenance"]["provider"] == "integration_static_provider"
    assert payload["provenance"]["data_mode"] == "SERVER_PROVIDER"
    assert payload["provenance"]["symbol"] == symbol.value
    assert payload["provenance"]["validated"] is True
    assert payload["provenance"]["received_candles"] == len(candles)
    assert "take_profit" in payload and "stop_loss" in payload
    assert not any(key.startswith("tp") for key in payload)
    assert provider.calls == [(symbol, Timeframe.ONE_MINUTE, 1000)]


def test_valid_binance_wire_payload_preserves_strategy_decision_parity(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES)
    retrieved_at = candles[-1].timestamp + timedelta(minutes=1, seconds=30)
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=retrieved_at,
    ):
        trusted_response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=binance_rows_from(candles))

    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://binance.test",
    )
    provider = BinancePublicMarketDataProvider(
        client=upstream_client,
        now=lambda: retrieved_at,
    )
    market_data = MarketDataService([provider], now=lambda: retrieved_at)
    service = build_strategy_evaluation_service(test_settings, market_data)
    client.app.dependency_overrides[get_strategy_evaluation_service] = lambda: service
    try:
        binance_response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )
    finally:
        client.app.dependency_overrides.pop(get_strategy_evaluation_service, None)
        asyncio.run(upstream_client.aclose())

    assert trusted_response.status_code == 200
    assert binance_response.status_code == 200
    trusted_payload = trusted_response.json()
    binance_payload = binance_response.json()
    assert binance_payload["decision"] == trusted_payload["decision"] == "LONG"
    assert binance_payload["entry_min"] == trusted_payload["entry_min"]
    assert binance_payload["entry_max"] == trusted_payload["entry_max"]
    assert binance_payload["take_profit"] == trusted_payload["take_profit"]
    assert binance_payload["stop_loss"] == trusted_payload["stop_loss"]
    assert binance_payload["algorithm_score"] == trusted_payload["algorithm_score"]


def test_analysis_api_returns_detailed_deterministic_snapshot(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES)
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1, seconds=15),
    ):
        response = client.post(
            "/api/v1/analysis",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "integration_static_provider"
    assert payload["provenance"]["provider"] == "integration_static_provider"
    assert payload["provenance"]["data_mode"] == "SERVER_PROVIDER"
    assert payload["data_cutoff_at"] == payload["provenance"]["data_cutoff_at"]
    assert payload["evaluation"]["final_deterministic_decision"] == "LONG"
    assert payload["evaluation"]["indicator_snapshot"] is not None
    assert payload["evaluation"]["market_structure_snapshot"]
    assert payload["evaluation"]["smc_ict_snapshot"] is not None
    assert payload["evaluation"]["multi_timeframe_result"] is not None
    assert payload["evaluation"]["risk_result"]["decision"] == "LONG"


def test_no_trade_has_no_levels(
    client: TestClient,
    test_settings: Settings,
) -> None:
    prices = tuple((100, 101, 99, 100) for _ in range(20))
    candles = candles_from(prices)
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1),
    ):
        response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "NO_TRADE"
    assert payload["reason_codes"] == ["READY_SETUP_UNAVAILABLE"]
    for field in ("entry_min", "entry_max", "take_profit", "stop_loss", "risk_reward"):
        assert payload[field] is None


def test_incomplete_mtf_bucket_returns_no_trade(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES, start=START + timedelta(minutes=1))
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1),
    ):
        response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "NO_TRADE"
    assert response.json()["reason_codes"] == ["MULTI_TIMEFRAME_SAFETY_REJECTED"]


def test_risk_rejection_cannot_expose_trade(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES)

    def reject_rr(config):
        return config.model_copy(
            update={"risk": config.risk.model_copy(update={"min_rr": Decimal("100")})}
        )

    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1),
        config_transform=reject_rr,
    ):
        response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "NO_TRADE"
    assert payload["reason_codes"] == ["RISK_SAFETY_REJECTED"]
    assert payload["take_profit"] is None
    assert payload["stop_loss"] is None


def test_invalid_or_stale_server_data_fails_closed(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES)
    gapped = candles[:5] + candles[6:]
    with server_owned_strategy(
        client,
        test_settings,
        gapped,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1),
    ):
        invalid = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=10),
    ):
        stale = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert invalid.status_code == 502
    assert invalid.json()["error"]["code"] == "MARKET_DATA_UPSTREAM_ERROR"
    assert stale.status_code == 503
    assert stale.json()["error"]["code"] == "STRATEGY_MARKET_DATA_STALE"


def test_provider_failure_and_xau_without_provider_fail_closed(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES)
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1),
        provider_error=ProviderRequestError("offline"),
    ):
        upstream = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )
        xau = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "XAUUSD", "timeframe": "1m"},
        )

    assert upstream.status_code == 502
    assert upstream.json()["error"]["code"] == "MARKET_DATA_UPSTREAM_ERROR"
    assert xau.status_code == 503
    assert xau.json()["error"]["code"] == "MARKET_DATA_PROVIDER_NOT_CONFIGURED"


@pytest.mark.parametrize(
    ("provider_error", "status_code", "error_code", "details"),
    (
        (
            ProviderTimeoutError("provider timed out"),
            504,
            "MARKET_DATA_UPSTREAM_TIMEOUT",
            {"provider": "integration_static_provider"},
        ),
        (
            ProviderRateLimitError(7),
            429,
            "MARKET_DATA_RATE_LIMITED",
            {
                "provider": "integration_static_provider",
                "retry_after_seconds": 7,
            },
        ),
    ),
)
def test_provider_timeout_and_rate_limit_have_distinct_safe_api_contracts(
    client: TestClient,
    test_settings: Settings,
    provider_error: Exception,
    status_code: int,
    error_code: str,
    details: dict[str, object],
) -> None:
    candles = candles_from(BULLISH_PRICES)
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1),
        provider_error=provider_error,
    ):
        response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert response.status_code == status_code
    payload = response.json()
    assert payload["error"]["code"] == error_code
    assert payload["error"]["details"] == details
    assert "decision" not in payload
    assert "take_profit" not in payload
    assert "stop_loss" not in payload


def test_research_cutoff_requires_authorization_and_uses_exact_prefix(
    client: TestClient,
    test_settings: Settings,
) -> None:
    prefix = candles_from(BULLISH_PRICES)
    candles = prefix + (
        Candle(
            timestamp=START + timedelta(minutes=20),
            open=Decimal("180"),
            high=Decimal("185"),
            low=Decimal("175"),
            close=Decimal("180"),
            volume=Decimal("1"),
        ),
    )
    settings = test_settings.model_copy(
        update={
            "strategy_research_cutoff_enabled": True,
            "strategy_research_cutoff_token": SecretStr("research-secret"),
        }
    )
    cutoff = START + timedelta(minutes=20)
    with server_owned_strategy(
        client,
        settings,
        candles,
        retrieved_at=START + timedelta(minutes=21),
    ):
        forbidden = client.post(
            "/api/v1/signals/evaluate",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "cutoff": cutoff.isoformat(),
            },
        )
        allowed = client.post(
            "/api/v1/signals/evaluate",
            headers={"X-Research-Cutoff-Token": "research-secret"},
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "cutoff": cutoff.astimezone(
                    timezone(timedelta(hours=8))
                ).isoformat(),
            },
        )

    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "RESEARCH_CUTOFF_FORBIDDEN"
    assert allowed.status_code == 200
    assert allowed.json()["decision"] == "LONG"
    assert allowed.json()["data_cutoff_at"] == cutoff.isoformat().replace("+00:00", "Z")
    assert allowed.json()["provenance"]["data_mode"] == "SERVER_PROVIDER"
    assert allowed.json()["provenance"]["data_cutoff_at"] == (
        cutoff.isoformat().replace("+00:00", "Z")
    )


def test_research_cutoff_rejects_naive_api_datetime(client: TestClient) -> None:
    response = client.post(
        "/api/v1/signals/evaluate",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "cutoff": "2026-08-31T04:00:00",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"][0]["location"] == "body.cutoff"


def test_unconfigured_signal_timeframe_fails_closed(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES)
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1),
    ):
        response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "5m"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STRATEGY_PIPELINE_UNAVAILABLE"


@pytest.mark.parametrize(
    "field_name",
    ("strategy_version", "config_hash", "algorithm_build_hash"),
)
def test_analysis_client_cannot_override_server_strategy_identity(
    client: TestClient,
    field_name: str,
) -> None:
    response = client.post(
        "/api/v1/analysis",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            field_name: "0" * 64,
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("candles", [{"timestamp": "2026-01-01T00:00:00Z"}]),
        ("macd", {"histogram": 1}),
        ("smc", {"fvg": []}),
        ("ict", {"bias": "bullish"}),
        ("take_profit", 120),
        ("stop_loss", 90),
        ("algorithm_score", 99),
        ("market_bias", "bullish"),
        ("provider", "binance_spot_public"),
        ("openai_context", {"decision": "LONG"}),
        ("candles_by_timeframe", {"1m": []}),
    ),
)
def test_production_analysis_rejects_client_market_evidence(
    client: TestClient,
    field_name: str,
    value,
) -> None:
    response = client.post(
        "/api/v1/analysis",
        json={"symbol": "BTCUSDT", "timeframe": "1m", field_name: value},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("candles", [{"timestamp": "2026-01-01T00:00:00Z"}]),
        ("macd", {"histogram": 1}),
        ("smc", {"mss": []}),
        ("ict", {"setup": "READY"}),
        ("entry_min", 100),
        ("entry_max", 101),
        ("take_profit", 110),
        ("stop_loss", 95),
        ("algorithm_score", 7),
        ("market_bias", "bullish"),
        ("provider", "binance_spot_public"),
    ),
)
def test_production_signal_evaluation_rejects_client_analysis_and_levels(
    client: TestClient,
    field_name: str,
    value,
) -> None:
    response = client.post(
        "/api/v1/signals/evaluate",
        json={"symbol": "BTCUSDT", "timeframe": "1m", field_name: value},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_client_created_signal_route_is_not_exposed(client: TestClient) -> None:
    response = client.post(
        "/api/v1/signals",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "decision": "LONG",
            "take_profit": 110,
            "stop_loss": 95,
        },
    )

    assert response.status_code == 405


@pytest.mark.parametrize(
    ("field_name", "value"),
    (("symbol", "DOGEUSDT"), ("timeframe", "2m")),
)
def test_production_analysis_rejects_unsupported_identity(
    client: TestClient,
    field_name: str,
    value: str,
) -> None:
    payload = {"symbol": "BTCUSDT", "timeframe": "1m"}
    payload[field_name] = value

    response = client.post("/api/v1/analysis", json=payload)

    assert response.status_code == 422


def test_insufficient_validated_history_fails_closed(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES[:-1])
    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=candles[-1].timestamp + timedelta(minutes=1),
    ):
        response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STRATEGY_MARKET_DATA_INSUFFICIENT"
    assert response.json()["error"]["details"] == {
        "received_candles": 19,
        "required_candles": 20,
    }


@pytest.mark.parametrize(
    ("scenario", "expected_reason"),
    (
        ("duplicate", "DuplicateTimestampError"),
        ("out_of_order", "OutOfOrderTimestampError"),
        ("invalid_ohlc", "InvalidProviderPayloadError"),
        ("off_grid", "TimeframeAlignmentError"),
        ("unclosed", "UnclosedCandleError"),
    ),
)
def test_production_api_fails_closed_on_invalid_provider_candles(
    client: TestClient,
    test_settings: Settings,
    scenario: str,
    expected_reason: str,
) -> None:
    candles = list(candles_from(BULLISH_PRICES))
    retrieved_at = candles[-1].timestamp + timedelta(minutes=1)
    if scenario == "duplicate":
        candles[-1] = candles[-2]
    elif scenario == "out_of_order":
        candles[-1], candles[-2] = candles[-2], candles[-1]
    elif scenario == "invalid_ohlc":
        payload = candles[-1].model_dump(mode="python")
        payload["high"] = Decimal("1")
        candles[-1] = Candle.model_construct(**payload)
    elif scenario == "off_grid":
        candles[-1] = candles[-1].model_copy(
            update={"timestamp": candles[-1].timestamp + timedelta(seconds=30)}
        )
    else:
        retrieved_at -= timedelta(seconds=30)

    with server_owned_strategy(
        client,
        test_settings,
        candles,
        retrieved_at=retrieved_at,
    ):
        response = client.post(
            "/api/v1/signals/evaluate",
            json={"symbol": "BTCUSDT", "timeframe": "1m"},
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MARKET_DATA_UPSTREAM_ERROR"
    assert response.json()["error"]["details"]["reason"] == expected_reason


def test_no_research_ohlc_upload_route_is_exposed(client: TestClient) -> None:
    response = client.post(
        "/api/v1/research/analysis",
        json={"symbol": "BTCUSDT", "timeframe": "1m", "candles": []},
    )

    assert response.status_code == 404


def test_authorized_research_cutoff_cannot_be_in_the_future(
    client: TestClient,
    test_settings: Settings,
) -> None:
    candles = candles_from(BULLISH_PRICES)
    retrieved_at = candles[-1].timestamp + timedelta(minutes=1)
    settings = test_settings.model_copy(
        update={
            "strategy_research_cutoff_enabled": True,
            "strategy_research_cutoff_token": SecretStr("research-secret"),
        }
    )
    with server_owned_strategy(
        client,
        settings,
        candles,
        retrieved_at=retrieved_at,
    ):
        response = client.post(
            "/api/v1/analysis",
            headers={"X-Research-Cutoff-Token": "research-secret"},
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "cutoff": (retrieved_at + timedelta(minutes=1)).isoformat(),
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RESEARCH_CUTOFF_UNAVAILABLE"
