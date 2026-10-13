"""Complete active-work keys never confer display-timeframe authority."""
from dataclasses import replace
from datetime import timedelta
import copy

import pytest

from app.core.strategy_config import load_strategy_config
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.market_data.historical import HistoricalBootstrapProvenance
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.market import MarketDataProvenance
from app.schemas.strategy import StrategyEvaluationContext
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.types import Timeframe
from app.services import strategy_evaluation
from app.services.strategy_evaluation import PreparedStrategyEvaluation, StrategyEngineBinding, _response_flight_key
from tests.integration.test_deterministic_api import LEGACY_CONFIG_PATH
from tests.unit.test_evaluation_group_projection import payloads


@pytest.mark.parametrize('dimension', [
    'symbol', 'cutoff', 'source_timeframe', 'provider', 'data_mode', 'history',
    'version', 'config_hash', 'build', 'config_values', 'source_code', 'mode',
])
def test_every_authority_and_source_dimension_separates_active_work(monkeypatch, dimension):
    monkeypatch.setattr(strategy_evaluation, '_runtime_source_checkpoint', lambda: 'source-A')
    payload = payloads('no_trade')[0][0]
    engine = ConcreteDeterministicStrategyEngine(load_strategy_config(LEGACY_CONFIG_PATH))
    context = StrategyEvaluationContext.model_validate(payload['context'])
    provenance = MarketDataProvenance.model_validate(payload['provenance'])
    history = HistoricalBootstrapProvenance(provider=provenance.provider, symbol=provenance.symbol,
        timeframe=provenance.timeframe, requested_start=provenance.first_candle_at,
        requested_end=provenance.data_cutoff_at, retrieved_at=provenance.retrieved_at,
        page_count=1, cache_hit=True, rebootstrap=False, content_hash='fixture-history-A')
    prepared = PreparedStrategyEvaluation(binding=StrategyEngineBinding(engine=engine,
        source_timeframe=Timeframe.ONE_MINUTE, minimum_source_candles={provenance.symbol: 2}),
        signal_timeframe=Timeframe.ONE_MINUTE, provenance=provenance, context=context,
        historical_provenance=history)
    request = ProductionAnalysisRequest(symbol='BTCUSDT')
    original = _response_flight_key(request, prepared, payload)
    if dimension == 'symbol':
        request = ProductionAnalysisRequest(symbol='ETHUSDT')
    elif dimension == 'cutoff':
        prepared = replace(prepared, context=context.model_copy(update={'as_of': context.as_of+timedelta(minutes=1)}))
    elif dimension == 'source_timeframe':
        prepared = replace(prepared, binding=replace(prepared.binding, source_timeframe=Timeframe.FIFTEEN_MINUTES))
    elif dimension in ('provider', 'data_mode'):
        update = {dimension: 'fixture-provider-B' if dimension == 'provider' else 'RESEARCH_FIXTURE'}
        # Key checks can use the real enum's alternate mode, when one exists.
        if dimension == 'data_mode':
            from app.schemas.market import MarketDataMode
            update = {dimension: next(mode for mode in MarketDataMode if mode != provenance.data_mode)}
        prepared = replace(prepared, provenance=provenance.model_copy(update=update))
    elif dimension == 'history':
        prepared = replace(prepared, historical_provenance=replace(history, content_hash='fixture-history-B'))
    elif dimension in ('version', 'config_hash', 'build'):
        field = {'version': 'strategy_version', 'config_hash': 'config_hash', 'build': 'algorithm_build_hash'}[dimension]
        value = 'different-version' if dimension == 'version' else 'a'*64
        engine._strategy_identity = StrategyIdentity.model_validate({**engine.strategy_identity.model_dump(), field: value})
    elif dimension == 'config_values':
        payload = copy.deepcopy(payload)
        payload['config']['strategy_version'] = 'different-version'
    elif dimension == 'source_code':
        monkeypatch.setattr(strategy_evaluation, '_runtime_source_checkpoint', lambda: 'source-B')
    else:
        request = ProductionAnalysisRequest(symbol='BTCUSDT', cutoff=context.as_of)
    assert _response_flight_key(request, prepared, payload) != original


def test_retrieval_metadata_and_display_hint_do_not_change_evaluated_evidence(monkeypatch):
    monkeypatch.setattr(strategy_evaluation, '_runtime_source_checkpoint', lambda: 'source-A')
    members, _ = payloads('no_trade')
    engine = ConcreteDeterministicStrategyEngine(load_strategy_config(LEGACY_CONFIG_PATH))
    context = StrategyEvaluationContext.model_validate(members[0]['context'])
    binding = StrategyEngineBinding(engine, Timeframe.ONE_MINUTE, {context.symbol: 2})
    keys = []
    for payload, hint in zip(members, ['1m', '1d'], strict=True):
        provenance = MarketDataProvenance.model_validate(payload['provenance'])
        prepared = PreparedStrategyEvaluation(binding, Timeframe.ONE_MINUTE, provenance, context, None)
        request = ProductionAnalysisRequest(symbol='BTCUSDT', timeframe=hint)
        keys.append(_response_flight_key(request, prepared, payload))
    assert keys[0] == keys[1]
