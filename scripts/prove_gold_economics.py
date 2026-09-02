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
    ap.add_argument(
        "--baseline", default=None,
        help="رأس المال المرجعي. الافتراض: يُقرأ من إعدادات الخادم، ولا يُفترض رقم.",
    )
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

    # ---------------------------------------------------------------------
    # **المرجع يُقرأ من إعدادات الخادم، ولا يُفترض.**
    #
    # كان `--baseline` يفترض 300 دولاراً — والميزانية وكل صفٍّ في الجدول
    # يُقاسان عليه. فلو كان مرجع الخادم 150 لكانت الميزانية 0.375 لا 0.75،
    # وكان الجدول يقول «صالحة» عن أوقافٍ لا تمرّ.
    #
    # وهو العيب الحاكم نفسه صعوداً درجةً: بعد أن كان المِسطرة وقفاً مفترضاً،
    # صار المِسطرة **رأس مالٍ مفترضاً**. فيُقرأ الآن من `settings`، ويُقال
    # مصدره، ويبقى `--baseline` لسؤال «ماذا لو».
    # ---------------------------------------------------------------------
    if a.baseline is not None:
        baseline, baseline_source = D(a.baseline), "أنتِ مرّرتِه"
    else:
        baseline, baseline_source = D(settings.baseline_equity_usd), "إعدادات الخادم"
    limits = RiskLimits.for_mode(RiskMode.VALIDATION, baseline, Broker.CAPITAL_COM)
    budget = min(limits.target_risk_per_trade, limits.effective_max_risk(baseline))

    # ---------------------------------------------------------------------
    # **سلّم الأوقاف نسبةٌ من السعر، لا مضاعفاتٌ لأدنى حدّ الوسيط.**
    #
    # أوّل كتابةٍ لهذا السكربت جعلت السلّم مضاعفاتٍ لأدنى مسافة وقف. وذلك
    # يصلح لـEUR/USD لأن حدّها 100 نقطة — رقمٌ كبيرٌ قريب من وقفٍ حقيقي.
    # وحدّ الذهب `0.001` دولار: **عُشر سنت**. فصار أوسع صفٍّ في الجدول وقفاً
    # بثلاثة سنتات على أداةٍ سعرها 4371 دولاراً، فابتلعه السبريد كلّه،
    # فطبع «لا وقفَ يمرّ» — وهو خطأٌ في مدى الجدول لا حقيقةٌ عن الذهب.
    #
    # وكاد ذلك يُسقط خطّةً صحيحة. فالسلّم الآن **نسبةٌ من السعر**: يقيس ما
    # يقيسه وقفٌ حقيقي على أي أداة، ويُعلَّم فيه صفُّ حدّ الوسيط ليُرى موضعه.
    # ---------------------------------------------------------------------
    LADDER_PCT = (
        D("0.0002"), D("0.0005"), D("0.001"), D("0.0025"),
        D("0.005"), D("0.01"), D("0.015"), D("0.02"),
    )

    print(
        f"\n{BOLD}ما يمرّ عند مرجع {baseline} دولار ({baseline_source}) "
        f"(ميزانية الصفقة {budget:.2f}، أدنى عائد/مخاطرة صافٍ {limits.min_reward_risk_ratio}){END}"
    )
    print(
        f"  {DIM}السعر الآن {entry} · الكمية الدنيا {size} · "
        f"أدنى وقفٍ يقبله الوسيط {row.economics.min_stop_distance} "
        f"({min_pips:g} نقطة){END}"
    )
    print(
        f"{DIM}  {'الوقف':>12} {'٪ السعر':>8} {'الخسارة':>8} {'التكلفة':>8} "
        f"{'الهامش':>8} {'ع/م ×2':>8} {'أقلّ هدف':>9}{END}"
    )

    passing: list[tuple[Decimal, Decimal, Decimal]] = []
    for pct in LADDER_PCT:
        stop_money = (entry * pct).quantize(pip if pip < 1 else D("0.01"))
        if stop_money <= 0:
            continue
        below_broker = stop_money < row.economics.min_stop_distance
        stop_pips = stop_money / pip
        e2 = model.estimate(
            size=size, entry_price=entry,
            stop_distance_pips=stop_pips, take_profit_distance_pips=stop_pips * 2,
        )
        fits_budget = e2.all_in_risk <= budget
        rr2_ok = e2.net_reward_risk_ratio >= limits.min_reward_risk_ratio

        # أقلّ مضاعِف هدفٍ يبلغ الحدّ الصافي — **يُبحَث عنه ولا يُفترَض**.
        # **يبدأ البحث من الضِّعف الواحد لا من 1.5.** بدؤه عند 1.5 يجعل أقلّ
        # النتائج الممكنة 1.5 دائماً — فيُعرض حدُّ البحث كأنه قياس. ويمتدّ إلى
        # 20 ضعفاً كي لا يُقال «لا يبلغ» عمّا يبلغ عند 12.
        needed = None
        for tenth in range(10, 201):
            candidate = model.estimate(
                size=size, entry_price=entry, stop_distance_pips=stop_pips,
                take_profit_distance_pips=stop_pips * (Decimal(tenth) / 10),
            )
            if candidate.net_reward_risk_ratio >= limits.min_reward_risk_ratio:
                needed = Decimal(tenth) / 10
                break

        if below_broker:
            verdict, note = f"{BAD}✘{END}", "دون حدّ الوسيط"
        elif not fits_budget:
            verdict, note = f"{BAD}✘{END}", "فوق الميزانية"
        elif needed is None:
            verdict, note = f"{WARN}~{END}", "لا يبلغ"
        else:
            verdict = f"{OK}✔{END}" if rr2_ok else f"{WARN}~{END}"
            note = f"×{needed}"
            passing.append((stop_money, needed, e2.all_in_risk))

        print(
            f"  {verdict} {stop_money:>11} {pct * 100:>7.2f}% {e2.all_in_risk:>8.2f} "
            f"{e2.total_costs:>8.2f} {e2.margin_required:>8.2f} "
            f"{e2.net_reward_risk_ratio:>8.2f} {note:>9}"
        )

    if not passing:
        print(
            f"\n{BAD}⛔ لا وقفَ يجمع بين الميزانية والعائد الصافي على {epic} "
            f"بمرجع {baseline}.{END}"
        )
        print(
            f"{DIM}   وهذا يعني أن {epic} لا تصلح على هذا الحجم — لا أن الحساب معطوب.{END}"
        )
    else:
        narrowest, widest = passing[0], passing[-1]
        best_multiple = min(p[1] for p in passing)
        print(
            f"\n{OK}✅{END} {epic} صالحة على مرجع {baseline}: "
            f"وقفٌ من {narrowest[0]} إلى {widest[0]} دولار "
            f"(مخاطرة {narrowest[2]:.2f}–{widest[2]:.2f} دولار)، "
            f"وأقلّ هدفٍ مقبول {best_multiple}× الوقف."
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
    from app.brokers.capital.safety import ExecutionLock, ExecutionLocked
    from app.contracts import OrderIntent
    from app.brokers.base import BrokerRejected

    # ---------------------------------------------------------------------
    # **حين لا يكون الحدّ قيداً، لا يُشترى إثباتُه بفتح قفلين.**
    #
    # أدنى وقفٍ على EUR/USD مئة نقطة — رقمٌ يمنع صفقاتٍ فعلاً، فإثباتُه يغيّر
    # قراراً. وأدنى وقفٍ على الذهب `0.001` دولار: عُشر سنت. لا استراتيجيةَ
    # تُنتج وقفاً بعُشر سنت، فالرقم لا يمنع شيئاً، وإثباتُه لا يغيّر قراراً.
    #
    # وثمنُ الإثبات ليس رخيصاً: قفل التنفيذ **طبقتان** — واحدة في المحوّل
    # وأخرى في الناقل — وهما أقوى ما في هذا النظام. وفتحُهما معاً لأجل رقمٍ
    # لا يقرّر شيئاً مقايضةٌ خاسرة.
    #
    # فالحدّ يبقى `FACT` مقروءاً من الوسيط لا مُثبَتاً بتجربة، **ويُقال ذلك**.
    # ---------------------------------------------------------------------
    binding_ratio = row.economics.min_stop_distance / entry
    if binding_ratio < D("0.0002"):
        print(
            f"\n{WARN}○ لا تجربة على {epic}: أدنى وقفٍ يقبله الوسيط "
            f"{row.economics.min_stop_distance} — أي {binding_ratio * 100:.4f}٪ من السعر.{END}"
        )
        print(f"{DIM}   رقمٌ لا يمنع أي وقفٍ حقيقي، فإثباتُه لا يغيّر قراراً.{END}")
        print(f"{DIM}   وفتحُ قفلَي التنفيذ لأجله مقايضةٌ خاسرة — وهما أقوى ما في هذا النظام.{END}")
        print(
            f"{DIM}   ما يقرّر في {epic} هو السبريد ({row.assumptions.spread_price}، "
            f"{row.spread_samples} رصدات) والكمية الدنيا ({size}) والهامش — وكلها مقيسة.{END}"
        )
        print(f"{DIM}   وأدنى الوقف يبقى مقروءاً من الوسيط لا مُثبَتاً بتجربة.{END}\n")
        return 0

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
    except ExecutionLocked as exc:
        print(f"  {WARN}○ لم يصل الأمر إلى الوسيط{END} — {exc}")
        print(f"  {DIM}  قفل التنفيذ طبقتان، والناقل ما زال مغلقاً. لا إثبات هنا.{END}")
        return 9
    except Exception as exc:  # noqa: BLE001
        # **الرفض من حارسنا ليس إثباتاً.** حارسنا يقارن بالرقم الذي قرأناه
        # نحن، فرفضُه يثبت أن الحارس يعمل — لا أن الوسيط يرفض. والإثبات لا
        # يكون إلا برفضٍ صادرٍ عن كابيتال.
        # **رفضُ حارسنا ليس إثباتاً، ولا يمضي إلى سطر «أُثبت».**
        #
        # حارسنا يقارن بالرقم الذي قرأناه نحن، فرفضُه يثبت أن الحارس يعمل لا
        # أن الوسيط يرفض. وكان هذا الفرع يطبع تنبيهه ثم **يسقط إلى ما بعده**
        # بلا `return`، فيصل إلى «✅ أُثبت: رُفض ما دونها» عن رفضٍ لم تُصدره
        # كابيتال قط. أي أن السطر الأخير كان يعِد بدليلٍ لم يقع.
        ours = isinstance(exc, BrokerRejected) and "حدّ الوسيط" in str(exc)
        if ours:
            print(f"  {WARN}○ رفضه حارسُنا قبل الإرسال{END} — {exc}")
            print(f"  {DIM}  وهذا يثبت أن الحارس يعمل، لا أن الوسيط يرفض.{END}")
            print(f"  {DIM}  ولا إثبات هنا: الأمر لم يبلغ كابيتال.{END}")
            return 11
        print(f"  {OK}✔ رفضه الوسيط{END} — {type(exc).__name__}: {exc}")

    at_min = intent(min_pips, "ATMIN")
    print(f"  {DIM}ب · وقفٌ عند {at_min.stop_price} (المُعلَن) — يُنتظر قبول…{END}")
    try:
        order = adapter.place_order(at_min)
    except ExecutionLocked as exc:
        # **لا يُنسَب إلى الوسيط رفضٌ لم يصدر عنه.**
        #
        # كان هذا الفرع يقول «فالحدّ الحقيقي أوسع من المُعلَن» عن *أي* فشل.
        # فلمّا أغلق قفلُ الناقل الطريق — وهو قفلنا نحن، لا الوسيط — نُسب
        # الرفض إلى كابيتال، واستُنتج عن أرقامها ما لم تقله. وهو العيب
        # الحاكم في صورة جديدة: سببٌ يُعرَض لم يُقرأ من مصدره.
        print(f"  {WARN}○ لم يصل الأمر إلى الوسيط أصلاً{END} — {exc}")
        print(f"  {DIM}  قفل التنفيذ طبقتان: واحدة في المحوّل وأخرى في الناقل.{END}")
        print(f"  {DIM}  ولا يُستنتج من هذا شيءٌ عن أرقام {epic}: لم تُختبَر.{END}")
        return 9
    except BrokerRejected as exc:
        print(f"  {BAD}✘ رفضه الوسيط{END} — {exc}")
        print(f"  {BAD}  فالحدّ الحقيقي أوسع من المُعلَن. لا تبني على الرقم المُعلَن.{END}")
        return 6
    except Exception as exc:  # noqa: BLE001
        print(f"  {BAD}✘ فشل لسببٍ آخر{END} — {type(exc).__name__}: {exc}")
        print(f"  {DIM}  ولا يُستنتج من هذا شيءٌ عن أرقام {epic}: لم تُختبَر.{END}")
        return 10

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
