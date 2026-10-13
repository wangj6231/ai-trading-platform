"""A shared worker preserves every caller's fully validated public result."""
import asyncio
from datetime import timedelta

import pytest

from app.core.errors import AppError
from app.core.strategy_config import load_strategy_config
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.market import MarketDataProvenance
from app.schemas.strategy import StrategyEvaluationContext
from app.schemas.types import Timeframe
from app.services.evaluation_execution import IsolatedEvaluationRunner, evaluate_response, prepare_response_engine
from app.services.evaluation_response import signal_response, analysis_response
from tests.integration.test_deterministic_api import (
    BULLISH_PRICES, LEGACY_CONFIG_PATH, candles_from, mirrored_prices,
)


def payloads(case):
    engine = ConcreteDeterministicStrategyEngine(load_strategy_config(LEGACY_CONFIG_PATH))
    prices = mirrored_prices() if case == 'short' else BULLISH_PRICES
    candles = candles_from(prices[:2] if case == 'no_trade' else prices)
    cutoff = candles[-1].timestamp + timedelta(minutes=1)
    context = StrategyEvaluationContext(symbol='BTCUSDT', as_of=cutoff,
        candles_by_timeframe={Timeframe.ONE_MINUTE: candles})
    result = engine.evaluate(context)
    members, expected = [], []
    for index, kind in enumerate(['analysis', 'signal']):
        provenance = MarketDataProvenance(provider='explicit_legacy_test_fixture', data_mode='SERVER_PROVIDER',
            symbol='BTCUSDT', timeframe='1m', first_candle_at=candles[0].timestamp,
            last_candle_at=candles[-1].timestamp, data_cutoff_at=cutoff,
            expected_latest_closed_candle_at=cutoff, retrieved_at=cutoff+timedelta(seconds=index),
            requested_candles=len(candles), received_candles=len(candles), lag_seconds=0)
        members.append(dict(config=engine.strategy_config.model_dump(mode='json'),
            context=context.model_dump(mode='json'), provenance=provenance.model_dump(mode='json'),
            signal_timeframe='1m', response_kind=kind))
        response = (analysis_response if kind == 'analysis' else signal_response)(provenance, result)
        expected.append(response.model_dump_json().encode('utf-8'))
    return members, expected


@pytest.mark.parametrize('case', ['long', 'short', 'no_trade'])
def test_shared_projection_is_byte_identical_and_signal_publishes_first(case):
    members, expected = payloads(case)
    async def exercise():
        runner = IsolatedEvaluationRunner(max_workers=1)
        publications = []
        async def prepared():
            return {**members[0], '_response_group': True}
        async def projections():
            return members
        try:
            await runner.warm(members[0]['config'])
            await runner.run_prepared(evaluate_response, prepared, initializer=prepare_response_engine,
                initial_payload=members[0]['config'], projections=projections,
                published=publications.append)
        finally:
            await runner.aclose()
        assert publications == [(1, expected[1]), (0, expected[0])]
        assert not runner._active
    asyncio.run(exercise())


def test_worker_rejects_different_full_context_even_if_coordinator_key_is_wrong():
    members, _ = payloads('no_trade')
    members[1]['context'] = {**members[1]['context'], 'symbol': 'ETHUSDT'}
    async def exercise():
        runner = IsolatedEvaluationRunner(max_workers=1)
        async def prepared():
            return {**members[0], '_response_group': True}
        async def projections():
            return members
        with pytest.raises(AppError) as rejected:
            await runner.run_prepared(evaluate_response, prepared, initializer=prepare_response_engine,
                initial_payload=members[0]['config'], projections=projections, published=lambda _: None)
        assert rejected.value.code == 'STRATEGY_EVALUATION_FAILED'
        assert not runner._active
        await runner.aclose()
    asyncio.run(exercise())
