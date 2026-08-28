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
