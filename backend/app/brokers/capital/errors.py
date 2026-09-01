"""أخطاء طبقة Capital.com — كلها ترث RedactedError فلا تحمل سرّاً أبداً."""
from __future__ import annotations

from ...secretstore.redaction import RedactedError


class CapitalError(RedactedError):
    """جذر كل أخطاء Capital.com."""


class CapitalAuthError(CapitalError):
    """فشل المصادقة — مفتاح أو معرّف أو كلمة مرور API غير صحيحة."""


class CapitalSessionExpired(CapitalError):
    """انتهت صلاحية CST / X-SECURITY-TOKEN (10 دقائق بلا نشاط)."""


class CapitalAuthLockout(CapitalError):
    """فشل متكرر في المصادقة — النظام يغلق نفسه بدل الاستمرار في المحاولة."""


class CapitalRateLimited(CapitalError):
    """تجاوز حدود الطلبات المعلنة."""


class CapitalTransportError(CapitalError):
    """خطأ شبكة أو استجابة غير صالحة."""


class CapitalTimeout(CapitalTransportError):
    """
    مهلة. بعد إرسال أمر، هذه **حالة غير معلومة** وليست فشلاً.
    لا يجوز إعادة الإرسال — يجب المطابقة أولاً.
    """


class CapitalMalformedResponse(CapitalError):
    """استجابة لا تطابق الشكل الرسمي — نرفضها ولا نخمّن."""


class CapitalMarketClosed(CapitalError):
    pass


class CapitalNotFound(CapitalError):
    pass


class CapitalExecutionUncertain(CapitalError):
    """
    أُرسل الأمر ولم يُحسم مصيره.

    **أخطر من الرفض.** الرفض يعني أن شيئاً لم يحدث؛ وهذه تعني أن مركزاً قد
    يكون فُتح دون أن نعلم. لا تُعالَج بإعادة الإرسال أبداً — بل بالاستقصاء
    (`resolve_unknown_execution`) وتفعيل قاطع الطوارئ وتدخّل بشري.

    ## ولماذا تحمل المعرّفات

    في 2026-09-01 رُفع هذا الاستثناء **من داخل** `place_order`، فلم تكن قد
    أعادت شيئاً بعد. فرأى `finally` في سكربت الإثبات أن لا معرّف بين يديه،
    وقال «لا مركز فُتح — لا شيء يُغلق». وكان المركز مفتوحاً.

    ⇒ جملةٌ تطمئن بلا حقّ، وهي أسوأ من صمت. فصارت المعرّفات المعروفة تُحمل
    **في الاستثناء نفسه**: من يمسكه يعرف ما يبحث عنه، مهما وقع قبله.
    """

    def __init__(self, message: str, *, deal_ids: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        #: كل معرّف قد يخصّ المركز الناتج — من `affectedDeals` ومن التأكيد.
        self.deal_ids = tuple(deal_ids)
