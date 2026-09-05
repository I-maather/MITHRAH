"""تحذيرٌ بلا وجهةٍ تحذيرٌ لم يُكتَب.

`uvicorn` يُهيّئ مسجّلاته وحدها ويترك الجذر بلا معالج. فكانت تحذيرات
التطبيق كلُّها — «تعذّر تنفيذ فحص الإقلاع»، «تعذّرت كتابة الدفتر»،
«تعذّر بناء خطّة الإدارة» — تُنشأ ثم تُهمَل. النظام كان يكتب أعطاله
لنفسه، والسجلّ الذي يُستشهَد به عند التحقيق فارغٌ لا لأنّ شيئاً لم يقع.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from app import logging_setup

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def test_main_configures_logging_before_the_app_starts():
    source = MAIN.read_text(encoding="utf-8")
    assert "logging_setup" in source, "main.py لا يهيّئ السجلّ"
    assert source.index("logging_setup.configure()") < source.index("lifespan=_lifespan"), (
        "التهيئة تأتي بعد إنشاء التطبيق — فتضيع سطورُ الإقلاع"
    )


def test_a_warning_reaches_the_stream():
    stream = io.StringIO()
    root = logging.getLogger()
    before = list(root.handlers)
    level = root.level
    try:
        root.handlers = []
        assert logging_setup.configure(stream=stream) is True
        logging.getLogger("app.runtime.startup").warning("اختبار الوجهة")
        assert "اختبار الوجهة" in stream.getvalue()
        assert "app.runtime.startup" in stream.getvalue()
    finally:
        root.handlers = before
        root.setLevel(level)


def test_an_existing_configuration_is_not_displaced():
    stream = io.StringIO()
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        root.handlers = [logging.NullHandler()]
        assert logging_setup.configure(stream=stream) is False
        assert len(root.handlers) == 1
    finally:
        root.handlers = before


def test_the_startup_gate_records_its_verdict():
    source = (
        Path(__file__).resolve().parents[1] / "app" / "runtime" / "startup.py"
    ).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "_LOG.info" in code, "البوابة تمرّ بلا أثرٍ في السجلّ"
    assert "verdict=" in code, "الحكم نفسه غير مسجَّل"


def test_the_destination_is_born_with_its_shield():
    """وجهةٌ بلا حاجبٍ ولو للحظةٍ وجهةٌ قد يمرّ فيها سرّ.

    كان الحاجب يُركَّب داخل `build_system` أثناء دورة الحياة، والوجهة
    تُنشأ عند الاستيراد. فبينهما نافذةٌ لا تُقاس بطولها بل بما قد يمرّ
    فيها. فصار يُولَد معها.
    """
    from app.secretstore.redaction import RedactingFilter

    stream = io.StringIO()
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        root.handlers = []
        assert logging_setup.configure(stream=stream) is True
        assert len(root.handlers) == 1
        handler = root.handlers[0]
        assert any(isinstance(f, RedactingFilter) for f in handler.filters), (
            "المعالج أُنشئ بلا حاجب"
        )
    finally:
        root.handlers = before


def test_a_registered_secret_never_reaches_the_stream():
    from app.secretstore.redaction import REGISTRY

    secret = "s3cr3t-value-not-a-real-token"
    stream = io.StringIO()
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        root.handlers = []
        logging_setup.configure(stream=stream)
        REGISTRY.register_many([secret])
        logging.getLogger("app.brokers.capital.session").info("token=%s", secret)
        assert secret not in stream.getvalue(), "سرٌّ مسجَّل بلغ الوجهة"
    finally:
        REGISTRY.forget(secret)
        root.handlers = before
