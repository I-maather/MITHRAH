"""
مسبار وحدة مسافة الوقف — **أمرٌ معلَّق واحد على Demo، ثم يُلغى**.

    cd /opt/mathrah/backend
    sudo -u mathrah /opt/mathrah/.venv/bin/python -m app.diagnostics.stop_distance_probe \\
        --approve "أوافق على أمر تجريبي واحد"

## السؤال الذي يجيبه

الوسيط يقبل حقل `stopDistance` ولم يُثبَت بعد **أهو بالنقاط أم بفرق السعر
الخام**. وخطأٌ بمعامل 10000 هنا يعني وقفاً أبعد بعشرة آلاف ضعف — أي بلا وقف.
ولذلك يرفض `place_order` كل إرسال ما دام `STOP_DISTANCE_UNIT_PROVEN = False`.

وهذا المسبار هو الطريق الوحيد لقلب ذلك الثابت **بقياس** لا بتخمين.

## لماذا أمرٌ معلَّق لا مركز

المركز يُفتح بسعر السوق فيصير مالاً في السوق فوراً. والأمر المعلَّق يوضع
**بعيداً عن السوق فلا يُنفَّذ أصلاً** — ومع ذلك يُعيد الوسيط له `stopLevel`
محسوباً من `stopDistance` الذي أرسلناه. فنقرأ الجواب بلا أن ندخل السوق.

أقلّ المسارين خطراً، وكلاهما يعطي الجواب نفسه.

## الأسوار — وكلّها تُفحَص قبل أي نداء

  ١  **Demo حصراً.** أي بيئة أخرى ⇒ توقّف قبل فتح جلسة.
  ٢  **موافقة نصّية حرفية** على سطر الأوامر. لا تشغيل بالخطأ.
  ٣  **أمرٌ واحد** بأصغر كمية يقبلها الوسيط.
  ٤  **بعيدٌ عن السوق** بنسبة معلومة ⇒ لا ينفَّذ.
  ٥  **يُلغى في `finally`** — حتى لو انفجر ما بينهما.
  ٦  **لا يقلب الثابت.** يطبع القياس، والقلب قرارٌ بعده بيدٍ بشرية.

## ما لا يفعله

لا يفتح مركزاً، ولا يلمس الحساب الحقيقي، ولا يغيّر إعداداً، ولا يطبع سرّاً.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

APPROVAL_PHRASE = "أوافق على أمر تجريبي واحد"

#: بُعد الأمر المعلَّق عن السوق. 5٪ على زوج عملات مسافةٌ لا تُقطع في دقائق.
AWAY_FROM_MARKET = Decimal("0.05")

#: مسافة الوقف المُرسَلة. رقمٌ لا يشبه شيئاً آخر في الحمولة كي لا يلتبس
#: مصدره في الاستجابة.
PROBE_STOP_DISTANCE = Decimal("37")

OK, BAD, WARN, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser(description="إثبات وحدة stopDistance بأمر معلَّق واحد")
    ap.add_argument("--approve", default="", help=f"العبارة المطلوبة: «{APPROVAL_PHRASE}»")
    ap.add_argument("--epic", default="EURUSD")
    a = ap.parse_args()

    if a.approve.strip() != APPROVAL_PHRASE:
        print(
            f"{BAD}⛔ لا تشغيل بلا موافقة صريحة.{END}\n"
            f"   أعيدي الأمر مع:  --approve \"{APPROVAL_PHRASE}\"\n"
            f"{DIM}   هذا المسبار يرسل أمراً حقيقياً إلى الوسيط — معلَّقاً وعلى Demo،\n"
            f"   لكنه إرسال. فلا يقع بالخطأ.{END}",
            file=sys.stderr,
        )
        return 2

    from app.brokers.capital.endpoints import (
        PATH_WORKING_ORDERS,
        CapitalEnvironment,
    )
    from app.brokers.capital.safety import ExecutionLock
    from app.brokers.factory import build_capital_adapter
    from app.clock import now_utc
    from app.config import get_settings
    from app.contracts import Side
    from app.money import D
    from app.secretstore.provider import build_secret_provider

    settings = get_settings()

    # ---- السور الأول: البيئة مثبَّتة على Demo في الكود لا في الإعداد ------
    #
    # المسبار **يفرض** Demo ولا يقرأ `BROKER_MODE` أصلاً: بيئةٌ تُقرأ من
    # إعدادٍ يمكن أن يتغيّر ليست سوراً — والسور ما لا يُغيَّر من خارج الملف.
    #
    # وحسابا Demo والحقيقي عند كابيتال **حسابان منفصلان بنفس الاعتمادات**،
    # وقد قِيس ذلك: `capital-auth-probe` نجح على مضيف Demo بالأسرار نفسها
    # التي تخدم الحقيقي. فلا حاجة لتبديل وضع الخادم — وتبديلُه كان سيقطع
    # قراءة السوق الحيّة عن التطبيق بلا مقابل.
    environment = CapitalEnvironment.DEMO
    print(f"{DIM}   البيئة مثبَّتة على Demo في الكود — إعداد الخادم لا يُقرأ هنا.{END}")

    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)

    # ---- فتح قفل التنفيذ لهذه العملية وحدها ------------------------------
    # القفل يُفتح **في الذاكرة ولهذا التشغيل فقط**، بمرجع موافقة مكتوب.
    # ولا يُمسّ ملف ولا متغيّر بيئة: انتهاء العملية يعيد كل شيء مقفلاً.
    lock = ExecutionLock.locked().authorise(
        owner_authorization_reference="D13/2026-08-31",
        reason_ar="إثبات وحدة مسافة الوقف بأمر معلَّق واحد على Demo، ثم يُلغى.",
        at=now_utc(),
    )
    adapter = build_capital_adapter(environment, secrets=secrets, execution_lock=lock)
    try:
        adapter.connect()
    except Exception as exc:  # noqa: BLE001
        # رسالةٌ تُقرأ بدل أثر استدعاءات. المسبار أداةُ تشخيص، وأداةٌ تنهار
        # بأثرٍ خام تُضيف عطلاً إلى العطل الذي جاءت تقيسه.
        print(f"\n{BAD}⛔ تعذّر الاتصال بحساب Demo.{END}", file=sys.stderr)
        print(f"   {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"\n{OK}✅{END} متصل — {adapter.name}")
    if adapter.is_live:
        print(f"{BAD}⛔ المحوّل يقول إنه حقيقي. توقّف.{END}", file=sys.stderr)
        return 3

    details = adapter.get_instrument_details(a.epic)
    pip = details.pip_size
    size = details.min_quantity
    if pip is None or size is None:
        print(f"{BAD}⛔ الوسيط لم يُعطِ pip_size أو الكمية الدنيا — لا قياس بلا مرجع.{END}",
              file=sys.stderr)
        return 1

    quote = adapter.get_market_data(a.epic)
    market = quote.ask
    if market is None or market <= 0:
        print(f"{BAD}⛔ لا سعر حالي — السوق مغلق أو لا بيانات.{END}", file=sys.stderr)
        return 1

    # شراءٌ معلَّق **تحت** السوق بكثير: لا يُنفَّذ حتى يهبط السعر 5٪.
    # التقريب إلى دقّة السعر نفسها: سعرٌ بخانات أكثر مما يقبله الوسيط يُرفض.
    level = (market * (Decimal("1") - AWAY_FROM_MARKET)).quantize(market)

    print(f"{DIM}   السوق {market} · الأمر المعلَّق عند {level} "
          f"({AWAY_FROM_MARKET:.0%} تحته) · الكمية {size}{END}")
    print(f"{DIM}   نرسل stopDistance = {PROBE_STOP_DISTANCE} ونقرأ ما يعيده الوسيط.{END}\n")

    payload = {
        "epic": a.epic,
        "direction": Side.BUY.value,
        "size": float(size),
        "level": float(level),
        "type": "LIMIT",
        "stopDistance": float(PROBE_STOP_DISTANCE),
    }

    deal_id = None
    try:
        body = adapter._post(PATH_WORKING_ORDERS, payload)  # noqa: SLF001
        reference = body.get("dealReference")
        if not reference:
            print(f"{BAD}⛔ استجابة بلا dealReference — لا يُثبَت ما حدث.{END}", file=sys.stderr)
            return 1

        state, confirmation = adapter.poll_confirmation(str(reference))
        print(f"{DIM}   التأكيد: {getattr(state, 'name', state)}{END}")
        if confirmation is None or not getattr(confirmation, "accepted", False):
            print(f"{WARN}○ رفض الوسيط الأمر المعلَّق — لا قياس، ولا شيء يُلغى.{END}")
            print(f"{DIM}   السبب من الوسيط: {getattr(confirmation, 'reason', '—')}{END}\n")
            return 1

        deal_id = confirmation.deal_id

        # ---- القياس ------------------------------------------------------
        orders = adapter._get(PATH_WORKING_ORDERS)  # noqa: SLF001
        stop_level = None
        for row in (orders.get("workingOrders") or []):
            order = row.get("workingOrderData", row)
            if str(order.get("dealId")) == str(deal_id):
                stop_level = order.get("stopLevel")
                break

        if stop_level is None:
            print(f"{WARN}○ لم يُعِد الوسيط stopLevel للأمر — لا قياس.{END}")
            return 1

        stop_level = D(str(stop_level))
        gap = abs(level - stop_level)
        as_pips = PROBE_STOP_DISTANCE * pip        # لو كانت الوحدة نقاطاً
        as_raw = PROBE_STOP_DISTANCE                # لو كانت فرق سعر خام

        print(f"\n\033[1m▸ القياس\033[0m\n")
        print(f"  سعر الأمر         {level}")
        print(f"  stopLevel العائد  {stop_level}")
        print(f"  الفرق             {gap}")
        print(f"  لو الوحدة نقاط    {as_pips}")
        print(f"  لو الوحدة سعر خام {as_raw}\n")

        tolerance = pip * Decimal("2")
        if abs(gap - as_pips) <= tolerance:
            print(f"{OK}✅ الوحدة **نقاط** (pips).{END}")
            print(f"{DIM}   الفرق يطابق stopDistance × pip_size ضمن نقطتين.{END}")
            verdict = "PIPS"
        elif abs(gap - as_raw) <= tolerance:
            print(f"{OK}✅ الوحدة **فرق سعر خام**.{END}")
            verdict = "RAW_PRICE"
        else:
            print(f"{BAD}⛔ الفرق لا يطابق أياً من الاحتمالين.{END}")
            print(f"{DIM}   لا يُقلَب الثابت على قياسٍ غامض — أعيدي بمسافة أخرى.{END}")
            verdict = "UNKNOWN"

        print(f"\n{DIM}   ولا يُقلَب `STOP_DISTANCE_UNIT_PROVEN` من هنا.{END}")
        if verdict == "PIPS":
            print(f"{DIM}   الحساب في `place_order` يقسم على pip_size — وهو موافقٌ لهذا"
                  f" القياس.{END}")
            print(f"{DIM}   فالقلب إلى True قرارٌ يُتَّخذ الآن بيدٍ بشرية.{END}")
        elif verdict == "RAW_PRICE":
            print(f"{BAD}   والحساب في `place_order` يقسم على pip_size — أي **خاطئ**"
                  f" لهذه الوحدة.{END}")
            print(f"{BAD}   يُصحَّح الحساب أوّلاً، ثم يُعاد هذا المسبار.{END}")
        print()
        return 0 if verdict != "UNKNOWN" else 1

    finally:
        # ---- السور الخامس: يُلغى مهما وقع ---------------------------------
        if deal_id:
            print(f"{DIM}   إلغاء الأمر {deal_id} …{END}")
            try:
                result = adapter.cancel_order(str(deal_id))
                print(f"{OK}✅{END} أُلغي — الحالة {result.status.value}")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"{BAD}⛔ تعذّر الإلغاء التلقائي: {type(exc).__name__}: {exc}{END}\n"
                    f"{BAD}   ألغيه بنفسك من موقع كابيتال — المعرّف {deal_id}.{END}",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    raise SystemExit(main())
