"""
دورة كاملة على الحساب التجريبي — **صفقة واحدة تُفتح وتُغلق**.

    cd /opt/mathrah/backend
    sudo -u mathrah /opt/mathrah/.venv/bin/python -m app.diagnostics.demo_round_trip \\
        --approve "أوافق على صفقة تجريبية واحدة"

## السؤال الذي يجيبه

**هل الآلة تعمل من طرفها إلى طرفها؟** وهو سؤالٌ مستقلٌّ تماماً عن «هل توجد
حافّة». الأوّل هندسيّ ويُجاب بصفقة واحدة؛ والثاني تجريبيّ ويحتاج شهوداً
أطول. وخلطُهما هو ما يجعل نظاماً يُطلَق قبل أن يُثبت أيٌّ منهما.

فالإشارة هنا **مكتوبة بيد** لا مولَّدة من استراتيجية: الغرض إثبات الأنبوب،
لا إثبات القرار. ولا تُقرأ نتيجة هذه الصفقة ربحاً ولا خسارة — تُقرأ
«وصلت أو لم تصل».

## المسار الذي يُثبَت

    بناء النية ⇐ إرسال ⇐ تأكيد (`GET /confirms`) ⇐ مطابقة الأداة والاتجاه
    والكمية ⇐ ظهور المركز في القائمة ⇐ إغلاق ⇐ تأكيد ⇐ **اختفاؤه من القائمة**

ثمانية مواضع، كلٌّ منها كان يمكن أن يكذب. وكلها تُطبع خطوةً خطوة.

## الأسوار

  ١  Demo مثبَّتة في الكود — لا تُقرأ من إعداد.
  ٢  موافقة نصّية حرفية.
  ٣  أصغر كمية يقبلها الوسيط.
  ٤  وقفٌ وهدفٌ إلزاميان — لا مسار لأمرٍ بلا وقف.
  ٥  **يُغلق في `finally`**، وتعذُّر الإغلاق يصرخ بالمعرّف ولا يُبتلع.
  ٦  لا يُغيَّر ثابتٌ ولا إعداد.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

APPROVAL_PHRASE = "أوافق على صفقة تجريبية واحدة"

#: مسافة الوقف والهدف بالنقاط. الهدف ضعف الوقف — نسبةٌ معقولة، والغرض
#: ليس الربح بل أن يقبل الوسيط الحمولة ويعيد مستويات نقارنها.
#: مسافة الوقف والهدف **بوحدة السعر** — وحدة أمر الوسيط.
#:
#: ## لماذا نزلت من 150 نقطة إلى 20
#:
#: كانت `0.0150` لأن حدّ الوسيط قُرئ `0.01` **سعراً** = ١٠٠ نقطة، فلزم
#: وقفٌ أوسع منه. والحدُّ الحقيقي `{"unit":"PERCENTAGE","value":0.01}` =
#: ٠٫٠١٪ من السعر = **١٫١٦ نقطة** (قياسٌ مباشر 2026-09-03).
#:
#: وأثرُ الرقم القديم على صفقة التشغيل مباشر: وقفٌ ١٥٠ نقطة عند الكمية
#: الدنيا يعرّض **١٫٥٠ دولاراً** — أي الحدّ الصلب للصفقة كلَّه، على صفقةٍ
#: غرضها إثبات الأنبوب لا الربح. و٢٠ نقطة تعرّض نحو ٠٫٢٢ دولار وتبقى فوق
#: حدّ الوسيط بسبعة عشر ضعفاً.
#:
#: **وأصغرُ ما يثبت الأنبوب هو الصحيح**: كلفةُ الاختبار ليست جزءاً من
#: نتيجته.
STOP_DISTANCE = Decimal("0.0020")
TARGET_DISTANCE = Decimal("0.0040")

OK, BAD, WARN, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def step(n: int, text: str) -> None:
    print(f"\n\033[1m  {n} · {text}\033[0m")


def main() -> int:
    ap = argparse.ArgumentParser(description="دورة كاملة على Demo: فتح ثم إغلاق")
    ap.add_argument("--approve", default="", help=f"العبارة المطلوبة: «{APPROVAL_PHRASE}»")
    ap.add_argument("--epic", default="EURUSD")
    a = ap.parse_args()

    if a.approve.strip() != APPROVAL_PHRASE:
        print(
            f"{BAD}⛔ لا تشغيل بلا موافقة صريحة.{END}\n"
            f'   أعيدي الأمر مع:  --approve "{APPROVAL_PHRASE}"\n'
            f"{DIM}   هذا يفتح مركزاً حقيقياً على الحساب التجريبي ثم يغلقه.{END}",
            file=sys.stderr,
        )
        return 2

    from app.brokers.capital.adapter import STOP_DISTANCE_UNIT
    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.capital.errors import CapitalExecutionUncertain
    from app.brokers.capital.safety import ExecutionLock
    from app.brokers.factory import build_capital_adapter
    from app.clock import now_utc
    from app.config import get_settings
    from app.contracts import OrderIntent, OrderType, Side
    from app.money import D
    from app.secretstore.provider import build_secret_provider

    if STOP_DISTANCE_UNIT != "PRICE":
        print(
            f"{BAD}⛔ وحدة مسافة الوقف غير معروفة ({STOP_DISTANCE_UNIT}).{END}\n"
            f'   شغّلي أوّلاً:  python -m app.diagnostics.stop_distance_probe --approve "…"',
            file=sys.stderr,
        )
        return 3

    settings = get_settings()
    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)

    lock = ExecutionLock.locked().authorise(
        owner_authorization_reference="D13/2026-09-01",
        reason_ar="صفقة تجريبية واحدة على Demo لإثبات المسار كاملاً، ثم تُغلق.",
        at=now_utc(),
    )
    adapter = build_capital_adapter(
        CapitalEnvironment.DEMO, secrets=secrets, execution_lock=lock
    )

    step(1, "الاتصال بحساب Demo")
    try:
        adapter.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD}⛔ تعذّر الاتصال: {type(exc).__name__}: {exc}{END}", file=sys.stderr)
        return 1
    if adapter.is_live:
        print(f"{BAD}⛔ المحوّل يقول إنه حقيقي. توقّف.{END}", file=sys.stderr)
        return 3
    print(f"{OK}✅{END} {adapter.name}")

    step(2, "قراءة الأداة والسعر")
    details = adapter.get_instrument_details(a.epic)
    quote = adapter.get_market_data(a.epic)
    pip = details.pip_size
    size = details.min_quantity
    if pip is None or size is None or details.min_stop_distance is None:
        print(
            f"{BAD}⛔ بيانات الأداة ناقصة — لا إرسال بلا مرجع:{END}\n"
            f"   pip_size={pip} · min_quantity={size} · "
            f"min_stop_distance={details.min_stop_distance}",
            file=sys.stderr,
        )
        return 1
    entry = quote.ask
    # **الحدُّ يُحلّ إلى وحدة السعر قبل أن يُقارَن.** كان هذا السطر يقارن
    # `0.0020` بـ`0.01` مباشرةً، و`0.01` عند هذا الوسيط
    # `{"unit":"PERCENTAGE","value":0.01}` — أي ٠٫٠١٪ من السعر = ١٫١٦ نقطة
    # على EURUSD، لا ١٠٠ نقطة. فكان يرفض وقفاً يفوق الحدّ الحقيقي
    # سبعة عشر ضعفاً. وهذا آخرُ موضعٍ بقي فيه الخطأ الأصلي بعد
    # إصلاح المحوّل ومحرّك المخاطر — والتشخيصُ أولى المواضع التي
    # يجب ألّا يكذب فيها القياس، لأنّه المكان الذي نحتكم إليه حين نشكّ في البقية.
    min_stop = details.min_stop_price_at(entry)
    if details.min_stop_spec_unresolved or min_stop is None:
        print(
            f"{BAD}⛔ حدُّ الوقف عند الوسيط غير قابل للحلّ إلى وحدة السعر:{END}\n"
            f"   القيمة={details.min_stop_distance} · "
            f"الوحدة={details.min_stop_distance_unit!r} · المرجع={entry}\n"
            f"   لا أُرسل أمراً بحدٍّ لا أعرف وحدته.",
            file=sys.stderr,
        )
        return 1
    if STOP_DISTANCE < min_stop:
        print(
            f"{BAD}⛔ وقفنا {STOP_DISTANCE} دون حدّ الوسيط المحلول {min_stop} "
            f"(من {details.min_stop_distance} "
            f"{details.min_stop_distance_unit} عند {entry}) — سيُرفَض.{END}",
            file=sys.stderr,
        )
        return 1
    print(
        f"{DIM}   حدُّ الوسيط {details.min_stop_distance} "
        f"{details.min_stop_distance_unit} ⇐ {min_stop} بوحدة السعر · "
        f"ووقفنا {STOP_DISTANCE} فوقه{END}"
    )
    stop = entry - STOP_DISTANCE
    target = entry + TARGET_DISTANCE
    print(f"{DIM}   السعر {entry} · الكمية {size} · وقف {stop} · هدف {target}{END}")

    step(3, "بناء النية — **بيدٍ لا من استراتيجية**")
    at = now_utc()
    intent = OrderIntent(
        idempotency_key=f"demo-round-trip-{int(at.timestamp())}",
        client_order_id=f"demo-{int(at.timestamp())}",
        symbol=a.epic,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=size,
        limit_price=None,
        stop_price=stop,
        take_profit_price=target,
        expected_fill_price=entry,
        max_slippage_abs=D(5) * pip,
        strategy_name="MANUAL_PIPELINE_PROOF",
        strategy_version="0.0.0",
        risk_amount_usd=(STOP_DISTANCE / pip) * pip * size,
        commission_estimate_usd=D("0"),
        exit_plan_ar="إثبات مسار: تُغلق فور التأكيد. ليست قراراً تداولياً.",
        instrument_snapshot={"guaranteed_stop": False},
        created_at_utc=at,
    )
    print(f"{OK}✅{END} النية جاهزة — الاستراتيجية «{intent.strategy_name}»")

    # **يُسجَّل أنّ الإرسال وقع، قبل أن نعرف نتيجته.**
    #
    # كان `deal_id` وحده يقرّر ما يفعله `finally`، وهو لا يُملأ إلا بعد أن
    # تعود `place_order` سالمة. فلمّا رفعت غموضاً في 2026-09-01 قال `finally`
    # «لا مركز فُتح» — وكان المركز مفتوحاً. جملةٌ تطمئن بلا حقّ.
    sent = False
    deal_ids: tuple[str, ...] = ()
    deal_id = None
    try:
        step(4, "الإرسال ⇐ التأكيد ⇐ المطابقة")
        sent = True
        try:
            order = adapter.place_order(intent)
        except CapitalExecutionUncertain as exc:
            deal_ids = exc.deal_ids
            print(f"{BAD}⛔ غموضٌ في التنفيذ: {exc}{END}", file=sys.stderr)
            raise
        print(f"{OK}✅{END} الحالة {order.status.value} · "
              f"المعرّف {order.broker_order_id} · التنفيذ {order.average_fill_price}")

        step(5, "هل ظهر المركز فعلاً في القائمة؟")
        positions = {p.deal_id: p for p in adapter.list_positions()}
        deal_id = order.broker_order_id
        position = positions.get(deal_id)
        if position is None:
            print(f"{BAD}⛔ قال الوسيط إن الأمر نُفِّذ، والمركز غير موجود في القائمة.{END}")
            print(f"{BAD}   لا يُعاد الإرسال — افحصي حسابك بنفسك.{END}", file=sys.stderr)
            return 1
        print(f"{OK}✅{END} موجود · وقفه {position.stop_level} · هدفه {position.profit_level}")

        # **الحماية عند الوسيط لا عندنا** — وهذا ما يُثبَت هنا: لو مات
        # الخادم الآن لبقي الوقف والهدف قائمين عند كابيتال.
        if position.stop_level is None:
            print(f"{WARN}⚠️  المركز بلا وقف عند الوسيط — وهذا خطر يُبلَّغ.{END}")

        return 0

    finally:
        step(6, "الإغلاق ⇐ التأكيد ⇐ المطابقة")

        # لو غمض التنفيذ، تُقرأ القائمة ويُبحث عن مركزٍ بأيٍّ من المعرّفات
        # المعروفة. **قراءةٌ لا إرسال** — آمنة تماماً، ولا تفتح شيئاً.
        if deal_id is None and deal_ids:
            print(f"{DIM}   بحثٌ عن مركزٍ بالمعرّفات: {'، '.join(deal_ids)}{END}")
            try:
                found = next(
                    (p for p in adapter.list_positions() if str(p.deal_id) in deal_ids),
                    None,
                )
                deal_id = found.deal_id if found else None
            except Exception as exc:  # noqa: BLE001
                print(f"{BAD}⛔ تعذّرت قراءة المراكز: {type(exc).__name__}: {exc}{END}",
                      file=sys.stderr)

        if deal_id is None:
            if sent:
                # **الفرق بين «لم يُرسَل» و«أُرسل ولم أتحقّق».**
                print(f"{BAD}⚠️  أُرسل الأمر ولم أتمكّن من تحديد مركزه.{END}",
                      file=sys.stderr)
                print(f"{BAD}   افحصي الحساب بنفسك:{END}", file=sys.stderr)
                print(f"{BAD}   python -m app.diagnostics.demo_positions{END}",
                      file=sys.stderr)
            else:
                print(f"{DIM}   لم يقع إرسال — لا شيء يُغلق.{END}")
        else:
            try:
                closed = adapter.close_position(str(deal_id))
                print(f"{OK}✅{END} أُغلق · الحالة {closed.status.value} · "
                      f"السعر {closed.average_fill_price}")
                remaining = {p.deal_id for p in adapter.list_positions()}
                if deal_id in remaining:
                    print(f"{BAD}⛔ ما زال في القائمة بعد إغلاقٍ «ناجح».{END}",
                          file=sys.stderr)
                else:
                    print(f"{OK}✅{END} اختفى من القائمة — الدورة كاملة.")
            except Exception as exc:  # noqa: BLE001
                print(
                    f"{BAD}⛔ تعذّر الإغلاق: {type(exc).__name__}: {exc}{END}\n"
                    f"{BAD}   أغلقيه بنفسك من موقع كابيتال — المعرّف {deal_id}.{END}",
                    file=sys.stderr,
                )
        print()


if __name__ == "__main__":
    raise SystemExit(main())
