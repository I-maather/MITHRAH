"""
بوابات اعتماد الاستراتيجيات.

القاعدة الحاكمة: **نجاح الاتصال بالوسيط ليس دليلاً على أن الاستراتيجية تعمل.**
الاعتماد يتطلب أدلة إحصائية بعد كل التكاليف، وثباتاً عبر ظروف مختلفة،
ونجاح وضع الظل — ثم موافقة بشرية مكتوبة.

هذه الوحدة تُقيّم فقط. لا تملك مساراً لتغيير حالة استراتيجية:
الحالة مكتوبة في كود الاستراتيجية نفسها، وتغييرها يتطلب commit ومراجعة.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from ..money import D
from .backtest import BacktestResult, WalkForwardResult
from .shadow import ShadowSession

# --- عتبات القبول. أرقام محافظة عمداً على حساب بهذا الحجم. --------------
MIN_TRADES = 100
MIN_OUT_OF_SAMPLE_TRADES = 30
MIN_PROFIT_FACTOR = D("1.30")
MIN_EXPECTANCY_USD = D("0.01")
MAX_DRAWDOWN_USD = D("6.50")            # الحد التشغيلي نفسه
MIN_OUT_OF_SAMPLE_POSITIVE_FOLDS = 3
MIN_DEGRADATION_RATIO = D("0.40")
MAX_DEPENDENCE_ON_BEST_TRADE = D("0.30")
MIN_PARAMETER_POSITIVE_SHARE = D("0.70")
MIN_SHADOW_OBSERVATIONS = 20
MAX_SHADOW_SUBMITTED_ORDERS = 0


@dataclass(frozen=True)
class GateOutcome:
    name: str
    passed: bool
    detail_ar: str
    evidence: Optional[str] = None


@dataclass
class AdmissionReport:
    strategy: str
    gates: list[GateOutcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(g.passed for g in self.gates)

    @property
    def failures(self) -> list[GateOutcome]:
        return [g for g in self.gates if not g.passed]

    def summary(self) -> dict:
        return {
            "strategy": self.strategy,
            "passed": self.passed,
            "gates": [
                {"name": g.name, "passed": g.passed, "detail_ar": g.detail_ar, "evidence": g.evidence}
                for g in self.gates
            ],
            "verdict_ar": (
                "اجتازت كل البوابات الآلية — يبقى الاعتماد النهائي بموافقة المالكة المكتوبة."
                if self.passed
                else f"لم تجتز {len(self.failures)} بوابة — تبقى الحالة RESEARCH."
            ),
        }


def evaluate_admission(
    *,
    strategy_label: str,
    full_sample: Optional[BacktestResult] = None,
    walk_forward: Optional[WalkForwardResult] = None,
    parameter_positive_share: Optional[Decimal] = None,
    shadow: Optional[ShadowSession] = None,
    regimes: Optional[dict[str, BacktestResult]] = None,
) -> AdmissionReport:
    """
    يقيّم كل البوابات. غياب دليل = سقوط البوابة، لا تجاوزها.
    """
    report = AdmissionReport(strategy=strategy_label)
    add = report.gates.append

    # 1) حجم العيّنة
    if full_sample is None:
        add(GateOutcome("SAMPLE_SIZE", False, "لا يوجد اختبار تاريخي — لا دليل أصلاً."))
    else:
        ok = full_sample.trade_count >= MIN_TRADES
        add(
            GateOutcome(
                "SAMPLE_SIZE",
                ok,
                f"عدد الصفقات {full_sample.trade_count} مقابل حد أدنى {MIN_TRADES}.",
                full_sample.run_id,
            )
        )

        # 2) توقّع إيجابي بعد كل التكاليف
        expectancy = full_sample.expectancy
        ok = expectancy is not None and expectancy >= MIN_EXPECTANCY_USD
        add(
            GateOutcome(
                "POSITIVE_EXPECTANCY_AFTER_COSTS",
                ok,
                f"التوقّع لكل صفقة {expectancy if expectancy is not None else '—'} دولار "
                f"مقابل حد أدنى {MIN_EXPECTANCY_USD}.",
                full_sample.run_id,
            )
        )

        # 3) Profit Factor
        pf = full_sample.profit_factor
        ok = pf is not None and pf >= MIN_PROFIT_FACTOR
        add(
            GateOutcome(
                "PROFIT_FACTOR",
                ok,
                f"معامل الربح {pf if pf is not None else 'غير معرّف'} مقابل حد أدنى {MIN_PROFIT_FACTOR}.",
                full_sample.run_id,
            )
        )

        # 4) التراجع
        ok = full_sample.max_drawdown <= MAX_DRAWDOWN_USD
        add(
            GateOutcome(
                "MAX_DRAWDOWN",
                ok,
                f"أقصى تراجع {full_sample.max_drawdown:.2f} دولار مقابل حد {MAX_DRAWDOWN_USD}.",
                full_sample.run_id,
            )
        )

        # 5) عدم الاعتماد على صفقة استثنائية واحدة
        dependence = full_sample.dependence_on_best_trade
        ok = dependence is not None and dependence <= MAX_DEPENDENCE_ON_BEST_TRADE
        add(
            GateOutcome(
                "NO_SINGLE_TRADE_DEPENDENCE",
                ok,
                (
                    f"أفضل صفقة تمثّل {dependence:.0%} من الربح الصافي "
                    f"(الحد {MAX_DEPENDENCE_ON_BEST_TRADE:.0%})."
                    if dependence is not None
                    else "لا ربح صافٍ موجب — البوابة ساقطة."
                ),
                full_sample.run_id,
            )
        )

    # 6) خارج العيّنة
    if walk_forward is None:
        add(GateOutcome("OUT_OF_SAMPLE", False, "لم يُشغَّل Walk-forward — لا دليل خارج العيّنة."))
    else:
        oos_trades = sum(r.trade_count for r in walk_forward.out_of_sample)
        ok = (
            walk_forward.out_of_sample_net > 0
            and oos_trades >= MIN_OUT_OF_SAMPLE_TRADES
            and walk_forward.out_of_sample_positive_folds >= MIN_OUT_OF_SAMPLE_POSITIVE_FOLDS
        )
        add(
            GateOutcome(
                "OUT_OF_SAMPLE",
                ok,
                f"صافي خارج العيّنة {walk_forward.out_of_sample_net:.2f} دولار عبر "
                f"{oos_trades} صفقة و{walk_forward.out_of_sample_positive_folds} طيّة موجبة.",
            )
        )

        degradation = walk_forward.degradation_ratio
        ok = degradation is not None and degradation >= MIN_DEGRADATION_RATIO
        add(
            GateOutcome(
                "NO_OVERFITTING",
                ok,
                (
                    f"نسبة أداء خارج العيّنة إلى داخلها {degradation:.2f} "
                    f"مقابل حد أدنى {MIN_DEGRADATION_RATIO}."
                    if degradation is not None
                    else "لا يمكن قياس التدهور — الأداء داخل العيّنة غير موجب."
                ),
            )
        )

    # 7) استقرار المعاملات
    if parameter_positive_share is None:
        add(GateOutcome("PARAMETER_STABILITY", False, "لم يُجرَ تحليل استقرار المعاملات."))
    else:
        ok = parameter_positive_share >= MIN_PARAMETER_POSITIVE_SHARE
        add(
            GateOutcome(
                "PARAMETER_STABILITY",
                ok,
                f"{parameter_positive_share:.0%} من نقاط شبكة المعاملات موجبة "
                f"(الحد {MIN_PARAMETER_POSITIVE_SHARE:.0%}). قمّة معزولة = ملاءمة مفرطة.",
            )
        )

    # 8) ثبات عبر ظروف سوقية مختلفة
    if not regimes:
        add(GateOutcome("MULTIPLE_REGIMES", False, "لم تُختبر على أكثر من ظرف سوقي."))
    else:
        positive = sum(1 for r in regimes.values() if r.net_pnl > 0)
        ok = len(regimes) >= 3 and positive >= len(regimes) - 1
        add(
            GateOutcome(
                "MULTIPLE_REGIMES",
                ok,
                f"{positive} من {len(regimes)} ظرف سوقي بنتيجة موجبة.",
            )
        )

    # 9) وضع الظل
    if shadow is None:
        add(GateOutcome("SHADOW_MODE", False, "لم يُشغَّل وضع الظل على أسعار حيّة."))
    else:
        ok = (
            len(shadow.observations) >= MIN_SHADOW_OBSERVATIONS
            and shadow.submitted_orders <= MAX_SHADOW_SUBMITTED_ORDERS
        )
        add(
            GateOutcome(
                "SHADOW_MODE",
                ok,
                f"{len(shadow.observations)} ملاحظة و{shadow.submitted_orders} أمر مُرسَل "
                f"(يجب أن يكون صفراً).",
                shadow.session_id,
            )
        )

    # 10) الموافقة البشرية — لا تُمنح آلياً أبداً
    add(
        GateOutcome(
            "OWNER_WRITTEN_APPROVAL",
            False,
            "الموافقة المكتوبة من المالكة لا يمنحها الكود. تبقى هذه البوابة ساقطة "
            "حتى تُسجَّل موافقة في جدول approvals.",
        )
    )
    return report
