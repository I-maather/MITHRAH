"""
أقفال السلامة لطبقة Capital.com.

ثلاثة أقفال مستقلة، كلٌّ منها كافٍ وحده لمنع أي طلب خطر:

  1. LIVE_API_ENABLED          — ثابت في الكود. مرفوعٌ الآن للقراءة فقط
                                 (٣١ أغسطس، بموافقة مكتوبة).
  2. ExecutionLock              — يمنع كل نداء يُعدّل شيئاً عند الوسيط.
  3. is_mutating() في الناقل    — يمنع الطلب نفسه قبل مغادرته العملية.

القفل الأول ثابت مصدرياً ولا يُغيَّر بمتغير بيئة. تغييره يتطلب تعديل هذا الملف
ومراجعة و commit — وهذا مقصود.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ...secretstore.redaction import RedactedError
from .endpoints import CapitalEnvironment, is_live_url, is_mutating

#: قفل مصدري. لا يقرأ متغير بيئة عمداً.
#:
#: **رُفع في ٣١ أغسطس ٢٠٢٦ بموافقة المالكة المكتوبة.**
#:
#: ما فتحه: قراءة الحساب الحقيقي — الأسعار والرصيد والشموع وقواعد التداول.
#: وما لم يفتحه: إرسال أمر. ثلاثة أقفال مستقلّة تمنعه ولم يمسّها هذا التغيير:
#:
#:   ExecutionLock في الناقل   — يرفض كل فعل مُعدِّل قبل مغادرة الطلب العملية
#:   LIVE_TRADING = false      — في بيئة الخادم
#:   التحقّق من الوقف بعد التنفيذ — يقرأ المركز من الوسيط ويرفض أي مركز
#:                               بلا وقف أو بوقفٍ غير الذي طُلب. (حلّ محلّ
#:                               `STOP_DISTANCE_UNIT_PROVEN` بعد أن قيست
#:                               الوحدة في 2026-09-01: فرق سعر خام.)
#:
#: وإعادته إلى False تُعيد المنع فوراً وبلا أثر جانبي — لا حالة تعتمد عليه.
LIVE_API_ENABLED: bool = True

#: قفل التنفيذ الافتراضي. كل نداء مُعدِّل مرفوض ما لم يُفتح صراحةً بموافقة موثقة.
EXECUTION_UNLOCK_ENV = "CAPITAL_EXECUTION_UNLOCKED"


class LiveApiBlocked(RedactedError):
    pass


class ExecutionLocked(RedactedError):
    pass


class MutatingEndpointBlocked(RedactedError):
    pass


def assert_environment_allowed(environment: CapitalEnvironment) -> None:
    if environment is CapitalEnvironment.LIVE and not LIVE_API_ENABLED:
        raise LiveApiBlocked(
            "واجهة Capital.com الحقيقية (Live) مقفلة في الكود. "
            "لا يمكن فتحها بمتغير بيئة — تتطلب تعديل safety.LIVE_API_ENABLED ومراجعة."
        )


#: المضيفون المسموح بلوغهم — قائمة بيضاء صريحة، لا استنتاج.
def _allowed_hosts() -> frozenset[str]:
    from urllib.parse import urlparse

    from .endpoints import DEMO_BASE_URL, DEMO_WS_URL, LIVE_BASE_URL, LIVE_WS_URL

    hosts = {DEMO_BASE_URL, DEMO_WS_URL.replace("wss://", "https://")}
    if LIVE_API_ENABLED:
        hosts |= {LIVE_BASE_URL, LIVE_WS_URL.replace("wss://", "https://")}
    return frozenset(urlparse(u).netloc.lower() for u in hosts)


def assert_url_allowed(url: str) -> None:
    """
    يرفض كل مضيف خارج القائمة البيضاء.

    **كان الفحص `is_live_url(url) and not LIVE_API_ENABLED`** — وهو يرفض
    المضيف المجهول *بالمصادفة* لا بالقصد: `is_live_url` يعدّ كلّ ما ليس ديمو
    «حقيقياً»، فكان القفل المغلق يحجب الجميع. ولمّا رُفع القفل (٣١ أغسطس،
    للقراءة فقط) سقط الحجب عن **كل عنوان في الدنيا**، لا عن كابيتال وحده.
    كشفه اختبار `test_unknown_host_is_treated_as_live_and_blocked`.

    فالفحص الآن قائمة بيضاء صريحة: الديمو دائماً، والحقيقي حين يكون القفل
    مرفوعاً، ولا شيء غيرهما — ورفعُ القفل يضيف مضيفَي كابيتال فقط.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url if "//" in url else f"https://{url}")
    host = (parsed.netloc or parsed.path).lower()
    if host not in _allowed_hosts():
        raise LiveApiBlocked(
            f"رُفض مضيف خارج القائمة البيضاء: {host or '(فارغ)'}."
        )


def assert_not_mutating(method: str, path: str) -> None:
    if is_mutating(method, path):
        raise MutatingEndpointBlocked(
            f"العملية {method.upper()} {path} تُعدّل حالة عند الوسيط وهي مقفلة في هذه المهمة. "
            "لا يوجد مسار برمجي لفتحها دون موافقة موثقة من المالكة."
        )


@dataclass
class ExecutionLock:
    """
    قفل التنفيذ على مستوى العملية.

    مغلق افتراضياً. فتحه يتطلب اجتماع ثلاثة شروط، وأي واحد ناقص ⇒ يبقى مغلقاً:
      * متغير بيئة صريح
      * مرجع موافقة مالكة غير فارغ
      * سبب مكتوب
    وهو **مستقلّ تماماً** عن `LIVE_API_ENABLED`: رفعُ ذاك يفتح القراءة
    على البيئة الحقيقية، ولا يمسّ هذا القفل بحال.
    """

    unlocked: bool = False
    owner_authorization_reference: Optional[str] = None
    reason_ar: str = ""
    unlocked_at_utc: Optional[datetime] = None

    @staticmethod
    def locked() -> "ExecutionLock":
        return ExecutionLock()

    @classmethod
    def from_environment(cls) -> "ExecutionLock":
        """
        حتى مع ضبط متغير البيئة، لا يُفتح القفل ما دام Live مقفلاً في الكود
        ولا توجد موافقة موثقة. هذه الدالة موجودة لتوثيق المسار، لا لتسهيله.
        """
        if os.environ.get(EXECUTION_UNLOCK_ENV, "").lower() not in {"1", "true", "yes"}:
            return cls.locked()
        return cls.locked()  # ⛔ لا مسار تلقائي — تُفتح فقط عبر authorise()

    def authorise(
        self, *, owner_authorization_reference: str, reason_ar: str, at: datetime
    ) -> "ExecutionLock":
        if not owner_authorization_reference.strip():
            raise ExecutionLocked("فتح قفل التنفيذ يتطلب مرجع موافقة من المالكة.")
        if len(reason_ar.strip()) < 10:
            raise ExecutionLocked("فتح قفل التنفيذ يتطلب سبباً مكتوباً.")
        return ExecutionLock(
            unlocked=True,
            owner_authorization_reference=owner_authorization_reference,
            reason_ar=reason_ar,
            unlocked_at_utc=at,
        )

    def assert_can_execute(self, operation: str) -> None:
        if not self.unlocked:
            raise ExecutionLocked(
                f"العملية «{operation}» مقفلة. التنفيذ مُعطَّل على مستوى المهمة: "
                "لا يوجد إرسال أوامر ولا تعديل مراكز ولا تغيير تفضيلات."
            )

    def as_dict(self) -> dict:
        return {
            "unlocked": self.unlocked,
            "owner_authorization_reference": self.owner_authorization_reference,
            "reason_ar": self.reason_ar,
            "unlocked_at_utc": self.unlocked_at_utc.isoformat() if self.unlocked_at_utc else None,
        }


#: القفل العام المستخدم في هذه المهمة — مغلق دائماً.
TASK_EXECUTION_LOCK = ExecutionLock.locked()
