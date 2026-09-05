"""«لا فعل» ليست «كلُّ شيءٍ مطابَق».

كانت الخطّة تقول «المراكز كلُّها مقروءةٌ ومطابَقة» لمجرّد أنّ عدد الأفعال
صفر. ومركزٌ لم يظهر عند الوسيط يُتخطّى بلا فعل — فتقول الشاشة إنّه مطابَق.
وهي أسوأ رسالةٍ ممكنة: طمأنينةٌ في موضع الجهل.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.positions.engine import PositionManager
from app.positions.policy import PolicyRegistry


@dataclass
class _Row:
    broker_deal_id: str
    symbol: str
    quantity: Decimal
    entry_price: Decimal | None = Decimal("1.1")
    stop_price: Decimal | None = Decimal("1.0")
    strategy_name: str = ""
    strategy_version: str = ""
    attribution: str = "UNLINKED"
    state: str = "OPEN"


def _plan(rows, broker_positions=()):
    return PositionManager(PolicyRegistry()).plan(
        broker_positions=list(broker_positions),
        book_rows=list(rows),
        now=datetime.now(timezone.utc),
    )


def _notes(plan) -> str:
    return " ".join(plan.notes_ar)


def test_an_empty_book_says_so():
    assert "لا مركزَ مفتوح" in _notes(_plan([]))


def test_nothing_matched_is_never_called_matched():
    rows = [_Row("d1", "EURUSD", Decimal("100")), _Row("d2", "GBPUSD", Decimal("-100"))]
    plan = _plan(rows, broker_positions=[])
    assert plan.touched == 0
    assert len(plan.skipped) == 2
    note = _notes(plan)
    assert "مطابَقة" not in note or "لا يُقال" in note, (
        f"الملاحظة تدّعي مطابقةً لم تقع: {note}"
    )
    assert "لا واحدٌ" in note or "لم يظهر" in note


def test_the_count_of_the_unmatched_is_named():
    rows = [_Row(f"d{i}", "EURUSD", Decimal("100")) for i in range(3)]
    note = _notes(_plan(rows, broker_positions=[]))
    assert "3" in note, f"عدد ما لم يُطابَق غير مذكور: {note}"
