"""Structure zone lookup preserves nearest-anchor and creation-order ties."""
from decimal import Decimal, localcontext

import pytest
from app.engines.structure import primitives
from app.schemas.structure import SwingKind, ZoneKind
from tests.unit.test_liquidity import swing
from tests.unit.test_market_structure import structure_config


def test_nonmatching_zone_lookup_does_not_scan_every_anchor(monkeypatch):
    calls = 0

    def counted(value):
        nonlocal calls
        calls += 1
        return abs(value)

    monkeypatch.setattr(primitives, 'abs', counted, raising=False)
    swings = [swing(str(index), SwingKind.HIGH, str(100+index),
        pivot_index=index, confirmed_minute=index+2) for index in range(500)]
    result = primitives._build_zones(swings, ZoneKind.RESISTANCE, structure_config())
    assert len(result) == len(swings)
    assert calls < len(swings) * 30


def test_nearest_anchor_tie_keeps_original_creation_order():
    swings = [swing(str(index), SwingKind.HIGH, price,
        pivot_index=index, confirmed_minute=index+2) for index, price in enumerate(['12', '8', '10'])]
    config = structure_config().model_copy(update={'zone_merge_tolerance_ticks': 4})
    result = primitives._build_zones(swings, ZoneKind.RESISTANCE, config)
    assert [zone.source_swing_ids for zone in result] == [('0', '2'), ('1',)]


@pytest.mark.parametrize('precision', [6, 28, 34])
@pytest.mark.parametrize('prices', [
    ['12', '8', '10', '10.01', '9.99', '8', '13.999999'],
    ['1000000.12', '1000000.08', '1000000.1', '1000000.099999', '999999.1'],
])
def test_zone_membership_matches_original_decimal_distance_and_priority(precision, prices):
    config = structure_config().model_copy(update={'zone_merge_tolerance_ticks': 4})
    swings = [swing(str(index), SwingKind.HIGH, price,
        pivot_index=index, confirmed_minute=index+2) for index, price in enumerate(prices)]
    with localcontext() as context:
        context.prec = precision
        tolerance = config.tick_size * Decimal(config.zone_merge_tolerance_ticks)
        groups = []
        for point in swings:
            matches = [(abs(point.price-anchor), index) for index, (anchor, _) in enumerate(groups)
                if abs(point.price-anchor) <= tolerance]
            if matches:
                _, index = min(matches)
                groups[index][1].append(point.swing_id)
            else:
                groups.append((point.price, [point.swing_id]))
        actual = primitives._build_zones(swings, ZoneKind.RESISTANCE, config)
        assert [(zone.anchor_price, zone.source_swing_ids) for zone in actual] == [
            (anchor, tuple(members)) for anchor, members in groups]
