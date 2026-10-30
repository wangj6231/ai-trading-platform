import asyncio
import sys
from datetime import timedelta
import pytest

from app.core.config import Settings
from app.market_data.rust_alignment import MarketAlignmentValidator, RustComputeError
from app.market_data.service import MarketDataService
from app.schemas.market import MarketDataQuery
from app.schemas.types import MarketSymbol, Timeframe
from tests.unit.test_market_data_trust_boundary import START, RawProvider, candle
from app.services.market_data import build_market_data_service
from app.core.errors import MarketDataUpstreamError
from pydantic import ValidationError
from app.market_data.base import ParsedProviderCandle


def test_service_accepts_explicit_alignment_implementation_without_changing_market_output() -> None:
    service = MarketDataService([RawProvider((candle(0), candle(1)))],
        now=lambda: START + timedelta(minutes=2), alignment_validator=MarketAlignmentValidator("python"))
    value = asyncio.run(service.get_historical_candles(MarketDataQuery(
        symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.ONE_MINUTE, limit=2)))
    assert [row.timestamp for row in value.candles] == [START, START + timedelta(minutes=1)]


def test_production_factory_fails_closed_when_shadow_wheel_is_missing(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "_utc_alignment_core", None)
    with pytest.raises(RustComputeError, match="UNAVAILABLE"):
        build_market_data_service(Settings(_env_file=None, app_env="test"))


def test_shadow_service_returns_exact_canonical_market_provenance() -> None:
    rows = (candle(0), candle(1))
    query = MarketDataQuery(symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.ONE_MINUTE, limit=2)
    def fetch(mode):
        service = MarketDataService([RawProvider(rows)], now=lambda: START + timedelta(minutes=2),
            alignment_validator=MarketAlignmentValidator(mode))
        return asyncio.run(service.get_historical_candles(query)).model_dump(mode="json")
    assert fetch("shadow") == fetch("python")


@pytest.mark.parametrize("kind", ["off_grid", "future", "gap", "duplicate", "disorder", "ohlc"])
def test_shadow_preserves_market_failure_classification(kind) -> None:
    rows = [candle(0), candle(1)]
    if kind == "off_grid":
        rows[1] = rows[1].model_copy(update={"timestamp": START + timedelta(seconds=61)})
    elif kind == "future":
        rows[1] = candle(2)
    elif kind == "gap":
        rows[1] = candle(2)
    elif kind == "duplicate":
        rows[1] = candle(0)
    elif kind == "disorder":
        rows.reverse()
    else:
        rows[1] = rows[1].model_copy(update={"high": rows[1].low})
    errors = []
    for mode in ("python", "shadow"):
        now = START + timedelta(minutes=2 if kind == "future" else 3)
        service = MarketDataService([RawProvider(rows)], now=lambda: now,
            alignment_validator=MarketAlignmentValidator(mode))
        with pytest.raises(MarketDataUpstreamError) as caught:
            asyncio.run(service.get_historical_candles(MarketDataQuery(
                symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.ONE_MINUTE, limit=2)))
        errors.append(caught.value.details)
    assert errors[0] == errors[1]


def test_malformed_native_response_maps_to_existing_redacted_http_domain_error() -> None:
    service = MarketDataService([RawProvider((candle(0),))], now=lambda: START + timedelta(minutes=1),
        alignment_validator=MarketAlignmentValidator(native=lambda payload: b"secret-backtrace"))
    with pytest.raises(MarketDataUpstreamError) as caught:
        asyncio.run(service.get_historical_candles(MarketDataQuery(
            symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.ONE_MINUTE, limit=1)))
    assert caught.value.details == {"provider": "trusted_unit_provider", "reason": "RustComputeError"}
    assert "secret" not in str(caught.value)


def test_closed_range_inherits_explicit_shadow_validator() -> None:
    class Range(RawProvider):
        async def get_historical_candles_between(self, symbol, timeframe, start, end, limit):
            return self.candles
    service = MarketDataService([Range((ParsedProviderCandle(**candle(0).model_dump()),))],
        now=lambda: START + timedelta(minutes=1),
        alignment_validator=MarketAlignmentValidator(native=lambda payload: b"malformed"))
    with pytest.raises(MarketDataUpstreamError) as caught:
        asyncio.run(service.get_closed_range(MarketSymbol.BTCUSDT, Timeframe.ONE_MINUTE,
            START, START + timedelta(minutes=1)))
    assert caught.value.details["reason"] == "RustComputeError"


def test_operational_settings_do_not_enable_native_only_production_cutover() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, market_alignment_implementation="rust")


def test_explicit_python_selection_can_start_without_native_wheel(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "_utc_alignment_core", None)
    service = build_market_data_service(Settings(_env_file=None, market_alignment_implementation="python"))
    asyncio.run(service.provider_for(MarketSymbol.BTCUSDT).aclose())
