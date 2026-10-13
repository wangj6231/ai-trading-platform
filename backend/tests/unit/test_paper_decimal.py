from decimal import Decimal, DefaultContext, Inexact, Rounded, ROUND_DOWN, localcontext

from app.execution.decimal_policy import add, divide, multiply, subtract


def test_financial_arithmetic_does_not_inherit_ambient_rounding():
    results = []
    for precision in (3, 28, 80):
        with localcontext() as context:
            context.prec = precision
            context.rounding = ROUND_DOWN
            results.append((
                add(Decimal('100000000000000000000'), Decimal('0.0001')),
                multiply(Decimal('100.123456789'), Decimal('0.001')),
                divide(Decimal('302'), Decimal('3')),
                subtract(Decimal('306'), Decimal('302')),
            ))
    assert results[0] == results[1] == results[2]
    assert results[0] == (
        Decimal('100000000000000000000.0001'),
        Decimal('0.100123456789'),
        Decimal('100.66666666666666666666666666666666666666666666667'),
        Decimal('4'),
    )


def test_terminating_division_preserves_more_than_fifty_digits():
    numerator = Decimal('12345678901234567890123456789012345678901234567890123456789')
    assert divide(numerator, Decimal('2')) == Decimal(
        '6172839450617283945061728394506172839450617283945061728394.5'
    )


def test_mutable_global_default_traps_cannot_change_financial_policy():
    previous = DefaultContext.copy()
    try:
        DefaultContext.traps[Inexact] = True
        DefaultContext.traps[Rounded] = True
        assert divide(Decimal('302'), Decimal('3')) == Decimal(
            '100.66666666666666666666666666666666666666666666667')
    finally:
        DefaultContext.traps = previous.traps.copy()
