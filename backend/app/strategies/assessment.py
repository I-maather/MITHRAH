"""
تشخيص الاستراتيجية — **لماذا لم تُشِر، بالأرقام.**

## العطل الذي فرض هذا الملف

كل رفضٍ في الاستراتيجيات كان `return None` مجرّداً. فالخط يقول
`NO_SETUP` — «لا توجد فرصة مطابقة» — وهي الجملة نفسها سواء كان ADX عند
24.9 (على بُعد شعرة من الدخول) أو عند 8 (سوقٌ ميّت لا تناسبه الاستراتيجية
أصلاً).

⇒ تنظر المالكة إلى الجملة نفسها أياماً بلا أن تعرف: أالنظام على وشك
الدخول، أم أن الاستراتيجية لا تناسب هذا السوق بحال؟

**وهذا بالضبط ما يُفترض أن يميّز هذا المنتج**: بحث المنافسين فحص 69 لقطة
من 18 تطبيقاً ولم يجد شاشةً واحدة تقول «لماذا لم أتداول». وشاشتنا تقولها
— ثم تصمت عند أهمّ سؤال فيها.

## القاعدة

كل شرطٍ يُفحَص يُسجَّل: اسمه، وهل مرّ، **وبأي رقم**. والرقم هو الفرق بين
معلومةٍ وجملةٍ مطمئنة: «ADX 18.3 دون 25» تُقرأ، و«لا فرصة» لا تُقرأ.

## وما لا يفعله

لا يغيّر قراراً. `evaluate` تبقى كما هي حرفاً — تُبنى فوق `assess` وتعيد
الإشارة وحدها. فالتشخيص **يُضاف ولا يَحكم**، ولا اختبارٌ قائم يتغيّر معناه.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from ..contracts import Signal


@dataclass(frozen=True)
class Check:
    """شرطٌ واحد: اسمه، وهل مرّ، والرقم الذي حكم."""

    name_ar: str
    passed: bool
    detail_ar: str

    def as_dict(self) -> dict:
        return {"name_ar": self.name_ar, "passed": self.passed, "detail_ar": self.detail_ar}


@dataclass(frozen=True)
class Assessment:
    """
    نتيجة تقييمٍ واحد: الإشارة إن وُجدت، وسلسلة ما فُحص حتى التوقّف.

    والسلسلة **تتوقّف عند أول شرطٍ ساقط** عمداً: عرضُ بقيّة الشروط بعد سقوط
    الظرف يوحي بأنها فُحصت وهي لم تُفحَص — وهو ادّعاءٌ عن عملٍ لم يقع.
    """

    signal: Optional[Signal]
    checks: tuple[Check, ...] = ()

    @property
    def blocking(self) -> Optional[Check]:
        """الشرط الذي أوقف التقييم — أو `None` إن مرّت كلها."""
        for check in self.checks:
            if not check.passed:
                return check
        return None

    @property
    def summary_ar(self) -> str:
        if self.signal is not None:
            return "كل الشروط تحقّقت — أُنتجت إشارة."
        blocker = self.blocking
        if blocker is None:
            return "لم تُفحَص شروط — بيانات غير كافية."
        return f"{blocker.name_ar}: {blocker.detail_ar}"

    def as_dict(self) -> dict:
        return {
            "has_signal": self.signal is not None,
            "summary_ar": self.summary_ar,
            "checks": [c.as_dict() for c in self.checks],
        }


class Recorder:
    """
    يجمع الشروط بالترتيب. أداةُ كتابةٍ لا منطق: **لا تقرّر شيئاً**، كي لا
    ينتقل حكمٌ من الاستراتيجية إلى أداةٍ مساعدة.
    """

    def __init__(self) -> None:
        self._checks: list[Check] = []

    def ok(self, name_ar: str, detail_ar: str) -> None:
        self._checks.append(Check(name_ar, True, detail_ar))

    def fail(self, name_ar: str, detail_ar: str) -> Assessment:
        """يسجّل السقوط **ويعيد التقييم منتهياً** — فيصير الرفض سطراً واحداً."""
        self._checks.append(Check(name_ar, False, detail_ar))
        return Assessment(None, tuple(self._checks))

    def signal(self, signal: Signal) -> Assessment:
        return Assessment(signal, tuple(self._checks))

    @property
    def checks(self) -> tuple[Check, ...]:
        return tuple(self._checks)


def as_dicts(checks: Sequence[Check]) -> list[dict]:
    return [c.as_dict() for c in checks]


__all__ = ["Check", "Assessment", "Recorder", "as_dicts"]
