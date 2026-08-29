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

from .security import ENROLLMENT_CHALLENGE_TTL, NEVER_ON_DEVICE, MobileSecurityService
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
    if payload.get("contains_secret") is not False:
        raise SystemExit("⛔ الحمولة لا تُعلن خلوّها من الأسرار.")


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
    segno.make(text, error="m").terminal(out=buffer, border=2)
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

    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    seconds = int(ENROLLMENT_CHALLENGE_TTL.total_seconds())

    print()
    print(render_qr(text))
    print(f"  صالح {seconds} ثانية · لمرة واحدة · ينتهي {challenge.expires_utc:%H:%M:%S} UTC")
    print(f"  الخادم: {backend}")
    print()
    print("  امسحيه من شاشة «لا جهاز مسجَّل» في التطبيق.")
    print("  ولو انتهى قبل أن تمسحيه، أعيدي تشغيل هذا الأمر — لا ضرر.")
    print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
