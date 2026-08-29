"""
MOBILE — طبقة الجوال الخلفية.

الهاتف عميل **مراقبة وتقليل مخاطرة**، لا طرف موثوق ولا مسار تنفيذ.
كل ما يستطيعه مُعرَّف على الخادم، ولا يوسّعه تعديل التطبيق.

  * `security.py`       تسجيل الأجهزة، الرموز قصيرة العمر، الصلاحيات
  * `notifications.py`  APNs بواجهة إنتاج ومُقلِّد، ونصّ قفل شاشة خاص
  * `api.py`            `/api/mobile/v1/` — قراءة + ثلاثة إجراءات تُقلّل المخاطرة

**لا مفتاح وسيط ولا مفتاح مزوّد ولا رمز جلسة يصل إلى الجهاز.**
"""
from .api import API_PREFIX, MobileApi, describe_api
from .notifications import (
    MockApnsProvider,
    Notification,
    NotificationService,
    NotificationType,
)
from .security import (
    FORBIDDEN_MOBILE_ACTIONS,
    NEVER_ON_DEVICE,
    MobilePermission,
    MobileSecurityService,
)

__all__ = [
    "API_PREFIX", "MobileApi", "describe_api",
    "MobileSecurityService", "MobilePermission",
    "FORBIDDEN_MOBILE_ACTIONS", "NEVER_ON_DEVICE",
    "NotificationService", "Notification", "NotificationType", "MockApnsProvider",
]
