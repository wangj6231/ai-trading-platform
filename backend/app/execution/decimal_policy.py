"""PAPER_DECIMAL_V1: exact arithmetic, 50-digit nonterminating division."""

from decimal import (
    Context, Decimal, DivisionByZero, Inexact, InvalidOperation, MAX_EMAX,
    MIN_EMIN, Overflow, ROUND_HALF_EVEN, localcontext,
)

NUMERIC_POLICY_VERSION = 'PAPER_DECIMAL_V1'
DIVISION_PRECISION = 50


def _context(precision: int) -> Context:
    return Context(prec=max(precision, 1), rounding=ROUND_HALF_EVEN,
                   Emax=MAX_EMAX, Emin=MIN_EMIN, capitals=1, clamp=0,
                   flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])


def _width(value: Decimal) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError('financial arithmetic requires finite Decimal')
    return len(value.as_tuple().digits)


def add(left: Decimal, right: Decimal) -> Decimal:
    _width(left)
    _width(right)
    exponent = min(int(left.as_tuple().exponent), int(right.as_tuple().exponent))
    precision = max(left.adjusted(), right.adjusted()) - exponent + 3
    with localcontext(_context(precision)):
        return left + right


def subtract(left: Decimal, right: Decimal) -> Decimal:
    return add(left, right.copy_negate())


def multiply(left: Decimal, right: Decimal) -> Decimal:
    with localcontext(_context(_width(left) + _width(right) + 1)):
        return left * right


def divide(left: Decimal, right: Decimal) -> Decimal:
    # For finite decimal operands a terminating quotient needs no more than
    # this conservative digit bound (powers of 2/5 included). Inexact is the
    # explicit boundary: only then apply the frozen 50-significant-digit rule.
    precision = 4 * (_width(left) + _width(right) + abs(
        int(left.as_tuple().exponent) - int(right.as_tuple().exponent))) + 10
    exact = _context(precision)
    exact.traps[Inexact] = True
    try:
        with localcontext(exact):
            return left / right
    except Inexact:
        with localcontext(_context(DIVISION_PRECISION)):
            return left / right


def decimal_text(value: Decimal) -> str:
    _width(value)
    if value == 0:
        return '0'
    encoded = format(value, 'f')
    return encoded.rstrip('0').rstrip('.') if '.' in encoded else encoded
