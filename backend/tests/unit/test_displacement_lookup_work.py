"""Displacement link lookup must examine only possible source-bar candidates."""
from app.engines.smc import displacement
from app.schemas.fvg import GapDirection
from app.schemas.structure import StructureDirection
from app.schemas.types import Timeframe
from tests.unit import test_displacement as fixtures


def test_fvg_lookup_does_not_scan_irrelevant_archive(monkeypatch):
    candles = fixtures.baseline() + [fixtures.bar(index, "10", "12", "10", "12") for index in range(3, 100)]
    zones = [fixtures.fvg(f"zone-{index}", GapDirection.BULLISH,
        source_indices=(index-2, index-1, index), confirmed_minute=index+1) for index in range(3, 100)]
    original = displacement._matching_fvgs
    lengths = []
    def measured(zones, *args):
        lengths.append(len(zones))
        return original(zones, *args)
    monkeypatch.setattr(displacement, "_matching_fvgs", measured)
    result = displacement.analyze_displacement(candles, Timeframe.ONE_MINUTE,
        [fixtures.structure_event(StructureDirection.BULLISH)], fixtures.config(require_fvg=True), fvg_zones=zones)
    assert result.legs[0].associated_fvg == ("zone-3",)
    assert max(lengths) <= 3
