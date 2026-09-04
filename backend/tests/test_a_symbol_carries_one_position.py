"""
الأداة الواحدة لا تحمل تعرّضاً مضاعفاً، والمطابقة تجمع ما عليها لا تمحوه.

يوم 2026-09-04 فُتح على GBPUSD مركزان بحجم ٢٠٠ لكلٍّ منهما، من استراتيجيتين
مختلفتين على الشمعة نفسها — فصار التعرّض ضِعف المعتمد على أداةٍ واحدة.
وحارسُ الإعداد لا يمنع ذلك لأن مفتاحه يحمل اسم الاستراتيجية.

وفي المطابقة كان الجانبان يُبنيان قاموساً مفتاحه الرمز، فيمحو المركزُ الثاني
الأول: قُرئ ‎-200‎ على الجانبين وقيل «مطابَق»، وفي الحساب ‎-400‎.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.contracts import Position
from app.execution.orders import reconcile

NOW = datetime(2026, 9, 4, 13, 45, tzinfo=timezone.utc)


def _position(symbol: str, quantity: str) -> Position:
    return Position(
        account_id="acct",
        symbol=symbol,
        quantity=Decimal(quantity),
        average_cost=Decimal("1.35"),
        as_of_utc=NOW,
    )


def test_two_positions_on_one_symbol_are_summed_not_overwritten():
    result = reconcile(
        local_positions=[_position("GBPUSD", "-200")],
        broker_positions=[_position("GBPUSD", "-200"), _position("GBPUSD", "-200")],
        now=NOW,
    )
    assert not result.matched
    assert any("-400" in problem for problem in result.discrepancies_ar), result.discrepancies_ar


def test_a_symbol_matches_when_the_totals_agree():
    result = reconcile(
        local_positions=[_position("GBPUSD", "-100"), _position("GBPUSD", "-100")],
        broker_positions=[_position("GBPUSD", "-200")],
        now=NOW,
    )
    assert result.matched, result.discrepancies_ar


def test_a_position_only_the_broker_has_is_still_named():
    result = reconcile(
        local_positions=[],
        broker_positions=[_position("GOLD", "-0.01")],
        now=NOW,
    )
    assert not result.matched
    assert any("GOLD" in problem for problem in result.discrepancies_ar)
