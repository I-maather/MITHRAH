"""
**كل صفقة بيعٍ كانت تُرفض برسالة تقول إن الاستراتيجية أنتجت هراءً.**

## العطل

`risk/engine.py` كان يفحص خطة الخروج هكذا:

    take_profit <= entry  or  stop >= entry   ⇒  NO_EXIT_PLAN

وهذا **وصف صفقة شراءٍ وحدها**. وفي البيع الوقف فوق الدخول والهدف تحته،
فيصدق الشرطان معاً — فتُرفض كلُّ صفقة بيعٍ بنصّ «خطة الخروج غير صالحة:
الهدف والوقف غير منطقيين». وهي منطقيةٌ تماماً؛ والمنطقُ المكسور هو الفحص.

و`Signal.reward_risk_ratio` كان يحسب `entry - stop` — موجبٌ في الشراء
وسالبٌ في البيع — فيعيد صفراً لكل بيعٍ، فتُرفض ثانيةً بـ«نسبة العائد أقل
من الحد» لو نجت من الأولى.

وثلاثٌ من أربع استراتيجيات مسجَّلة تُصدر بيعاً، وتُعلنه في فرضيّتها:
«صعوداً كان أو هبوطاً». ⇒ **نحو نصف الإشارات كان يُقتل بسببٍ كاذب.**

## وأخطر منه

`CFD_ALLOW_SHORT = False` مكتوبةٌ في الدستور ومنشورةٌ في بصمته، **ولا
تُقرأ في أي موضع من النظام**. فكان منعُ البيع يقع **بالصدفة** عبر الحساب
المكسور، ويُبلَّغ برمزٍ يخصّ شيئاً آخر.

وسياسةٌ تُفرَض بالغلط تسقط يوم يُصلَح الغلط — بلا أن ينتبه أحد. ولولا أن
هذا الملف كُتب مع الإصلاح، لفُتح البيع صامتاً في اللحظة نفسها التي صُحّح
فيها الحساب.

## القاعدة

السؤالان مفصولان: **«هل الجهات صحيحة؟»** يُفحَص باتجاه الصفقة، و**«هل
البيع مسموح؟»** يُقرأ من الدستور ويُرفض باسمه. والسلوك لم يتغيّر — البيع
يبقى ممنوعاً، لكن بقرارٍ مكتوب لا بكسرٍ في المعادلة.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.contracts import Broker, Side, Signal
from app.money import D
from app.risk.constitution import ALLOW_SHORT, CFD_ALLOW_SHORT, RiskLimits, RiskMode
from app.risk.engine import NO_EXIT_PLAN, SHORT_NOT_ALLOWED, RiskEngine, SessionRiskState

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def signal(side: Side, entry: str, stop: str, target: str, symbol: str = "GOLD") -> Signal:
    return Signal(
        strategy_name="T", strategy_version="1.0.0", symbol=symbol, side=side,
        entry_price=D(entry), stop_price=D(stop), take_profit_price=D(target),
        generated_at_utc=NOW, rationale_ar="—", invalidation_ar="—", inputs_digest="d",
    )


#: بيعٌ صحيح على الذهب: الوقف فوق الدخول بـ1.5×ATR، والهدف تحته بـ3×ATR.
VALID_SELL = ("4389.00", "4529.79", "4107.42")
VALID_BUY = ("4389.00", "4248.21", "4670.58")


class TestTheRatio:
    def test_a_sell_has_a_real_reward_risk_ratio(self):
        """
        **الفحص الذي يعضّ.** بيعٌ بوقف 140.79 وهدف 281.58 نسبتُه 2.0 —
        وكان يُعيد صفراً لأن `entry - stop` سالب.
        """
        sell = signal(Side.SELL, *VALID_SELL)
        assert sell.reward_risk_ratio == pytest.approx(Decimal("2"), abs=Decimal("0.01"))

    def test_the_buy_ratio_is_unchanged(self):
        """والشراء كما كان — الإصلاح لم يمسّه."""
        buy = signal(Side.BUY, *VALID_BUY)
        assert buy.reward_risk_ratio == pytest.approx(Decimal("2"), abs=Decimal("0.01"))

    def test_a_reversed_plan_still_scores_zero(self):
        """
        ولا يُخفَّف الحارس: خطةٌ معكوسة (وقفٌ في جهة الهدف) تبقى صفراً —
        `abs()` وحدها كانت ستجعلها 2.0 وهي أمرٌ يُنفَّذ فوراً بخسارة.
        """
        broken = signal(Side.BUY, "4389.00", "4529.79", "4670.58")  # وقفٌ فوق الشراء
        assert broken.reward_risk_ratio == Decimal("0")
        assert not broken.exit_plan_is_sane


class TestTheDirectionCheck:
    @pytest.mark.parametrize(
        "side, prices, sane",
        [
            (Side.BUY, VALID_BUY, True),
            (Side.SELL, VALID_SELL, True),
            (Side.BUY, VALID_SELL, False),    # خطة بيعٍ موسومةً شراءً
            (Side.SELL, VALID_BUY, False),    # والعكس
        ],
    )
    def test_the_plan_is_judged_by_the_side(self, side, prices, sane):
        assert signal(side, *prices).exit_plan_is_sane is sane

    def test_a_zero_or_negative_price_is_never_sane(self):
        assert not signal(Side.BUY, "4389.00", "0", "4670.58").exit_plan_is_sane


def engine(broker: Broker) -> RiskEngine:
    return RiskEngine(RiskLimits.for_mode(RiskMode.VALIDATION, D("300"), broker))


def state() -> SessionRiskState:
    return SessionRiskState(
        baseline_equity=D("300"), current_equity=D("300"),
        realized_pnl_today=D("0"), realized_pnl_week=D("0"), unrealized_pnl=D("0"),
        open_positions=0, entry_orders_today=0, consecutive_losses=0,
    )


class TestThePolicyIsSaidByName:
    def test_a_valid_sell_is_refused_as_policy_not_as_nonsense(self):
        """
        **جوهر الإصلاح.** البيع يبقى ممنوعاً — والسبب يتغيّر من «خطتك
        هراء» إلى «البيع ممنوع بالدستور». الفرق بينهما هو الفرق بين
        مالكةٍ تبحث عن عطبٍ في استراتيجيتها وأخرى تعرف أن أمامها قراراً.
        """
        rejection, _, _ = engine(Broker.CAPITAL_COM)._run_gates(
            signal=signal(Side.SELL, *VALID_SELL), state=state(),
            kill_switch_active=False, now=NOW,
        )
        assert rejection is not None
        assert rejection.reason_code == SHORT_NOT_ALLOWED
        assert rejection.reason_code != NO_EXIT_PLAN
        assert "CFD_ALLOW_SHORT" in rejection.reason_ar

    def test_a_genuinely_reversed_plan_still_says_no_exit_plan(self):
        """والرمز القديم يبقى لما كُتب له: جهةٌ معكوسة فعلاً."""
        rejection, _, _ = engine(Broker.CAPITAL_COM)._run_gates(
            signal=signal(Side.BUY, *VALID_SELL), state=state(),
            kill_switch_active=False, now=NOW,
        )
        assert rejection is not None and rejection.reason_code == NO_EXIT_PLAN

    def test_a_buy_still_passes_the_gate(self):
        """والشراء يمرّ — الإصلاح لم يغلق ما كان مفتوحاً."""
        rejection, checks, _ = engine(Broker.CAPITAL_COM)._run_gates(
            signal=signal(Side.BUY, *VALID_BUY), state=state(),
            kill_switch_active=False, now=NOW,
        )
        assert rejection is None, rejection.reason_ar if rejection else ""
        assert any(name == "REWARD_RISK" and ok for name, ok, _ in checks)


class TestTheFlagIsActuallyRead:
    def test_the_constitution_flags_are_not_decoration(self):
        """
        **حارسٌ ضدّ العودة.** لو صار البيع مسموحاً وأحدُ العلمين ما زال
        `False`، فالسياسة تُنشَر ولا تُنفَّذ — وهي الحال التي كانت قائمة.

        وهذا الفحص هو ما يمنع أن يُفتح البيع صامتاً يوم يُصلَح الحساب.
        """
        from app.risk.engine import RiskEngine as E

        assert E(RiskLimits.for_mode(
            RiskMode.VALIDATION, D("300"), Broker.CAPITAL_COM
        ))._short_allowed() is CFD_ALLOW_SHORT
        assert E(RiskLimits.for_mode(
            RiskMode.CONSERVATIVE_LIVE, D("300"), Broker.IBKR
        ))._short_allowed() is ALLOW_SHORT
