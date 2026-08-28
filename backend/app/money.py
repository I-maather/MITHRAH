"""
Money & decimal primitives.

قاعدة صارمة: كل المبالغ المالية Decimal وليست float.
حساب بـ float على رأس مال 100 دولار ينتج أخطاء تقريب تفسد قرارات المخاطر.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, getcontext

getcontext().prec = 28

USD = "USD"

CENT = Decimal("0.01")
SUB_CENT = Decimal("0.0001")
QTY_PRECISION = Decimal("0.0001")  # IBKR fractional share granularity used internally


def D(value) -> Decimal:
    """Safe Decimal constructor (never from binary float directly)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value) -> Decimal:
    """Round to cents, half-up. Used only for *display / settlement* amounts."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money_ceil(value) -> Decimal:
    """Round a COST upward — never understate what a trade may cost us."""
    return D(value).quantize(CENT, rounding=ROUND_UP)


def money_floor(value) -> Decimal:
    """Round a BENEFIT downward — never overstate what we may receive."""
    return D(value).quantize(CENT, rounding=ROUND_DOWN)


def quantize_qty(value, granularity: Decimal = QTY_PRECISION) -> Decimal:
    """Round a quantity DOWN to the tradable granularity (never size up)."""
    return D(value).quantize(granularity, rounding=ROUND_DOWN)


def pct(value) -> Decimal:
    """0.5 -> Decimal('0.005')"""
    return D(value) / Decimal("100")


def as_pct(value) -> Decimal:
    """Decimal('0.005') -> Decimal('0.5')"""
    return D(value) * Decimal("100")


def safe_div(numerator, denominator, default: Decimal = Decimal("0")) -> Decimal:
    d = D(denominator)
    if d == 0:
        return default
    return D(numerator) / d
