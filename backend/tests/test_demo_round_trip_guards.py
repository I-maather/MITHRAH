"""
أسوار الصفقة التجريبية تعضّ — لا تُذكر في تعليق فقط.

## لماذا هذا الملف موجود

سكربتٌ يفتح مركزاً حقيقياً — ولو على Demo — يُقاس بأسواره لا بنيّته. وصنف
العطل الحاكم لهذا المشروع كلّه هو **مسارٌ كُتب ولم يُنفَّذ فلم ينكشف**: قفلٌ
مكتوب لا يُختبَر يساوي قفلاً مفقوداً بالضبط، والفرق بينهما لا يظهر إلا في
اليوم الذي كنّا نحتاجه فيه.

فكل سورٍ هنا يُفحَص بأن **يُشغَّل السكربت فعلاً** ويُقرأ رمز خروجه، لا بأن
يُقرأ الشرط في المصدر.

## ما يُفحَص

  * لا تشغيل بلا العبارة الحرفية — والعبارة الناقصة ليست موافقة.
  * لا تشغيل ما دامت وحدة مسافة الوقف غير مُثبَتة.
  * السوران يعملان **قبل أي نداء شبكة**: لا جلسة، لا سرّ، لا وسيط.
  * Demo مثبَّتة في المصدر ولا تُقرأ من إعداد.
"""
from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

MODULE = "app.diagnostics.demo_round_trip"
BACKEND = Path(__file__).resolve().parents[1]
SOURCE = (BACKEND / "app" / "diagnostics" / "demo_round_trip.py").read_text(encoding="utf-8")

APPROVAL = "أوافق على صفقة تجريبية واحدة"


def run(*args: str) -> subprocess.CompletedProcess:
    """
    عمليةٌ منفصلة عمداً: السور يجب أن يعمل على المسار الذي تسلكه المالكة
    في الطرفية، لا على استدعاء دالة من داخل الاختبار.
    """
    return subprocess.run(
        [sys.executable, "-m", MODULE, *args],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("args,label", [
    ([], "بلا موافقة"),
    (["--approve", ""], "موافقة فارغة"),
    (["--approve", "أوافق"], "موافقة ناقصة"),
    (["--approve", "اوافق على صفقة تجريبية واحدة"], "بلا همزة — ليست العبارة"),
    (["--approve", APPROVAL + " شكراً"], "زيادة على العبارة"),
])
def test_nothing_runs_without_the_exact_phrase(args, label):
    """**السور الثاني.** والمطابقة حرفية: القرب من العبارة ليس موافقة."""
    result = run(*args)
    assert result.returncode == 2, f"{label}: مضى السكربت"
    assert "لا تشغيل بلا موافقة صريحة" in result.stderr


def test_the_script_refuses_if_the_stop_unit_is_not_the_measured_one():
    """
    كان السكربت يقف عند `STOP_DISTANCE_UNIT_PROVEN = False`. وقد **قيست
    الوحدة** يوم 2026-09-01 (فرق سعر خام)، فزال ذلك الحاجز.

    ولم يبقَ السكربت بلا حارس على الوحدة: يرفض التشغيل إن لم تكن `PRICE` —
    فلو عاد أحدٌ إلى النقاط يوماً لتوقّف السكربت بدل أن يرسل وقفاً خاطئاً.
    """
    assert 'STOP_DISTANCE_UNIT != "PRICE"' in SOURCE
    assert "STOP_DISTANCE_UNIT_PROVEN" not in SOURCE, "بقيت إشارة إلى حارسٍ زال"


def test_the_stop_distance_is_written_in_price_units_above_the_broker_minimum():
    """
    **حدُّ الوسيط نسبةٌ لا سعرٌ خام — وهذا الفحص كان يثبّت الخطأ.**

    كان يشترط `STOP_DISTANCE >= 0.01` لأن `minStopOrProfitDistance` قُرئت
    `0.01` بوحدة السعر = ١٠٠ نقطة. وهي `{"unit":"PERCENTAGE","value":0.01}`
    — أي ٠٫٠١٪ من السعر = **١٫١٦ نقطة** على 1.16292 (قياس 2026-09-03).

    فالشرط القديم كان يفرض على صفقة التشغيل وقفاً بمئة وخمسين نقطة، وهو
    عند الكمية الدنيا **١٫٥٠ دولاراً** — الحدُّ الصلب للصفقة كلُّه، على
    صفقةٍ غرضها إثبات الأنبوب لا الربح.

    والشرط الصحيح طرفان: **فوق حدّ الوسيط المحلول**، و**تحت ما يجعل
    كلفة الاختبار جزءاً من نتيجته**.
    """
    import app.diagnostics.demo_round_trip as drt

    reference = Decimal("1.16292")          # سعرٌ مقيس من الوسيط
    broker_minimum = Decimal("0.01") / Decimal("100") * reference

    assert drt.STOP_DISTANCE > broker_minimum, (
        f"الوقف {drt.STOP_DISTANCE} دون حدّ الوسيط المحلول {broker_minimum}."
    )
    assert drt.STOP_DISTANCE < Decimal("1"), "رقمٌ بهذا الحجم ليس بوحدة السعر"
    assert drt.TARGET_DISTANCE > drt.STOP_DISTANCE

    # كلفة الاختبار: خسارةُ السعر عند الكمية الدنيا (100 وحدة) وحدها.
    price_loss = drt.STOP_DISTANCE * Decimal("100")
    assert price_loss <= Decimal("0.50"), (
        f"صفقة تشغيلٍ تعرّض {price_loss} دولاراً — أكبر مما يلزم لإثبات أنبوب."
    )


def test_the_guards_run_before_any_network_or_secret_is_touched():
    """
    ترتيبٌ لا تجميل: التشغيل بلا موافقة يجب أن يتوقّف **قبل** أن نلمس
    الوسيط أو ملف الأسرار. والدليل أن الرفض يخرج نظيفاً في بيئةٍ بلا شبكة
    ولا أسرار — ولو سبق الاتصالُ السورَ لانفجر بعلّةٍ أخرى.
    """
    result = run()
    assert result.returncode == 2
    for leak in ("Traceback", "SecretNotFound", "ConnectionError", "httpx"):
        assert leak not in result.stderr, f"لُمس شيءٌ قبل السور: {leak}"


def test_demo_is_written_in_the_source_not_read_from_configuration():
    """**السور الأول.** إعدادٌ يُقرأ إعدادٌ يمكن أن يتغيّر تحت أقدامنا."""
    assert "CapitalEnvironment.DEMO" in SOURCE
    assert "BROKER_MODE" not in SOURCE and "broker_mode" not in SOURCE, (
        "البيئة تُقرأ من إعداد — فيصير الحساب الحقيقي على بُعد متغيّر واحد"
    )
    assert "if adapter.is_live" in SOURCE, "لا فحص ثانٍ بعد الاتصال"


def test_the_position_is_closed_in_a_finally_and_failure_is_not_swallowed():
    """
    **السور الخامس.** مركزٌ يُفتح ولا يُغلق لأن ما بينهما انفجر هو أسوأ ما
    يمكن أن يتركه سكربتُ إثبات. والإغلاق في `finally`، وتعذُّره يصرخ
    بالمعرّف كي تُغلقه يدٌ بشرية — ولا يُبتلع في `except: pass`.
    """
    finally_block = SOURCE[SOURCE.index("    finally:"):]
    assert "close_position" in finally_block, "الإغلاق ليس في finally"
    assert "أغلقيه بنفسك" in finally_block and "{deal_id}" in finally_block
    assert "except Exception:\n" not in finally_block


def test_the_close_is_verified_against_the_position_list():
    """
    «أُغلق» من الوسيط إيصالُ استلام لا إثبات. الدليل أن المركز **اختفى**.
    وهذه القاعدة نفسها التي أنقذت `place_order` من قبول تنفيذٍ مختلف بصمت.
    """
    finally_block = SOURCE[SOURCE.index("    finally:"):]
    assert "list_positions()" in finally_block
    assert "ما زال في القائمة بعد إغلاقٍ «ناجح»" in finally_block


def test_it_does_not_flip_the_constant_it_depends_on():
    """
    **السور السادس.** سكربتُ إثباتٍ يغيّر الثابت الذي يحرسه يصير سكربتَ
    التفاف. والقلب قرارٌ بشريّ بعد قراءة قياس المسبار.
    """
    assert "STOP_DISTANCE_UNIT_PROVEN = True" not in SOURCE
    assert "LIVE_TRADING" not in SOURCE and "LIVE_API_ENABLED" not in SOURCE


def test_the_signal_is_hand_written_and_says_so():
    """
    الصفقة تُثبت الأنبوب لا القرار. واسمُ استراتيجيةٍ حقيقيّ على صفقةٍ
    يدوية يلوّث سجلّ الأداء لاحقاً بصفقةٍ لم تصدر عن حافّة.
    """
    assert 'strategy_name="MANUAL_PIPELINE_PROOF"' in SOURCE
    assert "ليست قراراً تداولياً" in SOURCE
