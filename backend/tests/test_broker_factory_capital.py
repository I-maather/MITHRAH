"""
اختبارات مسار كابيتال في مصنع الوسطاء.

الغرض ليس إثبات أن المسار «يعمل»، بل إثبات أنه **لا ينفّذ**: أن الاتصال
بحساب حقيقي لقراءة السعر لا يفتح بأي حال إرسال أمر.

قاعدة هذا الملف: لا يلمس اختبارٌ واحدٌ الشبكة. الناقل يُستبدل، والأسرار
تُحقن من الذاكرة.
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

#: جذر الخلفية — تُشغَّل منه العملية الفرعية كي تجد حزمة `app`.
BACKEND_ROOT = Path(__file__).resolve().parents[1]

from app.brokers.capital.endpoints import CapitalEnvironment
from app.brokers.capital.safety import (
    ExecutionLock,
    ExecutionLocked,
    LiveApiBlocked,
)
from app.brokers.capital.transport import GuardedTransport
from app.brokers.factory import build_broker, build_capital_adapter
from app.config import Settings
from app.secretstore.provider import InMemorySecretProvider


def a_secret_provider() -> InMemorySecretProvider:
    return InMemorySecretProvider(
        {
            "CAPITAL_API_KEY": "k" * 16,
            "CAPITAL_IDENTIFIER": "owner@example.test",
            "CAPITAL_API_PASSWORD": "p" * 10,
        }
    )


def settings_with(mode: str) -> Settings:
    return Settings(BROKER_MODE=mode, LIVE_TRADING=False, RISK_MODE="VALIDATION")


# ---------------------------------------------------------------------------
# التعرّف على الوضع
# ---------------------------------------------------------------------------
def test_capital_demo_is_a_known_mode():
    """قبل هذا الإصلاح كان المصنع يرفع ValueError: «BROKER_MODE غير معروف»."""
    broker = build_broker(settings_with("CAPITAL_DEMO"), secrets=a_secret_provider())
    assert broker.broker.value.lower().startswith("capital")


def test_unknown_mode_still_raises():
    with pytest.raises(ValueError):
        build_broker(Settings(BROKER_MODE="MOCK").model_copy(update={"broker_mode": "NOPE"}))


def test_mock_remains_the_default():
    assert Settings().broker_mode == "MOCK"


# ---------------------------------------------------------------------------
# القفل الأول: البيئة الحقيقية مقفلة مصدرياً
# ---------------------------------------------------------------------------
def test_capital_live_is_refused_while_the_source_lock_is_closed():
    """
    `LIVE_API_ENABLED = False` ثابت في الكود. طلب CAPITAL_LIVE يجب أن يُرفض
    **عند الإقلاع** بسبب مقروء، لا أن يمرّ ثم يفشل عند أوّل طلب شبكة.
    """
    from app.brokers.capital import safety

    if safety.LIVE_API_ENABLED:
        pytest.skip("القفل المصدري مفتوح — هذا الاختبار يحرس حالة الإغلاق")
    with pytest.raises(LiveApiBlocked):
        build_broker(settings_with("CAPITAL_LIVE"), secrets=a_secret_provider())


def test_the_source_lock_is_assigned_a_literal_not_read_from_anywhere():
    """
    الثابت الذي يحرسه هذا الاختبار ليس **قيمة** القفل بل **مصدرها**:
    سطرٌ حرفيّ في الملف، لا يُقرأ من بيئة ولا إعداد ولا وسيط أمر.

    رُفع القفل إلى True في ٣١ أغسطس بموافقة مكتوبة. ولو كان الاختبار مربوطاً
    بالقيمة لسقط عند الرفع فحُذف أو ضُعّف — وهذا كيف تموت الاختبارات الأمنية.
    فهو مربوط بالشكل: أياً كانت القيمة، تغييرها يتطلّب تعديل الملف ومراجعة.

    ولا يستعمل `importlib.reload` عمداً: إعادة التحميل تُنشئ أصنافاً جديدة
    لنفس الأسماء، فيصير `ExecutionLocked` المرفوع غير الذي يمسكه
    `pytest.raises` في الاختبارات التالية، فتسقط اختباراتٌ سليمة.
    """
    from app.brokers.capital import safety

    line = next(
        raw for raw in Path(safety.__file__).read_text(encoding="utf-8").splitlines()
        if raw.startswith("LIVE_API_ENABLED")
    )
    assert re.fullmatch(r"LIVE_API_ENABLED: bool = (True|False)", line.strip()), line
    for forbidden in ("environ", "getenv", "Field(", "Settings", "argv"):
        assert forbidden not in line


def test_the_source_lock_is_immune_to_a_hostile_environment():
    """
    تحقّق سلوكي في **عملية منفصلة** فلا تتلوّث جلسة الاختبار.

    نضبط كل متغيّر بيئة قد يخطر ببال أحد، ثم نستورد الوحدة من الصفر،
    ونشترط أن القيمة **مطابقة للمكتوب في المصدر** — لا أن تكون False.
    فالبيئة لا ترفع القفل ولا تُنزله؛ هذا هو الأمان، لا القيمة نفسها.
    """
    from app.brokers.capital import safety

    line = next(
        raw for raw in Path(safety.__file__).read_text(encoding="utf-8").splitlines()
        if raw.startswith("LIVE_API_ENABLED")
    )
    in_source = line.strip().endswith("True")

    code = textwrap.dedent(
        """
        import os
        for name in ("LIVE_API_ENABLED", "CAPITAL_LIVE_ENABLED",
                     "CAPITAL_ENVIRONMENT", "LIVE_TRADING", "BROKER_MODE"):
            os.environ[name] = "false"
        from app.brokers.capital import safety
        print(safety.LIVE_API_ENABLED)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(in_source)


def test_live_environment_is_read_only_even_with_the_source_lock_open():
    """
    **هذا هو الاختبار الذي صار يحمي المال.**

    بعد رفع القفل الأول صار الوصول إلى الحساب الحقيقي ممكناً. وهذا الاختبار
    يُثبت أن ذلك الوصول **قراءةٌ فقط**: محوّل البيئة الحقيقية يُبنى بقفل تنفيذ
    مغلق، وكل فعل مُعدِّل يُرفض في الناقل قبل أن يغادر الطلب العملية.
    """
    from app.brokers.capital import safety

    if not safety.LIVE_API_ENABLED:
        pytest.skip("القفل المصدري مغلق — لا بيئة حقيقية تُختبر")

    adapter = build_capital_adapter(
        CapitalEnvironment.LIVE, secrets=a_secret_provider()
    )
    assert adapter.is_live is True
    assert adapter.session.transport.execution_lock is adapter.execution_lock
    for method, path in (
        ("POST", "/api/v1/positions"),
        ("PUT", "/api/v1/positions/abc"),
        ("DELETE", "/api/v1/positions/abc"),
    ):
        with pytest.raises(ExecutionLocked):
            adapter.session.transport.send(
                method, f"{CapitalEnvironment.LIVE.base_url}{path}", headers={}
            )


# ---------------------------------------------------------------------------
# القفل الثاني: التنفيذ مغلق افتراضياً
# ---------------------------------------------------------------------------
def test_the_adapter_is_built_with_a_closed_execution_lock():
    adapter = build_capital_adapter(
        CapitalEnvironment.DEMO, secrets=a_secret_provider()
    )
    with pytest.raises(ExecutionLocked):
        adapter.execution_lock.assert_can_execute("POST /positions")


def test_transport_and_adapter_share_one_lock():
    """
    قفلان منفصلان يعنيان أن فتح أحدهما يمرّ بلا أن يظهر في أي اختبار.
    هذا الاختبار يُثبت أنهما **الكائن نفسه**، لا كائنان متطابقان.
    """
    adapter = build_capital_adapter(
        CapitalEnvironment.DEMO, secrets=a_secret_provider()
    )
    transport = adapter.session.transport
    assert isinstance(transport, GuardedTransport)
    assert transport.execution_lock is adapter.execution_lock


def test_a_mutating_request_is_refused_by_the_transport():
    """
    الرفض يقع في الناقل — أي قبل أن يغادر الطلب العملية، ومهما كان المستدعي.
    """
    adapter = build_capital_adapter(
        CapitalEnvironment.DEMO, secrets=a_secret_provider()
    )
    with pytest.raises(ExecutionLocked):
        adapter.session.transport.send(
            "POST",
            f"{CapitalEnvironment.DEMO.base_url}/api/v1/positions",
            headers={},
            json={"epic": "EURUSD"},
        )


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_every_mutating_verb_is_refused(method):
    adapter = build_capital_adapter(
        CapitalEnvironment.DEMO, secrets=a_secret_provider()
    )
    with pytest.raises(ExecutionLocked):
        adapter.session.transport.send(
            method,
            f"{CapitalEnvironment.DEMO.base_url}/api/v1/positions/abc",
            headers={},
        )


def test_an_explicitly_passed_lock_is_the_one_used():
    """
    حين تبني الطبقة الأعلى قفلاً واحداً للنظام كله، يجب أن يصل إلى هنا هو
    لا نسخةٌ منه — وإلا صار للنظام قفلان يُفتح أحدهما دون الآخر.
    """
    lock = ExecutionLock.locked()
    adapter = build_capital_adapter(
        CapitalEnvironment.DEMO, secrets=a_secret_provider(), execution_lock=lock
    )
    assert adapter.execution_lock is lock
    assert adapter.session.transport.execution_lock is lock


# ---------------------------------------------------------------------------
# الأسرار
# ---------------------------------------------------------------------------
def test_the_secrets_file_default_points_at_runtime_env():
    """
    كُتبت الأسرار على الخادم في `secrets/runtime.env`، وكان القارئ يقرأ
    `secrets/capital.env`. مفتاحٌ موجود وغير مقروء أسوأ من مفتاح غائب،
    لأن الأول يفشل بينما المالكة متأكّدة أنها أدخلته.
    """
    assert Settings().secrets_file.endswith("secrets/runtime.env")


def test_no_secret_value_appears_in_the_adapter_repr():
    adapter = build_capital_adapter(
        CapitalEnvironment.DEMO, secrets=a_secret_provider()
    )
    blob = repr(adapter)
    assert "k" * 16 not in blob
    assert "p" * 10 not in blob
    assert "owner@example.test" not in blob
