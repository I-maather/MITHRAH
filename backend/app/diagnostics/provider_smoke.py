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

import sys
from datetime import datetime, timedelta, timezone

OK, BAD, WARN, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def line(label: str, mark: str, detail: str) -> None:
    print(f"  {mark} {label:<26} {detail}")


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
    p = registry.calendar
    if not p.configured:
        line("التقويم الاقتصادي", f"{WARN}○{END}", "غير مُعدّ")
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
    if not p.configured:
        line("البيانات الكلّية", f"{WARN}○{END}", "غير مُعدّ")
    else:
        try:
            series = p.series(keys=["EUR_POLICY_RATE", "US_POLICY_RATE"], as_of_utc=now)
            got = [k for k, v in series.items() if getattr(v, "value", None) is not None]
            mark = f"{OK}✅{END}" if got else f"{WARN}○{END}"
            line("البيانات الكلّية", mark, f"{len(got)} من {len(series)} سلسلة · {p.name}")
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

    print()
    if failures:
        print(f"{BAD}⛔ {failures} مزوّداً أخفق. النظام سيمتنع عن التداول — وهذا صحيح.{END}\n")
        return 1
    print(f"{OK}✅ كل مزوّد مُعدّ أعطى بيانات.{END}")
    print(f"{DIM}   لم يُرسل أمر، ولم يُفتح قفل.{END}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
