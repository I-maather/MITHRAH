"""
فحص حيّ للمزوّدين — **نداء واحد لكل واحد، قراءة فقط**.

    /opt/mathrah/.venv/bin/python -m app.diagnostics.provider_smoke

## لماذا

`live_eligible_by_providers: true` تعني **«المفتاح موجود»**، لا «الخطة
تسمح» ولا «البيانات تصل». والفرق يظهر عند أوّل قرار حقيقي: مزوّدٌ مُعدّ
يرجع منعاً بدل بيانات، فيمتنع النظام عن التداول والمالكة ترى «كل شيء مُعدّ»
فتحتار أين الخلل.

فهذا يسأل كل مزوّد سؤاله الحقيقي مرّة واحدة، ويقول ما وصل بالضبط.

## ما لا يفعله

لا يرسل أمراً، ولا يفتح قفلاً، ولا يطبع مفتاحاً. وأي إخفاق يُعرض بنوعه
واسم الاستثناء — لا يُبتلع ولا يُترجم إلى «فشل» واحد يضيّع التشخيص.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone

OK, BAD, WARN, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def line(label: str, mark: str, detail: str) -> None:
    print(f"  {mark} {label:<26} {clean(detail)}")


def clean(text: str) -> str:
    """
    يُخرج نصّاً صالحاً لسطرٍ عربي واحد.

    صفحة nginx خام طُبعت داخل سطر عربي فتشابكت الاتجاهات وصار السطر غير
    مقروء: «<hr><center>nginx</cFound</h1></center>d>لتقويم أعاد رمز 404».
    والتشخيص الذي لا يُقرأ ليس تشخيصاً.

    فتُنزع الوسوم ويُضغط الفراغ. وعزلُ الاتجاه يقع عند **مصدر** المقتطف
    اللاتيني لا هنا: عزلُ السطر كلّه كان سيفرض اتجاه اليسار على جملةٍ عربية.
    """
    return " ".join(re.sub(r"<[^>]*>", " ", text).split())[:160]


def main() -> int:
    from app.api.state import build_provider_registry
    from app.brokers.factory import build_broker
    from app.config import get_settings
    from app.secretstore.provider import build_secret_provider

    settings = get_settings()
    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)
    broker = build_broker(settings, secrets=secrets)
    try:
        broker.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"{WARN}⚠️  تعذّر الاتصال بالوسيط: {type(exc).__name__}{END}")

    registry = build_provider_registry(secrets, broker)
    now = datetime.now(timezone.utc)
    failures = 0

    print(f"\n\033[1m▸ المزوّدون — نداء واحد لكل واحد\033[0m\n")

    # ---- التقويم الاقتصادي ------------------------------------------------
    # التقويم يُجلب بمهمة مجدولة داخل الخدمة، ولا مجدول هنا. فيُطلب الجلب
    # صراحةً — وإلا لقال المسبار «غير مُعدّ» عن مزوّدٍ سليم لم يُسأل بعد.
    p = registry.calendar
    if not p.configured and hasattr(p, "refresh"):
        p.refresh()
    if not p.configured:
        note = getattr(p, "note_ar", "") or "غير مُعدّ"
        line("التقويم الاقتصادي", f"{WARN}○{END}", f"غير مُعدّ — {note}")
    else:
        try:
            events = p.events(
                currencies=["EUR", "USD"],
                window_start_utc=now,
                window_end_utc=now + timedelta(days=2),
            )
            n = len(tuple(events))
            line("التقويم الاقتصادي", f"{OK}✅{END}", f"{n} حدثاً خلال يومين · {p.name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            line("التقويم الاقتصادي", f"{BAD}⛔{END}", f"{type(exc).__name__}: {exc}")

    # ---- الأخبار المتحقَّقة -------------------------------------------------
    p = registry.news
    if not p.configured:
        line("الأخبار المتحقَّقة", f"{WARN}○{END}", "غير مُعدّ")
    else:
        try:
            items = p.news(
                currencies=["EUR", "USD"], since_utc=now - timedelta(days=1), now_utc=now
            )
            n = len(tuple(items))
            line("الأخبار المتحقَّقة", f"{OK}✅{END}", f"{n} خبراً خلال يوم · {p.name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            line("الأخبار المتحقَّقة", f"{BAD}⛔{END}", f"{type(exc).__name__}: {exc}")

    # ---- البيانات الكلّية ---------------------------------------------------
    p = registry.macro
    # المفاتيح من المزوّد نفسه لا من ذاكرتي. سؤالٌ بمفتاحٍ مخترع
    # (`EUR_POLICY_RATE`) يعيد `UNKNOWN` بحقّ، ويُقرأ هنا «صفر من سلسلتين» —
    # أي عطلٌ مُعلَن عن مزوّد سليم.
    keys = list(getattr(p, "known_series_keys", ()) or ())[:2]
    if not p.configured:
        line("البيانات الكلّية", f"{WARN}○{END}", "غير مُعدّ")
    elif not keys:
        line("البيانات الكلّية", f"{WARN}○{END}", f"لا يعلن مفاتيحه · {p.name}")
    else:
        try:
            series = p.series(keys=keys, as_of_utc=now)
            got = [k for k, v in series.items() if getattr(v, "known", False)]
            mark = f"{OK}✅{END}" if got else f"{WARN}○{END}"
            detail = f"{len(got)} من {len(series)} سلسلة · {p.name}"
            if not got:
                # سببُ الصمت يُقال. «صفر» بلا سبب يُرسل المالكة تبحث في السجلات.
                first = next(iter(series.values()), None)
                if first is not None and first.note_ar:
                    detail += f" · {first.note_ar}"
            line("البيانات الكلّية", mark, detail)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            line("البيانات الكلّية", f"{BAD}⛔{END}", f"{type(exc).__name__}: {exc}")

    # ---- بيانات السوق -------------------------------------------------------
    p = registry.market_data
    if not p.configured:
        line("بيانات السوق", f"{WARN}○{END}", "غير مُعدّ — الوسيط بلا جلسة")
    else:
        try:
            from app.intelligence.snapshot import Timeframe

            series = p.candles(
                instrument="EURUSD", timeframe=Timeframe.H1, count=50, as_of_utc=now
            )
            n = len(series.candles)
            mark = f"{OK}✅{END}" if n >= 20 else f"{WARN}○{END}"
            detail = f"{n} شمعة ساعية · {p.name}"
            if series.note_ar:
                detail += f" · {series.note_ar}"
            line("بيانات السوق", mark, detail)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            line("بيانات السوق", f"{BAD}⛔{END}", f"{type(exc).__name__}: {exc}")

    # المزوّد الإلزامي غير المُعدّ **إخفاق**، لا حالةٌ محايدة.
    #
    # كانت الخلاصة تقول «كل مزوّد مُعدّ أعطى بيانات» وتخرج بصفر بينما التقويم
    # — وهو حارسٌ إلزامي — ميّت. الجملة صحيحة حرفياً وتُقرأ «كل شيء تمام»،
    # وهذا بالضبط صنف العطل الذي بُني هذا المسبار لكشفه: شيءٌ يُعرَض سليماً
    # ولم يُقَس من مصدره. ومسبارٌ يطمئن كذباً أسوأ من لا مسبار.
    missing = registry.missing_mandatory()
    print()
    if missing:
        names = "، ".join(k.value for k in missing)
        print(f"{BAD}⛔ مزوّد إلزامي غير مُعدّ: {names}{END}")
    if failures:
        print(f"{BAD}⛔ {failures} مزوّداً أخفق.{END}")
    if missing or failures:
        print(f"{DIM}   النظام سيمتنع عن التداول — وهذا صحيح.{END}\n")
        return 1
    print(f"{OK}✅ كل مزوّد إلزامي مُعدّ وأعطى بيانات.{END}")
    print(f"{DIM}   لم يُرسل أمر، ولم يُفتح قفل.{END}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
