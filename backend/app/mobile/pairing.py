"""
أمر الاقتران — يولّد تحدّي تسجيل ويعرضه رمزَ QR في الطرفية.

    python -m app.mobile.pairing --backend http://100.x.y.z:8000

## لماذا أمرٌ لا نقطة نهاية

الخيار البديهي كان مساراً في الخادم يولّد التحدّي، محميّاً بفحص أن الطلب
جاء من `127.0.0.1`. وهو **حارس زائف** في هذه المعمارية تحديداً:

    الجوال ⇢ الشبكة الخاصة ⇢ وسيط يعيد التوجيه إلى 127.0.0.1:8000

الوسيط يُخفي مصدر الطلب، فكل طلب يصل إلى الخادم يبدو قادماً من الحلقة
المحلية — بما فيه طلب قادم من جهاز آخر على الشبكة الخاصة. ففحص عنوان المصدر
هنا يعطي إحساس أمان بلا أمان.

والأمر يحسم ذلك بلا التباس: **من يملك صدفةً على الخادم يستطيع توليد تحدٍّ،
ولا أحد سواه.** لا مسار شبكي يُهاجَم، ولا حارس يعتمد على عنوان قد يُزوَّر أو
يُخفيه وسيط.

## ما في الرمز

    الإصدار · عنوان الخادم · معرّف التحدّي · قيمة عشوائية · وقت الانتهاء

**ولا سرّ.** ويوجد اختبار يفحص أن الحمولة لا تحتوي أي اسم من
`NEVER_ON_DEVICE`. الرمز صالح دقيقتين، ويُستهلَك من أول مسح.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .security import (
    ENROLLMENT_CHALLENGE_TTL,
    NEVER_ON_DEVICE,
    QR_PAYLOAD_VERSION,
    MobileSecurityService,
)
from .store import MobileStateStore


def assert_payload_carries_no_secret(payload: dict) -> None:
    """
    حارس أخير قبل الطباعة. الفحص هنا لا في الاختبار وحده، لأن الاختبار
    يفحص ما كُتب والحارس يفحص ما **يُطبَع فعلاً**.
    """
    blob = json.dumps(payload, ensure_ascii=False)
    for name in NEVER_ON_DEVICE:
        if name in blob:
            raise SystemExit(f"⛔ حمولة الاقتران كانت ستحمل «{name}» — أُوقفت.")
    # حارس الشكل: لا حقل خارج الأربعة. حقلٌ إضافي هو المكان الذي يُهرَّب فيه
    # سرّ، فيُرفَض بوجوده لا باعترافه.
    if set(payload) != {"v", "b", "c", "e"}:
        raise SystemExit(f"⛔ حمولة الاقتران بحقول غير متوقَّعة: {sorted(payload)}")
    if payload["v"] != QR_PAYLOAD_VERSION:
        raise SystemExit("⛔ إصدار حمولة غير متوقَّع.")


def render_qr(text: str) -> str:
    """
    يرسم الرمز محارفَ في الطرفية.

    تُستورَد `segno` هنا لا في أعلى الملف: غيابها يجب أن يوقف **هذا الأمر
    وحده** برسالة مفهومة، لا أن يُسقط استيراد حزمة الجوال كلها فيمنع الخادم
    من الإقلاع.
    """
    try:
        import segno
    except ImportError:  # pragma: no cover - يعتمد على البيئة
        raise SystemExit(
            "⛔ حزمة segno غير مثبَّتة. ثبّتيها بـ:\n"
            "     pip install segno"
        )
    from io import StringIO

    buffer = StringIO()
    # `compact=True` يرسم وحدتين رأسياً في محرف واحد، فينصّف الارتفاع.
    # و`border=2` أدنى ما تقبله المواصفة عملياً لتمييز الرمز عن الخلفية.
    segno.make(text, error="m").terminal(out=buffer, border=2, compact=True)
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.mobile.pairing",
        description="توليد رمز اقتران لجهاز جوال واحد.",
    )
    parser.add_argument(
        "--backend", required=True,
        help="العنوان الذي يصل إليه **الجوال** — لا 127.0.0.1، فتلك تعني الجوال نفسه.",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help=(
            "اطبع الحمولة نصّاً بلا رمز ولا شرح. للمحاكي — لا كاميرا فيه، "
            "فتُنقَل الحمولة عبر الحافظة. **لا تُطبع في سجل ولا تُلصَق في صورة.**"
        ),
    )
    parser.add_argument(
        "--state", default=None,
        help="مسار ملف حالة الجوال (الافتراضي: data/mobile-state.json).",
    )
    args = parser.parse_args(argv)

    backend = args.backend.rstrip("/")
    if "127.0.0.1" in backend or "localhost" in backend:
        print(
            "⛔ عنوان الحلقة المحلية لا يصلح هنا.\n"
            "   الجوال سيفسّر 127.0.0.1 على أنه **الجوال نفسه** فلن يجد شيئاً.\n"
            "   استعملي عنوان الخادم على الشبكة الخاصة.",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(__file__).resolve().parents[3]
    state_path = Path(args.state) if args.state else repo_root / "data" / "mobile-state.json"

    service = MobileSecurityService(store=MobileStateStore(state_path))
    challenge = service.create_enrollment_challenge()
    payload = challenge.qr_payload(backend_url=backend)
    assert_payload_carries_no_secret(payload)

    text = json.dumps(payload, separators=(",", ":"))
    seconds = int(ENROLLMENT_CHALLENGE_TTL.total_seconds())

    # **الحمولة وحدها إلى المخرج القياسي.** تُوجَّه إلى الحافظة مباشرةً فلا
    # تمرّ بشاشة ولا سجل. والتحدّي نفسه لمرةٍ واحدة وبالعمر نفسه — لا مسار
    # موازٍ ولا صلاحيةٌ أطول.
    if args.raw:
        print(text)
        return 0

    # **تُمسح الشاشة أولاً.** رمزٌ سابق باقٍ في سجل الطرفية تلتقطه الكاميرا
    # بدل الجديد، فتُرفَض المحاولة بـ«منتهٍ أو مُستهلَك» والمالكة تظنّ أن
    # الرمز الجديد هو المرفوض. حدث ذلك فعلاً.
    print("\033[2J\033[H", end="")
    print(render_qr(text))
    print(f"  صالح {seconds} ثانية · لمرة واحدة · ينتهي {challenge.expires_utc:%H:%M:%S} UTC")
    print(f"  حجم الحمولة: {len(text)} محرفاً")
    print()
    print("  وجّهي كاميرا التطبيق إلى الرمز أعلاه.")
    print("  ولو انتهى قبل أن تمسحيه، أعيدي تشغيل هذا الأمر — لا ضرر.")
    print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
