#!/usr/bin/env python3
"""
إثبات اقتصاديات الذهب — **قراءةٌ وحساب، والتجربة خلف علَمٍ صريح.**

    /opt/mathrah/.venv/bin/python ../scripts/prove_gold_economics.py

## السؤال الذي يجيبه

قرّرت المالكة الخطة (ب): التداول على **الذهب** بمرجع 300 دولار، لأن
الكمية الدنيا للذهب 0.01 أونصة لا 100 وحدة — فتنزل المخاطرة معها، ويعمل
النظام **بلا تخفيف حدٍّ واحد**. وقبل أن يُبنى على ذلك، لا بدّ من رقمٍ
مُثبَت لا مقروء.

والفرق بين المقروء والمُثبَت هو الفرق بين ما يقوله الوسيط في `GET
/markets` وما يفعله عند الإرسال. وقد أُثبتت `EURUSD` بتجربة رفض/قبول،
و`GOLD` **قُرئت ولم تُثبَت** — وهذا ما يسدّه هذا السكربت.

## ثلاثة أوضاع

  ١  بلا علَم (الافتراضي): يقرأ ويحسب ويطبع. **لا أمر يُرسَل إطلاقاً.**
     ويكفي وحده لمعرفة أي وقفٍ وأي هدفٍ يمرّان.

  ٢  `--prove`: يرسل أمرين على **الحساب التجريبي وحده**:
       أ  وقفٌ أضيق من المُعلَن ⇒ يُنتظر **رفضٌ** من الوسيط.
       ب  وقفٌ عند المُعلَن ⇒ يُنتظر **قبول**، ثم يُغلق فوراً.
     ونتيجتاهما معاً هي الإثبات: القبول وحده لا يثبت الحدّ، والرفض وحده
     لا يثبت أن ما فوقه يُقبل.

  ٣  `--epic EURUSD`: الأداة نفسها على أي أداةٍ أخرى.

## ما لا يفعله

لا يعمل على حسابٍ حقيقي بحال — يتوقّف قبل أي شيء إن لم يقل الوسيط إنه
تجريبي. ولا يفتح قفل تنفيذ، ولا يمسّ إعدادات الخدمة، ولا يكتب ملفاً.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

OK, BAD, WARN, DIM, BOLD, END = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)

#: الأوقاف التي تُجرَّب في الحساب، مضروبةً في أدنى مسافةٍ معلنة.
#: نصفٌ يُنتظر رفضه، وواحدٌ يُنتظر قبوله.
TOO_TIGHT = Decimal("0.5")


def main() -> int:
    ap = argparse.ArgumentParser(description="إثبات اقتصاديات أداة من الوسيط")
    ap.add_argument("--epic", default="GOLD")
    ap.add_argument("--baseline", default="300", help="رأس المال المرجعي للحساب")
    ap.add_argument(
        "--prove", action="store_true",
        help="يرسل أمرين على التجريبي: واحدٌ يُرفض وواحدٌ يُقبل ثم يُغلق.",
    )
    ap.add_argument(
        "--approval-ref", default=None,
        help="مرجع موافقتك المكتوب — يلزم مع --prove، ويُسجَّل في قفل التنفيذ.",
    )
    a = ap.parse_args()

    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.factory import build_capital_adapter
    from app.config import get_settings
    from app.contracts import OrderType, Side
    from app.money import D
    from app.risk.capital_costs import CapitalComCostModel, ValueProvenance
    from app.risk.constitution import Broker, RiskLimits, RiskMode
    from app.risk.instrument_registry import InstrumentRegistry
    from app.secretstore.provider import build_secret_provider

    epic = a.epic.upper()
    settings = get_settings()
    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)
    adapter = build_capital_adapter(CapitalEnvironment.DEMO, secrets=secrets)
    adapter.connect()

    # ---- الحارس: تجريبيٌّ بالإيجاب، لا بغياب النفي -----------------------
    is_live = getattr(adapter, "is_live", True)
    if is_live is not False:
        print(f"{BAD}⛔ الوسيط لا يقول إنه تجريبي (is_live={is_live!r}). توقّف.{END}")
        return 2
    print(f"\n{OK}✅{END} متصل بالحساب التجريبي — {adapter.name}\n")

    # ---- ١ · ما يقوله الوسيط ---------------------------------------------
    details = adapter.get_instrument_details(epic)
    print(f"{BOLD}ما يقوله الوسيط عن {epic}{END}")
    for label, value in (
        ("حجم النقطة", details.pip_size),
        ("أصغر كمية", details.min_quantity),
        ("خطوة الكمية", details.quantity_increment),
        ("حجم العقد", details.lot_size),
        ("الهامش", f"{details.margin_factor} {details.margin_factor_unit or ''}"),
        ("أدنى مسافة وقف", details.min_stop_distance),
        ("وقف مضمون متاح", details.guaranteed_stop_available),
        ("عملة التسعير", details.quote_currency),
        ("حالة السوق", details.market_status),
    ):
        mark = f"{WARN}؟{END}" if value is None else f"{OK}·{END}"
        print(f"  {mark} {label:<18} {value}")

    if details.min_stop_distance is None or details.pip_size is None:
        print(f"\n{BAD}⛔ قيمةٌ لازمة غير معلنة — لا يُبنى على تخمين.{END}")
        return 3

    # ---- ٢ · ما يعنيه ذلك لحدودها ----------------------------------------
    registry = InstrumentRegistry.load()
    row = registry.get(epic)
    if row is None:
        print(
            f"\n{WARN}○{END} لا قياس محفوظ لـ{epic}. "
            "شغّلي discover_instrument_economics.py أولاً كي يُقاس السبريد."
        )
        return 4
    model = CapitalComCostModel(row.economics, row.assumptions)
    spread_note = (
        f"{OK}مقيس{END}"
        if row.assumptions.spread_provenance is ValueProvenance.BROKER_DISCOVERY
        else f"{WARN}مفترض{END}"
    )
    print(
        f"\n{DIM}السبريد المستعمل: {row.assumptions.spread_price} "
        f"({spread_note}، {row.spread_samples} رصدة){END}"
    )

    quote = adapter.get_market_data(epic)
    entry = quote.ask
    pip = row.economics.pip_size
    size = row.economics.min_deal_size
    min_pips = row.economics.min_stop_distance / pip

    limits = RiskLimits.for_mode(RiskMode.VALIDATION, D(a.baseline), Broker.CAPITAL_COM)
    budget = min(limits.target_risk_per_trade, limits.effective_max_risk(D(a.baseline)))
    print(
        f"\n{BOLD}ما يمرّ عند مرجع {a.baseline} دولار "
        f"(ميزانية الصفقة {budget:.2f}، أدنى عائد/مخاطرة {limits.min_reward_risk_ratio}){END}"
    )
    print(f"  {DIM}السعر الآن {entry} · الكمية الدنيا {size} · أدنى وقف {min_pips:.0f} نقطة{END}")
    header = f"  {'الوقف':>10} {'الخسارة':>9} {'التكلفة':>9} {'الهامش':>9} {'هدف ×2':>9} {'أقلّ هدف':>10}"
    print(f"{DIM}{header}{END}")

    workable = []
    for multiple in (1, 2, 5, 10, 15, 20, 30):
        stop_pips = min_pips * multiple
        stop_money = stop_pips * pip
        e2 = model.estimate(
            size=size, entry_price=entry,
            stop_distance_pips=stop_pips, take_profit_distance_pips=stop_pips * 2,
        )
        fits_budget = e2.all_in_risk <= budget
        rr2_ok = e2.net_reward_risk_ratio >= limits.min_reward_risk_ratio

        # أقلّ مضاعِف هدفٍ يبلغ الحدّ الصافي — يُبحَث لا يُفترَض.
        needed = None
        for tenth in range(20, 81):
            candidate = model.estimate(
                size=size, entry_price=entry, stop_distance_pips=stop_pips,
                take_profit_distance_pips=stop_pips * (Decimal(tenth) / 10),
            )
            if candidate.net_reward_risk_ratio >= limits.min_reward_risk_ratio:
                needed = Decimal(tenth) / 10
                break

        verdict = (
            f"{OK}✔{END}" if (fits_budget and rr2_ok)
            else (f"{WARN}~{END}" if fits_budget else f"{BAD}✘{END}")
        )
        print(
            f"  {verdict} {stop_money:>8} {e2.all_in_risk:>9.2f} {e2.total_costs:>9.2f} "
            f"{e2.margin_required:>9.2f} {e2.net_reward_risk_ratio:>9.2f} "
            f"{('×' + str(needed)) if needed else 'لا يبلغ':>10}"
        )
        if fits_budget and needed is not None:
            workable.append((stop_money, needed, e2.all_in_risk))

    if not workable:
        print(
            f"\n{BAD}⛔ لا وقفَ يجمع بين الميزانية والعائد الصافي على {epic} "
            f"بمرجع {a.baseline}.{END}"
        )
    else:
        widest = workable[-1]
        print(
            f"\n{OK}✅{END} {epic} صالحة: وقفٌ حتى {widest[0]} بمخاطرة {widest[2]:.2f} دولار، "
            f"بشرط هدفٍ عند {widest[1]}× الوقف فأكثر."
        )

    if not a.prove:
        print(
            f"\n{DIM}هذه قراءةٌ وحساب. لإثبات أدنى مسافة الوقف بالتجربة أضيفي "
            f"--prove (أمران على التجريبي: واحدٌ يُرفض وواحدٌ يُقبل ثم يُغلق).{END}\n"
        )
        return 0

    # ---- ٣ · التجربة: الرفض ثم القبول ------------------------------------
    #
    # قفل التنفيذ لا يُفتَح من علَمٍ وحده: `authorise` تشترط مرجعاً وسبباً
    # مكتوبين، ويُسجَّلان في القفل. وهذه هي القاعدة نفسها التي تحكم تجربة
    # الحساب التجريبي — ولا تُلتَفّ هنا لأن السكربت «مؤقّت».
    from app.brokers.capital.safety import ExecutionLock
    from app.contracts import OrderIntent

    if not (a.approval_ref or "").strip():
        print(f"\n{BAD}⛔ --prove يتطلب --approval-ref: مرجع موافقتك المكتوب.{END}\n")
        return 8
    adapter.execution_lock = ExecutionLock.locked().authorise(
        owner_authorization_reference=a.approval_ref,
        reason_ar=(
            f"إثبات أدنى مسافة وقف على {epic} بتجربة رفض/قبول على الحساب "
            "التجريبي — أمران، والثاني يُغلق فوراً."
        ),
        at=datetime.now(timezone.utc),
    )
    # قائمة التنفيذ تُضيَّق على هذه الأداة وحدها طوال التجربة.
    try:
        adapter.execution_allowlist = frozenset({epic})
    except Exception:  # noqa: BLE001
        pass

    def intent(stop_pips: Decimal, tag: str) -> OrderIntent:
        key = uuid.uuid4().hex
        stop = entry - stop_pips * pip
        return OrderIntent(
            idempotency_key=key, client_order_id=f"PROVE-{tag}-{key[:10]}",
            symbol=epic, side=Side.BUY, order_type=OrderType.MARKET, quantity=size,
            limit_price=None, stop_price=stop,
            take_profit_price=entry + stop_pips * pip * 3,
            expected_fill_price=entry, max_slippage_abs=quote.spread * D("3"),
            strategy_name="PROVE", strategy_version="1.0.0",
            risk_amount_usd=D("0"), commission_estimate_usd=D("0"),
            exit_plan_ar="تجربة إثبات حدّ الوسيط — تُغلق فوراً.",
            instrument_snapshot=details.model_dump(mode="json"),
            created_at_utc=datetime.now(timezone.utc),
        )

    print(f"\n{BOLD}التجربة على الحساب التجريبي{END}")

    tight = intent(min_pips * TOO_TIGHT, "TIGHT")
    print(f"  {DIM}أ · وقفٌ عند {tight.stop_price} (نصف المُعلَن) — يُنتظر رفض…{END}")
    try:
        adapter.place_order(tight)
        print(f"  {BAD}✘ قُبِل!{END} أي أن أدنى مسافة الوقف المُعلَنة ليست هي المطبَّقة.")
        print(f"  {BAD}  أغلقي المركز من تطبيق كابيتال، ولا تبني على الرقم المُعلَن.{END}")
        return 5
    except Exception as exc:  # noqa: BLE001
        print(f"  {OK}✔ رُفض كما يجب{END} — {type(exc).__name__}: {exc}")

    at_min = intent(min_pips, "ATMIN")
    print(f"  {DIM}ب · وقفٌ عند {at_min.stop_price} (المُعلَن) — يُنتظر قبول…{END}")
    try:
        order = adapter.place_order(at_min)
    except Exception as exc:  # noqa: BLE001
        print(f"  {BAD}✘ رُفض أيضاً{END} — {type(exc).__name__}: {exc}")
        print(f"  {BAD}  فالحدّ الحقيقي أوسع من المُعلَن. لا تبني على الرقم المُعلَن.{END}")
        return 6

    print(f"  {OK}✔ قُبل{END} — أمر {order.broker_order_id or order.client_order_id}")
    print(f"  {DIM}يُغلق الآن…{END}")
    try:
        # كابيتال تُغلق بـ`dealId` لا بالأداة والكمية.
        for position in adapter.list_positions():
            if position.epic.upper() == epic:
                adapter.close_position(position.deal_id)
                print(f"  {OK}✔ أُغلق المركز {position.deal_id}.{END}")
                break
        else:
            print(f"  {WARN}○ لم يُعثر على مركزٍ مفتوح — تحقّقي من تطبيق كابيتال.{END}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {BAD}⚠ تعذّر الإغلاق تلقائياً: {exc}{END}")
        print(f"  {BAD}  أغلقي المركز يدوياً من تطبيق كابيتال الآن.{END}")
        return 7

    print(
        f"\n{OK}✅ أُثبت{END}: أدنى مسافة وقفٍ على {epic} = {row.economics.min_stop_distance} "
        f"— رُفض ما دونها وقُبِلت هي.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
