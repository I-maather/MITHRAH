"""
INDEPENDENT TRADE REVIEW — مراجع مستقل حتمي.

يعيد حساب **كل** قيمة حرجة من اللقطة غير القابلة للتعديل، بمسار كود منفصل
عن التحليل الأساسي، ثم يقارن.

القاعدة التي تجعل هذا مفيداً بدل أن يكون شكلياً:

    **أي اختلاف مادي ⇒ `NO_TRADE — VERIFICATION_MISMATCH`.**
    **ولا يُحلّ الاختلاف باختيار الحساب الأفضل.**

اختيار الأفضل من حسابين متعارضين هو بالضبط كيف تتحول المراجعة إلى تبرير.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from ..contracts import Side, StopKind
from ..money import D
from .snapshot import UNKNOWN, MarketSnapshot, MarketStatus, _Unknown, is_unknown

#: التسامح النسبي المسموح بين الحسابين قبل اعتبار الفرق مادياً.
#: صغير عمداً: هذان حسابان لنفس المعادلة على نفس المدخلات، لا تقديران.
RELATIVE_TOLERANCE = D("0.005")     # 0.5%
ABSOLUTE_TOLERANCE_USD = D("0.005")


@dataclass(frozen=True)
class TradeProposal:
    """
    ما يقترحه التحليل الأساسي. المراجع لا يقرأ حسابات المُقترِح —
    يقرأ المدخلات الأولية فقط ثم يعيد الحساب.
    """

    snapshot_id: str
    instrument: str
    side: Side
    size: Decimal
    entry_reference: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    stop_kind: StopKind

    # القيم المحسوبة من التحليل الأساسي — تُقارَن ولا تُستعمل.
    claimed_spread: Decimal
    claimed_pip_value: Decimal
    claimed_notional: Decimal
    claimed_margin: Decimal
    claimed_price_risk: Decimal
    claimed_fees: Decimal
    claimed_slippage_reserve: Decimal
    claimed_all_in_risk: Decimal
    claimed_reward_risk: Decimal

    # حدود الملف المعلنة وقت الاقتراح
    profile_max_risk: Decimal
    profile_min_reward_risk: Decimal
    remaining_daily_budget: Decimal
    remaining_weekly_budget: Decimal


@dataclass(frozen=True)
class VerificationField:
    name: str
    name_ar: str
    primary: Any
    independent: Any
    matched: bool
    detail_ar: str

    def as_dict(self) -> dict:
        def fmt(v: Any) -> str:
            if is_unknown(v):
                return "UNKNOWN"
            if isinstance(v, Decimal):
                return f"{v:.6f}"
            return str(v)

        return {
            "name": self.name,
            "name_ar": self.name_ar,
            "primary": fmt(self.primary),
            "independent": fmt(self.independent),
            "matched": self.matched,
            "detail_ar": self.detail_ar,
        }


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    fields: tuple[VerificationField, ...]
    mismatches: tuple[str, ...]
    reason_ar: str

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "mismatches": list(self.mismatches),
            "reason_ar": self.reason_ar,
            "fields": [f.as_dict() for f in self.fields],
        }


def _close_enough(a: Any, b: Any) -> bool:
    if is_unknown(a) or is_unknown(b):
        return False
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        diff = abs(a - b)
        if diff <= ABSOLUTE_TOLERANCE_USD:
            return True
        scale = max(abs(a), abs(b))
        return scale > 0 and diff / scale <= RELATIVE_TOLERANCE
    return a == b


class IndependentTradeVerifier:
    """
    مسار حساب ثانٍ. يستقبل خصائص الأداة الاقتصادية من الوسيط واللقطة، ولا
    يستقبل أي قيمة محسوبة من المُقترِح إلا للمقارنة.
    """

    def __init__(
        self,
        *,
        lot_size: Decimal,
        pip_size: Decimal,
        margin_rate: Decimal,
        slippage_reserve_pips: Decimal,
        guaranteed_stop_premium: Decimal = D("0"),
        conversion_rate_cost: Decimal = D("0"),
    ) -> None:
        self.lot_size = D(lot_size)
        self.pip_size = D(pip_size)
        self.margin_rate = D(margin_rate)
        self.slippage_reserve_pips = D(slippage_reserve_pips)
        self.guaranteed_stop_premium = D(guaranteed_stop_premium)
        self.conversion_rate_cost = D(conversion_rate_cost)

    # -- إعادة الحساب، من الصفر -------------------------------------------

    def recompute(
        self, proposal: TradeProposal, snapshot: MarketSnapshot
    ) -> dict[str, Any]:
        bid = snapshot.bid.value if snapshot.bid.known else None
        ask = snapshot.ask.value if snapshot.ask.known else None
        if bid is None or ask is None:
            return {"spread": UNKNOWN, "pip_value": UNKNOWN, "notional": UNKNOWN,
                    "margin": UNKNOWN, "price_risk": UNKNOWN, "fees": UNKNOWN,
                    "slippage_reserve": UNKNOWN, "all_in_risk": UNKNOWN,
                    "reward_risk": UNKNOWN}

        spread = ask - bid
        pip_value = proposal.size * self.lot_size * self.pip_size
        notional = proposal.size * self.lot_size * proposal.entry_reference
        margin = notional * self.margin_rate

        stop_distance = abs(proposal.entry_reference - proposal.stop_price)
        tp_distance = abs(proposal.take_profit_price - proposal.entry_reference)
        price_risk = stop_distance * proposal.size * self.lot_size
        gross_reward = tp_distance * proposal.size * self.lot_size

        spread_cost = spread * proposal.size * self.lot_size
        gsl_premium = (
            self.guaranteed_stop_premium if proposal.stop_kind is StopKind.GUARANTEED else D("0")
        )
        conversion = self.conversion_rate_cost * notional
        fees = spread_cost + gsl_premium + conversion

        slippage_reserve = (
            D("0")
            if proposal.stop_kind is StopKind.GUARANTEED
            else self.slippage_reserve_pips * pip_value
        )

        all_in_risk = price_risk + fees + slippage_reserve
        recurring = spread_cost + gsl_premium + conversion
        net_reward = gross_reward - recurring
        reward_risk = (net_reward / all_in_risk) if all_in_risk > 0 else D("0")

        return {
            "spread": spread,
            "pip_value": pip_value,
            "notional": notional,
            "margin": margin,
            "price_risk": price_risk,
            "fees": fees,
            "slippage_reserve": slippage_reserve,
            "all_in_risk": all_in_risk,
            "reward_risk": reward_risk,
        }

    # -- المقارنة ----------------------------------------------------------

    def verify(
        self,
        proposal: TradeProposal,
        snapshot: MarketSnapshot,
        *,
        now: datetime,
        in_blackout: bool,
        max_quote_age_seconds: int = 60,
    ) -> VerificationResult:
        fields: list[VerificationField] = []
        mismatches: list[str] = []

        def compare(name: str, name_ar: str, primary: Any, independent: Any) -> None:
            ok = _close_enough(primary, independent)
            fields.append(
                VerificationField(
                    name=name,
                    name_ar=name_ar,
                    primary=primary,
                    independent=independent,
                    matched=ok,
                    detail_ar=("مطابق." if ok else "اختلاف مادي — لا يُرجَّح أحد الحسابين."),
                )
            )
            if not ok:
                mismatches.append(name)

        # 0) اللقطة نفسها
        if proposal.snapshot_id != snapshot.snapshot_id:
            return VerificationResult(
                passed=False,
                fields=(),
                mismatches=("snapshot_id",),
                reason_ar=(
                    "المراجع واللقطة غير متطابقين — التحقق على لقطة أخرى بلا معنى. "
                    "NO_TRADE — VERIFICATION_MISMATCH."
                ),
            )

        # 1) الأداة والاتجاه
        compare("instrument", "الأداة", proposal.instrument, snapshot.instrument)
        fields.append(VerificationField(
            "direction", "الاتجاه", proposal.side.value, proposal.side.value, True,
            "الاتجاه كما اقتُرح.",
        ))

        # 2) صحة الوقف والهدف اتجاهياً
        if proposal.side is Side.BUY:
            stop_ok = proposal.stop_price < proposal.entry_reference < proposal.take_profit_price
        else:
            stop_ok = proposal.take_profit_price < proposal.entry_reference < proposal.stop_price
        fields.append(VerificationField(
            "stop_orientation", "اتجاه الوقف والهدف", stop_ok, True, stop_ok,
            "الوقف والهدف على الجانبين الصحيحين." if stop_ok
            else "الوقف أو الهدف على الجانب الخاطئ من سعر الدخول.",
        ))
        if not stop_ok:
            mismatches.append("stop_orientation")

        # 3) الكمية موجبة
        size_ok = proposal.size > 0
        fields.append(VerificationField(
            "quantity", "الكمية", proposal.size, proposal.size, size_ok,
            "كمية صالحة." if size_ok else "كمية غير صالحة.",
        ))
        if not size_ok:
            mismatches.append("quantity")

        # 4) إعادة الحساب الكاملة
        r = self.recompute(proposal, snapshot)
        compare("spread", "السبريد", proposal.claimed_spread, r["spread"])
        compare("pip_value", "قيمة النقطة", proposal.claimed_pip_value, r["pip_value"])
        compare("notional", "قيمة التعرّض", proposal.claimed_notional, r["notional"])
        compare("margin", "الهامش المحجوز", proposal.claimed_margin, r["margin"])
        compare("price_risk", "خسارة السعر", proposal.claimed_price_risk, r["price_risk"])
        compare("fees", "الرسوم", proposal.claimed_fees, r["fees"])
        compare(
            "slippage_reserve", "احتياطي الانزلاق",
            proposal.claimed_slippage_reserve, r["slippage_reserve"],
        )
        compare("all_in_risk", "الخسارة الكلية", proposal.claimed_all_in_risk, r["all_in_risk"])
        compare("reward_risk", "العائد/المخاطرة", proposal.claimed_reward_risk, r["reward_risk"])

        # 5) حدود الملف — يُعاد فحصها على القيمة المستقلة، لا المُدَّعاة
        indep_risk = r["all_in_risk"]
        within_profile = not is_unknown(indep_risk) and indep_risk <= proposal.profile_max_risk
        fields.append(VerificationField(
            "profile_risk_limit", "حد مخاطرة الملف", proposal.profile_max_risk, indep_risk,
            within_profile,
            "الخسارة المستقلة ضمن حد الملف." if within_profile
            else "الخسارة المحسوبة استقلالاً تتجاوز حد الملف.",
        ))
        if not within_profile:
            mismatches.append("profile_risk_limit")

        indep_rr = r["reward_risk"]
        rr_ok = not is_unknown(indep_rr) and indep_rr >= proposal.profile_min_reward_risk
        fields.append(VerificationField(
            "profile_min_rr", "أدنى R:R للملف", proposal.profile_min_reward_risk, indep_rr,
            rr_ok,
            "R:R المستقل يحقق متطلب الملف." if rr_ok else "R:R المستقل دون متطلب الملف.",
        ))
        if not rr_ok:
            mismatches.append("profile_min_rr")

        # 6) الحدود اليومية والأسبوعية
        daily_ok = not is_unknown(indep_risk) and indep_risk <= proposal.remaining_daily_budget
        fields.append(VerificationField(
            "daily_budget", "المتبقي اليومي", proposal.remaining_daily_budget, indep_risk,
            daily_ok, "ضمن المتبقي اليومي." if daily_ok else "يتجاوز المتبقي اليومي.",
        ))
        if not daily_ok:
            mismatches.append("daily_budget")

        weekly_ok = not is_unknown(indep_risk) and indep_risk <= proposal.remaining_weekly_budget
        fields.append(VerificationField(
            "weekly_budget", "المتبقي الأسبوعي", proposal.remaining_weekly_budget, indep_risk,
            weekly_ok, "ضمن المتبقي الأسبوعي." if weekly_ok else "يتجاوز المتبقي الأسبوعي.",
        ))
        if not weekly_ok:
            mismatches.append("weekly_budget")

        # 7) الحجب الاقتصادي
        fields.append(VerificationField(
            "economic_blackout", "الحجب الاقتصادي", in_blackout, False, not in_blackout,
            "لا حجب." if not in_blackout else "داخل نافذة حجب.",
        ))
        if in_blackout:
            mismatches.append("economic_blackout")

        # 8) حالة السوق
        status_ok = (
            snapshot.market_status.known
            and snapshot.market_status.value is MarketStatus.OPEN
        )
        fields.append(VerificationField(
            "market_status", "حالة السوق",
            snapshot.market_status.value, MarketStatus.OPEN, status_ok,
            "السوق مفتوح." if status_ok else "السوق ليس مفتوحاً أو حالته غير معلومة.",
        ))
        if not status_ok:
            mismatches.append("market_status")

        # 9) قِدَم البيانات
        age = snapshot.bid.age_seconds(now)
        stale = age is None or age > max_quote_age_seconds
        fields.append(VerificationField(
            "data_freshness", "طزاجة البيانات",
            f"{age:.0f}s" if age is not None else "UNKNOWN",
            f"≤{max_quote_age_seconds}s", not stale,
            "السعر حديث." if not stale else "السعر قديم أو بلا طابع زمني.",
        ))
        if stale:
            mismatches.append("data_freshness")

        passed = not mismatches
        return VerificationResult(
            passed=passed,
            fields=tuple(fields),
            mismatches=tuple(mismatches),
            reason_ar=(
                "المراجع المستقل يطابق التحليل الأساسي في كل قيمة حرجة."
                if passed
                else (
                    "NO_TRADE — VERIFICATION_MISMATCH. اختلاف في: "
                    + "، ".join(mismatches)
                    + ". **لا يُحلّ الاختلاف باختيار الحساب الأفضل.**"
                )
            ),
        )


__all__ = [
    "TradeProposal",
    "VerificationField",
    "VerificationResult",
    "IndependentTradeVerifier",
    "RELATIVE_TOLERANCE",
    "ABSOLUTE_TOLERANCE_USD",
]
