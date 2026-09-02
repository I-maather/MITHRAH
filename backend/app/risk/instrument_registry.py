"""
سجلّ اقتصاديات الأدوات — **المقيس وحده يُنفَّذ عليه.**

## لماذا وُجد

كان في المشروع نموذج تكلفةٍ واحد (`PROVISIONAL_EURUSD`)، وقيمُه **من صفحة
كابيتال العامة لا من حساب المالكة** — موسومةٌ بذلك صراحةً
(`PROVISIONAL_PUBLIC_SITE`). وقائمة التنفيذ مثبَّتة على `EURUSD` وحدها،
بينما النظام يمسح أربع أدوات. فثلاثٌ من أربع تُمسح ولا يمكن أن تُنفَّذ،
والرابعة تُنفَّذ باقتصادياتٍ **مفترضة**.

وأثرُ ذلك على المالكة مباشر: معدّل الإشارة يقتصر على أداة واحدة، فيصير
انتظار الصفقة أسابيع بدل أيام.

## القاعدة

أداةٌ تصير قابلة للتنفيذ **حين تُقاس اقتصادياتها من الوسيط نفسه**، لا حين
تُضاف إلى قائمة. والقياس يأتي من `scripts/discover_instrument_economics.py`
ويُكتب في ملفٍ يحمل تاريخه ومصدره.

⇒ وهذا **يضيّق ويوسّع معاً**: يمنع `EURUSD` نفسها حتى تُقاس، ويسمح بالثلاث
الباقيات متى قِيست. مبدأٌ واحد في الاتجاهين، لا تسهيلٌ في اتجاه.

## وما لا يفعله

لا يخترع قيمة عند غياب القياس. غيابُ الملف يعني **لا أداة قابلة للتنفيذ**،
ويُقال ذلك بنصّه مع الأمر الذي يصلحه — لا سقوطٌ إلى افتراضٍ صامت.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping, Optional

from ..money import D
from .capital_costs import (
    CapitalComCostModel,
    CfdCostAssumptions,
    InstrumentEconomics,
    ValueProvenance,
)

#: مكان القياس — تحت `data/` مع بقيّة ما يُكتب في التشغيل.
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "instrument-economics.json"


def _dec(value: object) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    return D(str(value))


@dataclass(frozen=True)
class MeasuredInstrument:
    economics: InstrumentEconomics
    assumptions: CfdCostAssumptions
    measured_at_utc: str
    #: كم مرّةً رُصد السبريد. **رصدةٌ واحدة ليست قياساً** — يُذكر العدد ليُقرأ.
    spread_samples: int

    @property
    def executable(self) -> bool:
        """
        ثلاثة شروط: اقتصادياتٌ من الوسيط، وأدنى مسافة وقفٍ معلومة، وسبريدٌ
        مرصود.

        والثاني ليس تفصيلاً: بلا حدٍّ معلوم يُرسَل الأمر ليُرفَض عند الوسيط
        — وقد كلّفنا ذلك ليلةً كاملة يوم 09-01.
        """
        return (
            self.economics.provenance is ValueProvenance.BROKER_DISCOVERY
            and self.economics.min_stop_distance is not None
            and self.spread_samples > 0
            # **والسبريد نفسه مقيسٌ لا موروث.** كان الشرط عدد الرصدات
            # وحده؛ وصفٌّ برصداتٍ بلا `spread_price` يرث احتياطي
            # `CfdCostAssumptions.default()` — و`0.00006` سبريدُ **اليورو**
            # (0.6 نقطة). على الذهب سبريدُه المقيس 0.50 دولار: الفارق نحو
            # ثمانية آلاف ضعف، ويدخل حساب التعادل ونسبة التكلفة بلا أن
            # يُقال إنه موروث.
            and self.assumptions.spread_provenance is ValueProvenance.BROKER_DISCOVERY
        )


class InstrumentRegistry:
    """يقرأ القياس من القرص ويقدّم نموذج تكلفةٍ لكل أداةٍ مقيسة."""

    def __init__(self, measured: Mapping[str, MeasuredInstrument]) -> None:
        self._measured = dict(measured)

    @classmethod
    def empty(cls) -> "InstrumentRegistry":
        return cls({})

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "InstrumentRegistry":
        target = path or DEFAULT_PATH
        if not target.exists():
            return cls.empty()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # ملفٌ تالف ليس قياساً. لا يُخمَّن منه شيء.
            return cls.empty()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Mapping) -> "InstrumentRegistry":
        out: dict[str, MeasuredInstrument] = {}
        for epic, row in (raw.get("instruments") or {}).items():
            try:
                economics = InstrumentEconomics(
                    epic=str(row["epic"]),
                    pip_size=D(str(row["pip_size"])),
                    lot_size=D(str(row["lot_size"])),
                    min_deal_size=D(str(row["min_deal_size"])),
                    size_increment=D(str(row["size_increment"])),
                    margin_factor=D(str(row["margin_factor"])),
                    margin_factor_unit=str(row["margin_factor_unit"]),
                    min_stop_distance=_dec(row.get("min_stop_distance")),
                    min_guaranteed_stop_distance=_dec(row.get("min_guaranteed_stop_distance")),
                    guaranteed_stop_available=bool(row.get("guaranteed_stop_available", False)),
                    # **لا تُملأ عملةُ التسعير صامتة.** كان `or "USD"` يمنح
                    # صفّاً بلا عملةٍ عملةَ الحساب بمصدر `BROKER_DISCOVERY`
                    # — أي أنه يؤكّد ما لم يقرأه. و`None` تُمرَّر كما هي،
                    # وطبقةُ الأهلية تقول صراحةً إنها مفترضة من قائمتنا.
                    quote_currency=(
                        str(row["quote_currency"])
                        if row.get("quote_currency")
                        else None
                    ),
                    overnight_fee_rate_daily=_dec(row.get("overnight_fee_rate_daily")),
                    provenance=ValueProvenance(row.get("provenance", "UNKNOWN")),
                )
                spread = _dec(row.get("spread_price"))
                base = CfdCostAssumptions.default()
                assumptions = CfdCostAssumptions(
                    spread_price=spread if spread is not None else base.spread_price,
                    slippage_reserve_pips=base.slippage_reserve_pips,
                    guaranteed_stop_premium_pips=base.guaranteed_stop_premium_pips,
                    currency_conversion_pct=base.currency_conversion_pct,
                    nights_held=0,
                    spread_provenance=(
                        ValueProvenance.BROKER_DISCOVERY
                        if spread is not None
                        else base.spread_provenance
                    ),
                )
            except (KeyError, ValueError, TypeError, ArithmeticError):
                # صفٌّ ناقص يُتجاهَل ولا يُكمَّل بالتخمين.
                continue
            out[str(epic).upper()] = MeasuredInstrument(
                economics=economics,
                assumptions=assumptions,
                measured_at_utc=str(row.get("measured_at_utc") or ""),
                spread_samples=int(row.get("spread_samples") or 0),
            )
        return cls(out)

    def get(self, epic: str) -> Optional[MeasuredInstrument]:
        return self._measured.get(epic.upper())

    def cost_model_for(self, epic: str) -> Optional[CapitalComCostModel]:
        row = self.get(epic)
        if row is None:
            return None
        return CapitalComCostModel(row.economics, row.assumptions)

    def executable_epics(self, within: Optional[Iterable[str]] = None) -> frozenset[str]:
        """
        الأدوات القابلة للتنفيذ — المقيسة وحدها، ومقصورةً على `within` إن
        مُرِّرت. **التوسيع لا يتجاوز ما سُمح باكتشافه**: قياسُ أداةٍ خارج
        قائمة الاكتشاف لا يجعلها قابلة للتنفيذ.
        """
        names = list(self._measured)
        if within is not None:
            permitted = {e.upper() for e in within}
            names = [e for e in names if e in permitted]
        return frozenset(e for e in names if self._measured[e].executable)

    def why_not(self, epic: str) -> str:
        """سببٌ يُقرأ. «غير مسموح» وحدها ترسل المالكة تبحث."""
        row = self.get(epic)
        if row is None:
            return (
                f"{epic}: لا قياس لاقتصادياتها. شغّلي "
                "scripts/discover_instrument_economics.py على الخادم."
            )
        if row.economics.provenance is not ValueProvenance.BROKER_DISCOVERY:
            return f"{epic}: اقتصادياتها مفترضة لا مقيسة ({row.economics.provenance.value})."
        if row.economics.min_stop_distance is None:
            return f"{epic}: أدنى مسافة وقف غير معلومة — الأمر سيُرفض عند الوسيط."
        if row.spread_samples <= 0:
            return f"{epic}: لم يُرصد سبريد."
        if row.assumptions.spread_provenance is not ValueProvenance.BROKER_DISCOVERY:
            return (
                f"{epic}: السبريد موروثٌ من افتراضٍ لا مقيسٌ من الوسيط "
                f"({row.assumptions.spread_provenance.value}) — والافتراض سبريدُ اليورو."
            )
        return f"{epic}: قابلة للتنفيذ."

    def measured_epics(self) -> tuple[str, ...]:
        return tuple(sorted(self._measured))

    def __len__(self) -> int:
        return len(self._measured)


__all__ = ["InstrumentRegistry", "MeasuredInstrument", "DEFAULT_PATH"]
