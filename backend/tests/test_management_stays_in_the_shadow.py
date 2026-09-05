"""الخطّة تُبنى ولا تُنفَّذ — والمراكز بلا نسبةٍ لا تُمَسّ أبداً.

القاعدة التي وضعتها المالكة (D-19) ليست «السجلّ فارغٌ اليوم فلا شيء يقع».
سجلٌّ فارغٌ حالةٌ عابرة؛ والقاعدة يجب أن تصمد **يوم يُملأ**. فمركزٌ لا
يُعرَف أيُّ قرارٍ فتحه لا تُطبَّق عليه قواعدُ استراتيجيةٍ لم تفتحه — ولو
كانت تلك الاستراتيجية مُعلَنةً بسياسةٍ كاملةٍ الأدلة.

وحارسٌ ثانٍ: لا مسارَ في شيفرة الإنتاج يأخذ فعلاً من الخطّة ويرسله إلى
الوسيط. وضعُ الظلّ ليس نيّةً — هو غيابُ الوصلة.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.portfolio.book import OpenPosition
from app.positions.engine import (
    SKIP_UNATTRIBUTED,
    PositionManager,
)
from app.positions.policy import REGISTRY, Capability, ManagementPolicy, PolicyRegistry

APP = Path(__file__).resolve().parents[1] / "app"
NOW = datetime.now(timezone.utc)


@dataclass
class _Row:
    broker_deal_id: str
    symbol: str
    quantity: Decimal
    entry_price: Decimal | None
    stop_price: Decimal | None
    take_profit_price: Decimal | None
    strategy_name: str
    strategy_version: str
    attribution: str
    state: str = "OPEN"
    opened_at_utc: datetime | None = None


def _row(**kw) -> _Row:
    base = dict(
        broker_deal_id="d-1", symbol="EURUSD", quantity=Decimal("300"),
        entry_price=Decimal("1.16"), stop_price=Decimal("1.15"),
        take_profit_price=Decimal("1.17"), strategy_name="TREND_PULLBACK",
        strategy_version="2.0.0", attribution="LINKED",
    )
    base.update(kw)
    return _Row(**base)


def _live(row: _Row) -> OpenPosition:
    return OpenPosition(
        symbol=row.symbol, quantity=row.quantity, entry_price=row.entry_price,
        stop_price=row.stop_price, take_profit_price=row.take_profit_price,
        deal_id=row.broker_deal_id, opened_utc=NOW - timedelta(hours=3),
    )


def _registry_with_a_live_policy() -> PolicyRegistry:
    """سجلٌّ **غيرُ فارغ** — كي لا يكون الفراغُ هو ما يحمي."""
    registry = PolicyRegistry()
    policy = ManagementPolicy(
        strategy_name="TREND_PULLBACK",
        strategy_version="2.0.0",
        policy_version="drill-1",
        capabilities=frozenset({Capability.BREAK_EVEN}),
        break_even_after_r=Decimal("1.0"),
        backtest_evidence_ar="تمرين — لا يُسجَّل في الإنتاج",
        out_of_sample_evidence_ar="تمرين — لا يُسجَّل في الإنتاج",
        paper_evidence_ar="تمرين — لا يُسجَّل في الإنتاج",
    )
    registry.register(policy)
    return registry


def test_the_registry_used_here_is_really_not_empty():
    registry = _registry_with_a_live_policy()
    policy = registry.for_strategy("TREND_PULLBACK", "2.0.0")
    assert not policy.is_fixed_only, "السجلّ الاختباري فارغٌ فعلياً — الحارس غير مُختبَر"


def test_an_unattributed_position_is_skipped_even_with_a_policy_registered():
    row = _row(attribution="UNLINKED", strategy_name="", strategy_version="")
    plan = PositionManager(_registry_with_a_live_policy()).plan(
        broker_positions=[_live(row)], book_rows=[row], now=NOW
    )
    assert plan.touched == 0
    assert [s.code for s in plan.skipped] == [SKIP_UNATTRIBUTED]


def test_a_named_strategy_without_linked_attribution_is_still_skipped():
    row = _row(attribution="UNLINKED")
    plan = PositionManager(_registry_with_a_live_policy()).plan(
        broker_positions=[_live(row)], book_rows=[row], now=NOW
    )
    assert plan.touched == 0
    assert [s.code for s in plan.skipped] == [SKIP_UNATTRIBUTED]


def test_the_shipped_registry_is_empty_by_design():
    assert not (getattr(REGISTRY, "_policies", None) or {}), (
        "سياسةٌ مُسجَّلة بلا قرارٍ مكتوب — D-20 يشترط دليلاً"
    )


def test_no_production_path_sends_a_management_action_to_the_broker():
    """وضعُ الظلّ غيابُ وصلة، لا نيّة."""
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        if "management_plan" not in code and "ManagementPlan" not in code:
            continue
        if re.search(r"modify_position_protection|amend_position|update_stop", code):
            offenders.append(str(path.relative_to(APP)))
    assert offenders == [], (
        "مسارٌ يأخذ من خطّة الإدارة ويرسل إلى الوسيط: " + ", ".join(offenders)
    )
