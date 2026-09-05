"""تهيئةُ السجلّ — وإلا فكلُّ تحذيرٍ يُكتَب يذهب إلى العدم.

`uvicorn` يُهيّئ مسجّلاته وحدها ويترك الجذر بلا معالج. فكلُّ
`logging.getLogger(__name__).warning(...)` في التطبيق — وفيه «تعذّر تنفيذ
فحص الإقلاع» و«تعذّرت كتابة الدفتر» و«تعذّر بناء خطّة الإدارة» — كان
يُنشأ ثم يُهمَل بلا وجهة. أي أنّ النظام كان يكتب أعطاله لنفسه.

فتُضاف وجهةٌ واحدة إلى الجذر عند الاستيراد. ولا يُزاحَم إعدادٌ قائم: من
هيّأ سجلّه (الاختبارات، `cli.py`) يبقى إعدادُه.
"""

from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(levelname)s %(name)s: %(message)s"


def configure(*, stream=None, force: bool = False) -> bool:
    """يُرجع True إن أضاف وجهةً، وFalse إن كان هناك إعدادٌ قائم."""
    root = logging.getLogger()
    if root.handlers and not force:
        return False
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    # **الحجب يُولَد مع الوجهة.** كان يُركَّب لاحقاً داخل `build_system`
    # أثناء دورة الحياة، فبين استيراد التطبيق وبدئه نافذةٌ تكتب فيها وجهةٌ
    # بلا حاجب. ونافذةٌ كهذه لا تُقاس بطولها بل بما قد يمرّ فيها.
    from .secretstore.redaction import RedactingFilter

    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    level = os.environ.get("MATHRAH_LOG_LEVEL", "INFO").upper()
    root.setLevel(getattr(logging, level, logging.INFO))
    return True


__all__ = ["configure"]
