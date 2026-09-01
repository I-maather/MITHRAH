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
#: مسافة الوقف والهدف **بوحدة السعر** — وحدة الوسيط المقيسة.
#: 0.0150 = 150 نقطة على اليورو/دولار، فوق حدّ الوسيط 0.01.
STOP_DISTANCE = Decimal("0.0150")
TARGET_DISTANCE = Decimal("0.0300")

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
    if STOP_DISTANCE < details.min_stop_distance:
        print(
            f"{BAD}⛔ وقفنا {STOP_DISTANCE} دون حدّ الوسيط "
            f"{details.min_stop_distance} (كلاهما بوحدة السعر) — سيُرفَض.{END}",
            file=sys.stderr,
        )
        return 1
    entry = quote.ask
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

    deal_id = None
    try:
        step(4, "الإرسال ⇐ التأكيد ⇐ المطابقة")
        order = adapter.place_order(intent)
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
        if deal_id is None:
            print(f"{DIM}   لا مركز فُتح — لا شيء يُغلق.{END}")
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
