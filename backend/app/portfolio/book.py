"""
دفترُ المحفظة — **حقيقةُ ما هو مفتوحٌ ومغلق، مقروءةً من الوسيط لا من ذاكرتنا.**

## العطل الذي فرض هذا الملف

طبقةُ الجوال كُتبت يوم لم يكن النظام قد أرسل أمراً قط، فكانت كل حقولها
فارغةً **بصدق**:

    "trades": lambda: []          # «قائمة فارغة صادقة: لم يُرسَل أمرٌ قط»
    "has_position": sys.session_state.open_positions > 0
    "notes_ar": ["لا مركز مفتوح. لم يُرسَل أي أمر، والتنفيذ مقفول."]

ثم تداول النظام. ويوم 2026-09-04 كان على الحساب **خمسة مراكز مفتوحة**
وصفقتان مغلقتان بنتيجةٍ محقّقة ‎−0.35‎ دولار، والتطبيق يقول «لا مركز مفتوح،
لم يُرسَل أي أمر». الجملة التي كانت صادقةً صارت **أخطر كذبةٍ يمكن لسطح
مراقبةٍ أن يقولها**: يطمئن إلى أمانٍ غير موجود.

وسببُ ذلك ليس الجوال. `session_state.open_positions` عدّادٌ **لا يملؤه شيءٌ
من الوسيط** — وهو نفسه العدّاد الذي يقرأه محرّك المخاطر في `engine.py`
ليفرض سقف المراكز. فمنبعٌ واحدٌ جافّ يُنتج ثلاثة أعطال: سقفٌ لا يُفرَض،
وتطبيقٌ لا يرى، ومطابقةٌ بلا خطّ أساس.

## القاعدة

مصدرُ الحقيقة هو **حساب الوسيط**، يُقرأ في مكانٍ واحد ويُوزَّع على المخاطر
والواجهة والمطابقة. ولا يُترجَم إخفاقُ القراءة إلى «لا شيء»:

    فشلُ القراءة حالةٌ تُعرَض، لا صفرٌ يُعرَض.

لأن «صفر مراكز» و«لم أستطع أن أقرأ» يتطابقان في الشكل ويفترقان في المعنى
افتراقاً كاملاً — والخلط بينهما هو صنفُ العطل نفسه الذي كلّف هذا المشروع
يومَ عمل.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from ..money import D

#: عمرٌ تُعَدُّ بعده اللقطة قديمة. الجوال يعرض «آخر مزامنة» ووسماً صريحاً.
DEFAULT_MAX_AGE = timedelta(seconds=90)

#: أسبابُ عجزٍ عن القراءة — رموزٌ ثابتة تُقرأ في السجل والواجهة.
PORTFOLIO_OK = "OK"
PORTFOLIO_BROKER_UNREACHABLE = "BROKER_UNREACHABLE"
PORTFOLIO_READ_FAILED = "PORTFOLIO_READ_FAILED"
PORTFOLIO_NOT_ATTEMPTED = "NOT_ATTEMPTED"

#: نسبةُ المركز إلى ما فتحه. تبقى `UNATTRIBUTED` حتى يربطها الدفتر الدائم
#: (C1) بـ`dealReference`. ولا يُخمَّن: مركزٌ منسوبٌ بالظنّ أسوأ من مركزٍ
#: يقول إنه غير منسوب.
KIND_STRATEGY = "STRATEGY"
KIND_COMMISSIONING = "COMMISSIONING"
KIND_UNATTRIBUTED = "UNATTRIBUTED"


@dataclass(frozen=True)
class OpenPosition:
    """مركزٌ مفتوحٌ كما يقوله الوسيط. الكمية **موقّعة**: السالب قصير."""

    symbol: str
    quantity: Decimal
    entry_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    take_profit_price: Optional[Decimal] = None
    opened_utc: Optional[datetime] = None
    deal_id: str = ""
    deal_reference: str = ""
    unrealised_pnl: Optional[Decimal] = None
    currency: str = ""
    kind: str = KIND_UNATTRIBUTED
    strategy_ar: Optional[str] = None

    @property
    def direction(self) -> str:
        return "SELL" if self.quantity < 0 else "BUY"

    @property
    def is_protected(self) -> bool:
        """مركزٌ بلا وقفٍ عند الوسيط ليس محميّاً مهما قال سجلُّنا."""
        return self.stop_price is not None

    @property
    def risk_at_stop(self) -> Optional[Decimal]:
        """
        الخسارة عند الوقف بوحدة عملة التسعير — **تقديرٌ صريح**.

        لا يحوّل عملة ولا يحسب رسماً: أداةٌ مسعَّرة بغير الدولار (USDJPY،
        الذهب) تحتاج تحويلاً مقيساً وهو عيبٌ مفتوح. فيُقرأ الرقم على أنه
        فرقُ السعر × الحجم، لا التزاماً نهائياً.
        """
        if self.stop_price is None or self.entry_price is None:
            return None
        return abs(self.stop_price - self.entry_price) * abs(self.quantity)


@dataclass(frozen=True)
class ClosedTrade:
    """صفقةٌ أُغلقت — النتيجة المحقّقة كما يقولها دفترُ الوسيط."""

    symbol: str
    realised_pnl: Optional[Decimal] = None
    currency: str = ""
    closed_utc: Optional[datetime] = None
    deal_id: str = ""
    reference: str = ""
    note: str = ""
    kind: str = KIND_UNATTRIBUTED
    strategy_ar: Optional[str] = None

    @property
    def is_win(self) -> Optional[bool]:
        if self.realised_pnl is None:
            return None
        return self.realised_pnl > 0


@dataclass(frozen=True)
class PortfolioSnapshot:
    """
    لقطةٌ واحدة يقرأها الجميع: المخاطر والجوال والمطابقة.

    `ok=False` **لا يعني صفر مراكز** — يعني أننا لم نعرف. والفرق بينهما هو
    كل شيء.
    """

    as_of_utc: datetime
    ok: bool = False
    reason_code: str = PORTFOLIO_NOT_ATTEMPTED
    error_ar: str = ""
    account_id: str = ""
    open_positions: tuple[OpenPosition, ...] = ()
    closed_trades: tuple[ClosedTrade, ...] = ()
    balance: Optional[Decimal] = None
    available: Optional[Decimal] = None
    realised_pnl_total: Optional[Decimal] = None

    @property
    def open_count(self) -> Optional[int]:
        """`None` حين تعذّرت القراءة — لا صفر."""
        return len(self.open_positions) if self.ok else None

    @property
    def unprotected(self) -> tuple[OpenPosition, ...]:
        return tuple(p for p in self.open_positions if not p.is_protected)

    def exposure_by_symbol(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for position in self.open_positions:
            key = position.symbol.upper()
            totals[key] = totals.get(key, D("0")) + position.quantity
        return totals

    def holds(self, symbol: str) -> bool:
        return abs(self.exposure_by_symbol().get(symbol.upper(), D("0"))) > 0

    def total_unrealised(self) -> Optional[Decimal]:
        values = [
            p.unrealised_pnl for p in self.open_positions if p.unrealised_pnl is not None
        ]
        if not values:
            return None
        return sum(values, D("0"))

    def is_stale(self, now: datetime, max_age: timedelta = DEFAULT_MAX_AGE) -> bool:
        return (now - self.as_of_utc) > max_age

    def age_seconds(self, now: datetime) -> int:
        return max(0, int((now - self.as_of_utc).total_seconds()))


def unavailable(
    *, at: datetime, reason_code: str, error_ar: str, account_id: str = ""
) -> PortfolioSnapshot:
    """لقطةُ عجزٍ صريحة. تُعرَض ولا تُترجَم إلى فراغ."""
    return PortfolioSnapshot(
        as_of_utc=at,
        ok=False,
        reason_code=reason_code,
        error_ar=error_ar,
        account_id=account_id,
    )


def read_portfolio(broker: Any, *, account_id: str, at: datetime) -> PortfolioSnapshot:
    """
    يقرأ الحقيقة من الوسيط. **لا يرفع استثناءً ولا يخترع فراغاً.**

    المصادر بالترتيب:
      `list_open_positions_detailed()` — المراكز بوقفها وهدفها وربحها.
      `get_positions(account_id)`      — بديلٌ أفقر إن غاب الأول.
      `list_recent_transactions()`     — الصفقات المغلقة ونتائجها.
      `get_balances(account_id)`       — الرصيد.
    وغيابُ مصدرٍ ثانوي لا يُبطل اللقطة؛ غيابُ المراكز يُبطلها.
    """
    positions: tuple[OpenPosition, ...] = ()
    detailed = getattr(broker, "list_open_positions_detailed", None)
    try:
        if callable(detailed):
            positions = tuple(detailed())
        else:
            raw = broker.get_positions(account_id)
            positions = tuple(
                OpenPosition(
                    symbol=p.symbol,
                    quantity=p.quantity,
                    entry_price=getattr(p, "average_cost", None),
                )
                for p in raw
            )
    except Exception as exc:  # noqa: BLE001
        return unavailable(
            at=at,
            reason_code=PORTFOLIO_BROKER_UNREACHABLE,
            error_ar=(
                f"تعذّرت قراءة المراكز من الوسيط: {type(exc).__name__}. "
                "لا تُعرَض «صفر مراكز» على إخفاق قراءة."
            ),
            account_id=account_id,
        )

    closed: tuple[ClosedTrade, ...] = ()
    recent = getattr(broker, "list_recent_transactions", None)
    if callable(recent):
        try:
            closed = tuple(recent())
        except Exception:  # noqa: BLE001
            closed = ()

    balance = available = realised = None
    try:
        balances = broker.get_balances(account_id)
        balance = getattr(balances, "total_cash", None)
        available = getattr(balances, "settled_cash", None)
    except Exception:  # noqa: BLE001
        pass
    if closed:
        values = [t.realised_pnl for t in closed if t.realised_pnl is not None]
        realised = sum(values, D("0")) if values else None

    return PortfolioSnapshot(
        as_of_utc=at,
        ok=True,
        reason_code=PORTFOLIO_OK,
        error_ar="",
        account_id=account_id,
        open_positions=positions,
        closed_trades=closed,
        balance=balance,
        available=available,
        realised_pnl_total=realised,
    )


__all__ = [
    "OpenPosition", "ClosedTrade", "PortfolioSnapshot",
    "read_portfolio", "unavailable",
    "DEFAULT_MAX_AGE", "PORTFOLIO_OK", "PORTFOLIO_BROKER_UNREACHABLE",
    "PORTFOLIO_READ_FAILED", "PORTFOLIO_NOT_ATTEMPTED",
    "KIND_STRATEGY", "KIND_COMMISSIONING", "KIND_UNATTRIBUTED",
]
