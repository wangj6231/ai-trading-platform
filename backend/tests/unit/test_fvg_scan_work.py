"""Historical terminal gaps retain evidence without repeated no-op replay."""
import json
from datetime import timedelta

from app.engines.smc import fvg
from app.schemas.candle import Candle
from app.schemas.types import Timeframe
from tests.unit import test_fvg as fixtures


def test_terminal_fvg_archive_is_not_replayed_on_later_bars(monkeypatch):
    candles = [Candle.model_validate(row) for row in json.loads(fixtures.FIXTURE_PATH.read_text())['bullish']]
    last = candles[-1]
    candles += [last.model_copy(update={'timestamp': last.timestamp + timedelta(minutes=index)}) for index in range(1, 101)]
    original = fvg._update_zone
    terminal_visits = []

    def counted(zone, *args):
        if zone.lifecycle_state in fvg.TERMINAL_STATES:
            terminal_visits.append(zone.zone_id)
        return original(zone, *args)

    monkeypatch.setattr(fvg, '_update_zone', counted)
    result = fvg.analyze_fvg(candles, Timeframe.ONE_MINUTE, fixtures.fvg_config(max_age=1))
    assert any(zone.lifecycle_state in fvg.TERMINAL_STATES for zone in result.zones)
    assert all(zone.lifecycle for zone in result.zones)
    assert not terminal_visits
