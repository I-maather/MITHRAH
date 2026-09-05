"""
محرّكُ إدارة المراكز — يقرأ الحقيقة، ويقترح، ويحرس، ثمّ ينفّذ.

## الترتيب، وهو الأمان كلّه

    الوسيط → الدفتر → المطابقة → السياسة → الحارس → التنفيذ → المطابقة ثانيةً

لا يُعدَّل مركزٌ لم تُطابَق حقيقتُه لحظتَها. تعديلُ مركزٍ بهويّةٍ قديمة أو
كميةٍ قديمة أسوأ من عدم التعديل: قد يُوسّع وقفاً على مركزٍ صار أكبر.

## الحرّاس الثلاثة

١. **لا يُوسَّع وقفٌ أبداً.** الوقف يقترب من السعر أو يبقى. توسيعُه زيادةُ
   خسارةٍ محتملة، وهي القرار الوحيد الذي لا يجوز أن يتّخذه محرّكٌ آلي.
٢. **المخاطرة بعد الإدارة ≤ المخاطرة المعتمدة عند الدخول.** الإدارة تقلّل أو
   تُبقي، ولا تزيد.
٣. **العمل مُتماثِل.** قيمةٌ مطابقةٌ لما عند الوسيط لا تُرسَل ثانيةً؛ وإعادة
   تشغيلٍ في منتصف الدورة لا تُنتج أمرين.

## والإيقاف

الإدارة تعمل والإيقاف قائم. الإيقاف يمنع **فتح** المراكز؛ ومركزٌ مفتوحٌ لا
يُدار ليس موقوفاً — هو متروك.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from ..money import D
from .policy import Capability, ManagementPolicy, PolicyRegistry, default_policy

#: فرقٌ سعريّ أصغر منه يُعدّ «نفس القيمة» — فلا يُرسل أمرٌ بلا أثر.
IDEMPOTENCE_TOLERANCE = Decimal("0.0000001")

ACTION_MOVE_STOP = "MOVE_STOP"
ACTION_CLOSE = "CLOSE"
ACTION_PARTIAL_CLOSE = "PARTIAL_CLOSE"

SKIP_NOT_RECONCILED = "NOT_RECONCILED"
SKIP_UNATTRIBUTED = "UNATTRIBUTED"
SKIP_FIXED_ONLY = "FIXED_ONLY"
SKIP_NO_CHANGE = "NO_CHANGE"
SKIP_NO_STOP = "NO_STOP"


@dataclass(frozen=True)
class ManagementAction:
    """
    فعلٌ مقترَح على مركزٍ واحد — **بالقيمتين القديمة والجديدة**.

    السجلّ بلا القيمة القديمة لا يُراجَع: لا يُعرَف هل ضاق الوقف أم اتّسع.
    """

    deal_id: str
    symbol: str
    kind: str
    reason_ar: str
    policy_version: str
    strategy_name: str = ""
    strategy_version: str = ""
    old_value: Optional[Decimal] = None
    new_value: Optional[Decimal] = None
    quantity: Optional[Decimal] = None
    at_utc: Optional[datetime] = None

    def as_dict(self) -> dict:
        return {
            "deal_id": self.deal_id,
            "symbol": self.symbol,
            "kind": self.kind,
            "reason_ar": self.reason_ar,
            "policy_version": self.policy_version,
            "strategy": self.strategy_name,
            "strategy_version": self.strategy_version,
            "old_value": str(self.old_value) if self.old_value is not None else None,
            "new_value": str(self.new_value) if self.new_value is not None else None,
            "at_utc": self.at_utc.isoformat() if self.at_utc else None,
        }


@dataclass(frozen=True)
class Skipped:
    deal_id: str
    symbol: str
    code: str
    reason_ar: str


@dataclass(frozen=True)
class ManagementPlan:
    at_utc: datetime
    actions: tuple[ManagementAction, ...] = ()
    skipped: tuple[Skipped, ...] = ()
    notes_ar: tuple[str, ...] = ()

    @property
    def touched(self) -> int:
        return len(self.actions)

    def as_dict(self) -> dict:
        return {
            "at_utc": self.at_utc.isoformat(),
            "actions": [a.as_dict() for a in self.actions],
            "skipped": [
                {"deal_id": s.deal_id, "symbol": s.symbol, "code": s.code, "reason_ar": s.reason_ar}
                for s in self.skipped
            ],
            "notes_ar": list(self.notes_ar),
        }


def _is_long(quantity: Decimal) -> bool:
    return quantity > 0


def tightens(*, is_long: bool, entry: Decimal, old_stop: Decimal, new_stop: Decimal) -> bool:
    """
    هل الوقف الجديد **أقرب إلى السعر** من القديم؟

    للمركز الطويل: الوقف تحت الدخول، فالاقتراب ارتفاع.
    وللقصير: فوقه، فالاقتراب انخفاض.
    """
    return new_stop > old_stop if is_long else new_stop < old_stop


def risk_at(*, entry: Decimal, stop: Decimal, quantity: Decimal) -> Decimal:
    """مخاطرةٌ تقريبيةٌ بعملة الأداة — بلا تحويل، وتُقارَن بمثلها فقط."""
    return abs(stop - entry) * abs(quantity)


@dataclass
class PositionManager:
    """
    يقترح الأفعال. **لا يرسل شيئاً بنفسه** — الإرسال خطوةٌ منفصلة تُدقَّق.
    """

    registry: PolicyRegistry

    def plan(
        self,
        *,
        broker_positions: Sequence,
        book_rows: Sequence,
        now: datetime,
        atr_by_symbol: Optional[dict[str, Decimal]] = None,
    ) -> ManagementPlan:
        actions: list[ManagementAction] = []
        skipped: list[Skipped] = []
        notes: list[str] = []

        by_deal = {
            (p.deal_id or "").strip(): p for p in broker_positions if (p.deal_id or "").strip()
        }

        for row in book_rows:
            deal_id = row.broker_deal_id
            live = by_deal.get(deal_id)

            # ١ · المطابقة أوّلاً — لا فعلَ على حقيقةٍ غير مؤكَّدة.
            if live is None:
                skipped.append(Skipped(
                    deal_id, row.symbol, SKIP_NOT_RECONCILED,
                    "المركز في الدفتر ولا يظهر عند الوسيط الآن — لا يُعدَّل.",
                ))
                continue
            if live.quantity != row.quantity:
                skipped.append(Skipped(
                    deal_id, row.symbol, SKIP_NOT_RECONCILED,
                    f"كميةُ الوسيط {live.quantity} تخالف الدفتر {row.quantity} — لا يُعدَّل.",
                ))
                continue

            # ٢ · لا نسبةَ لا سياسة. مركزٌ لا يُعرَف أيُّ قرارٍ فتحه لا تُطبَّق
            #     عليه قواعدُ استراتيجيةٍ لم تفتحه.
            if row.attribution != "LINKED" or not row.strategy_name:
                skipped.append(Skipped(
                    deal_id, row.symbol, SKIP_UNATTRIBUTED,
                    "مركزٌ بلا نسبةٍ إلى قرار — يبقى على خروجه الثابت ويُراقَب.",
                ))
                continue

            policy = self.registry.for_strategy(row.strategy_name, row.strategy_version)
            if policy.is_fixed_only:
                skipped.append(Skipped(
                    deal_id, row.symbol, SKIP_FIXED_ONLY,
                    f"سياسة {policy.policy_version}: خروجٌ ثابتٌ بلا تحريك.",
                ))
                continue

            action = self._evaluate(
                row=row, live=live, policy=policy, now=now,
                atr=(atr_by_symbol or {}).get(row.symbol),
            )
            if isinstance(action, Skipped):
                skipped.append(action)
            elif action is not None:
                actions.append(action)

        # **الملاحظة كانت تدّعي المطابقة لأنّ الأفعال صفر.** وهذان أمران
        # مختلفان تماماً: «لا حاجةَ إلى فعل» ليس «كلُّ شيءٍ مقروءٌ ومطابَق».
        # فمركزٌ لم يظهر عند الوسيط يُتخطّى بلا فعل، فتقول الشاشة إنّه
        # مطابَق — وهي أسوأ رسالةٍ ممكنة: طمأنينةٌ في موضع الجهل.
        if not book_rows:
            notes.append("لا مركزَ مفتوحاً في الدفتر.")
        elif not actions:
            unmatched = [s for s in skipped if s.code == SKIP_NOT_RECONCILED]
            if len(unmatched) == len(book_rows):
                notes.append(
                    f"لا فعل — ولا واحدٌ من {len(book_rows)} مركزاً ظهر عند "
                    "الوسيط في هذه الدورة. لا يُقال إنّها مطابَقة."
                )
            elif unmatched:
                notes.append(
                    f"لا فعل — و{len(unmatched)} من {len(book_rows)} مركزاً "
                    "لم يظهر عند الوسيط في هذه الدورة."
                )
            else:
                notes.append(
                    f"لا فعلَ هذه الدورة — و{len(book_rows)} مركزاً قُرئت "
                    "وطُوبقت، وهي على خروجها الثابت المعتمد."
                )

        return ManagementPlan(
            at_utc=now, actions=tuple(actions), skipped=tuple(skipped), notes_ar=tuple(notes)
        )

    # -- التقييم ---------------------------------------------------------------

    def _evaluate(self, *, row, live, policy: ManagementPolicy, now, atr):
        entry = row.entry_price
        stop = live.stop_price
        if entry is None or stop is None:
            return Skipped(
                row.broker_deal_id, row.symbol, SKIP_NO_STOP,
                "لا وقفَ عند الوسيط أو لا سعرَ دخولٍ معروف — لا يُحسب R.",
            )

        is_long = _is_long(row.quantity)
        r_distance = abs(entry - stop)
        if r_distance == 0:
            return Skipped(
                row.broker_deal_id, row.symbol, SKIP_NO_STOP,
                "الوقف عند الدخول تماماً — لا وحدةَ مخاطرةٍ تُقاس بها.",
            )

        price = getattr(live, "market_price", None) or getattr(live, "entry_price", None)
        proposed: Optional[Decimal] = None
        reason = ""

        # التعادل قبل المطاردة: الأضيق يفوز، والحارس يمنع التوسيع على أي حال.
        if policy.has(Capability.BREAK_EVEN) and policy.break_even_after_r and price is not None:
            gained = (price - entry) if is_long else (entry - price)
            if gained >= policy.break_even_after_r * r_distance:
                proposed = entry
                reason = (
                    f"ربحٌ بلغ {policy.break_even_after_r}R — الوقف إلى نقطة الدخول "
                    f"({policy.policy_version})."
                )

        if policy.has(Capability.TRAILING_STOP) and policy.trailing_atr_multiple and atr and price:
            trail = (
                price - policy.trailing_atr_multiple * atr
                if is_long
                else price + policy.trailing_atr_multiple * atr
            )
            if proposed is None or tightens(
                is_long=is_long, entry=entry, old_stop=proposed, new_stop=trail
            ):
                proposed = trail
                reason = (
                    f"مطاردةٌ بـ{policy.trailing_atr_multiple}×ATR ({policy.policy_version})."
                )

        if proposed is None:
            return Skipped(
                row.broker_deal_id, row.symbol, SKIP_NO_CHANGE,
                "لم يتحقّق شرطُ أيّ قدرةٍ مفعّلة.",
            )

        return self._guard(
            row=row, policy=policy, entry=entry, old_stop=stop,
            new_stop=proposed, reason=reason, is_long=is_long, now=now,
        )

    # -- الحرّاس ---------------------------------------------------------------

    def _guard(self, *, row, policy, entry, old_stop, new_stop, reason, is_long, now):
        if abs(new_stop - old_stop) <= IDEMPOTENCE_TOLERANCE:
            return Skipped(
                row.broker_deal_id, row.symbol, SKIP_NO_CHANGE,
                "القيمةُ المقترحة هي القائمة عند الوسيط — لا يُرسَل أمرٌ بلا أثر.",
            )

        if not tightens(is_long=is_long, entry=entry, old_stop=old_stop, new_stop=new_stop):
            # **الحارس الأوّل.** توسيعُ الوقف زيادةُ خسارةٍ محتملة، وهو القرار
            # الوحيد الذي لا يجوز أن يتّخذه محرّكٌ آلي. يُرفَض ويُسجَّل.
            return Skipped(
                row.broker_deal_id, row.symbol, SKIP_NO_CHANGE,
                f"الوقف المقترح {new_stop} أبعدُ من القائم {old_stop} — "
                "لا يُوسَّع وقفٌ أبداً.",
            )

        before = risk_at(entry=entry, stop=old_stop, quantity=row.quantity)
        after = risk_at(entry=entry, stop=new_stop, quantity=row.quantity)
        if after > before:
            return Skipped(
                row.broker_deal_id, row.symbol, SKIP_NO_CHANGE,
                f"المخاطرة بعد الإدارة {after} تتجاوز القائمة {before} — تُرفَض.",
            )

        return ManagementAction(
            deal_id=row.broker_deal_id,
            symbol=row.symbol,
            kind=ACTION_MOVE_STOP,
            reason_ar=reason,
            policy_version=policy.policy_version,
            strategy_name=row.strategy_name,
            strategy_version=row.strategy_version,
            old_value=old_stop,
            new_value=new_stop,
            quantity=row.quantity,
            at_utc=now,
        )
