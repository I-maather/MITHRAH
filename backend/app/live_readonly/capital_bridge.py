"""
جسرٌ بين جلسة الوسيط وواجهة القراءة فقط.

## المشكلة

`LiveReadOnlyMarketDataProvider` كُتب لـ`LiveSession` — جلسةٍ مستقلّة لها
`authenticated` و`get(path)`. وجلسة الوسيط `CapitalSession` لها واجهة أخرى:
`ensure_session()` و`auth_headers()` و`transport.send(...)`.

فتمريرُ الثانية إلى الأول ينفجر بـ:

    AttributeError: 'CapitalSession' object has no attribute 'authenticated'

## لماذا جسرٌ لا جلسةٌ ثانية

`LiveSession` جاهزة ومُختبَرة، وبناؤها كان الحلّ الأقصر. لكنه يعني **تسجيل
دخول ثانٍ** إلى كابيتال بنفس الاعتمادات. وبعض الوسطاء يُبطل الجلسة الأولى
عند فتح الثانية — فأكسر اتصال الوسيط كلّه لأصلح مزوّداً واحداً. وهذا ثمنٌ
لا يُدفع لتوفير عشرين سطراً.

فالجسر يعيد استعمال الجلسة القائمة: تسجيل دخول واحد، وحالة واحدة، وقفل
تنفيذ واحد.

## والأمان لم يُضعَف

`CapitalSession.transport` هو `GuardedTransport`، وهو يرفض كل فعل مُعدِّل
قبل مغادرة الطلب العملية، ويفحص القائمة البيضاء للمضيفين. والجسر لا يملك
ميثوداً واحداً يرسل غير `GET` — لا لأنه مؤدَّب، بل لأنه لا يكتب غيرها.
"""
from __future__ import annotations

from typing import Any, Optional


class CapitalReadOnlyBridge:
    """
    يعرض واجهة `LiveSession` (قراءةً فقط) فوق `CapitalSession`.

    يُنفّذ ما يحتاجه `LiveReadOnlyMarketDataProvider` بالضبط، لا أكثر:
    `authenticated` و`get`.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    @property
    def authenticated(self) -> bool:
        """
        الجلسة صالحة إن كانت رموزها قائمة.

        ولا تُنشأ جلسةٌ هنا: `configured` سؤالٌ عن الحال، وسؤالٌ لا يُغيّر
        ما يسأل عنه. إنشاء الجلسة موضعه `get` عند أول قراءة فعلية.
        """
        return getattr(self._session, "tokens", None) is not None

    def get(self, path: str, *, params: Optional[dict] = None):
        """قراءة مُصادَقة عبر ناقل الوسيط المحروس."""
        self._session.ensure_session()
        return self._session.transport.send(
            "GET",
            f"{self._session.base_url}{path}",
            headers=self._session.auth_headers(),
            params=params,
        )

    def __repr__(self) -> str:  # noqa: D105
        return f"<CapitalReadOnlyBridge authenticated={self.authenticated}>"
