from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.database.db import get_database


def valid_candle() -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00Z",
        "open": "100",
        "high": "105",
        "low": "99",
        "close": "103",
        "volume": "10",
    }


def test_health_and_database_readiness(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    readiness = client.get("/api/v1/health/ready")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["environment"] == "test"
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ready", "database": "connected"}


def test_xauusd_without_provider_does_not_return_fake_data(client: TestClient) -> None:
    response = client.get("/api/v1/market/candles?symbol=XAUUSD&timeframe=1m")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MARKET_DATA_PROVIDER_NOT_CONFIGURED"
    assert response.json()["error"]["details"] == {"symbol": "XAUUSD"}
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_analysis_endpoint_rejects_client_supplied_candles(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analysis/run",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "candles": [valid_candle()],
            "modules": ["MACD"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    locations = {item["location"] for item in response.json()["error"]["details"]}
    assert "body.candles" in locations
    assert "body.modules" in locations


def test_request_validation_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/market/candles?symbol=INVALID&timeframe=1m")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"][0]["location"].startswith("query")


def test_malformed_json_uses_safe_validation_error_envelope(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analysis",
        content="{not-json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["message"] == "The request failed validation."
    assert "traceback" not in response.text.lower()


def test_configured_market_limit_is_enforced(client: TestClient) -> None:
    response = client.get("/api/v1/market/candles?symbol=BTCUSDT&timeframe=1m&limit=1001")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "QUERY_LIMIT_EXCEEDED"
    assert response.json()["error"]["details"] == {"maximum": 1000}


def test_database_failure_uses_readiness_error_envelope(client: TestClient) -> None:
    class FailingDatabase:
        def ping(self) -> None:
            raise OperationalError("SELECT 1", {}, RuntimeError("database offline"))

    client.app.dependency_overrides[get_database] = lambda: FailingDatabase()
    try:
        response = client.get("/api/v1/health/ready")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_ERROR"
