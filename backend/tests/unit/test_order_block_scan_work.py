"""Completed order blocks keep all evidence without repeated terminal work."""
from app.engines.smc import order_blocks
from app.schemas.order_block import OrderBlockStatus
from app.schemas.structure import StructureDirection
from app.schemas.order_block import OrderBlockDisplacementLink
from app.schemas.types import Timeframe
from tests.unit import test_order_blocks as fixtures


def test_terminal_order_block_work_does_not_grow_with_later_bars(monkeypatch):
    terminal_reads = 0
    original = order_blocks._OrderBlockState.__getattribute__

    def counted(zone, name):
        nonlocal terminal_reads
        value = original(zone, name)
        if name == 'status' and value in {OrderBlockStatus.INVALIDATED, OrderBlockStatus.EXPIRED}:
            terminal_reads += 1
        return value

    monkeypatch.setattr(order_blocks._OrderBlockState, '__getattribute__', counted)
    candles = fixtures.bullish_base()
    candles += [fixtures.bar(index, '5', '6', '4', '5') for index in range(4, 104)]
    result = order_blocks.analyze_order_blocks(candles, Timeframe.ONE_MINUTE,
        [fixtures.structure_event(StructureDirection.BULLISH)], fixtures.ob_config())
    assert result.order_blocks[0].status is OrderBlockStatus.INVALIDATED
    assert result.order_blocks[0].lifecycle
    assert terminal_reads <= 10


def test_displacement_lookup_does_not_rescan_unrelated_evidence(monkeypatch):
    candles = fixtures.bullish_base()
    events = [fixtures.structure_event(StructureDirection.BULLISH) for _ in range(100)]
    links = [OrderBlockDisplacementLink(displacement_id=f'unrelated-{index}',
        structure_event=f'unrelated-{index}', confirmed_at=events[0].confirmed_at)
        for index in range(100)]
    original = OrderBlockDisplacementLink.__getattribute__
    reads = 0
    def measured(link, name):
        nonlocal reads
        if name == 'structure_event':
            reads += 1
        return original(link, name)
    monkeypatch.setattr(OrderBlockDisplacementLink, '__getattribute__', measured)
    result = order_blocks.analyze_order_blocks(candles, Timeframe.ONE_MINUTE,
        events, fixtures.ob_config(require_displacement=True), qualified_displacements=links)
    assert result.order_blocks == []
    assert len(result.rejections) == len(events)
    assert reads <= 2*len(links)
