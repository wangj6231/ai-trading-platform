"""Batch lookup must not repeatedly hand complete evidence archives to each sweep."""
from app.engines.ict import high_probability_entry as entry
from app.schemas.entry_setup import EntrySetupDirection
from app.schemas.types import Timeframe
from tests.unit import test_high_probability_entry as fixtures


def test_each_sweep_receives_exact_first_eligible_evidence(monkeypatch):
    source, structure, leg, zone = fixtures.components(EntrySetupDirection.BULLISH)
    structures = [structure.model_copy(update={"broken_structure_id": f"level-{index:03}"}) for index in range(100)]
    original = entry._evaluate_sweep
    seen = []
    def measured(sweep, **kwargs):
        seen.append((len(kwargs["mss_events"]), len(kwargs["legs"])))
        return original(sweep, **kwargs)
    monkeypatch.setattr(entry, "_evaluate_sweep", measured)
    result = entry.detect_high_probability_entry_setups(fixtures.long_candles(),
        Timeframe.ONE_MINUTE, [source], structures, [leg], [zone], fixtures.setup_config())
    assert len(result.setups) == 1
    assert all(mss <= 2 and legs <= 1 for mss, legs in seen)
