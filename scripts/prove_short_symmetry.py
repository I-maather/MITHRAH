#!/usr/bin/env python3
"""
هل خسارةُ البيع مقيّدةٌ كخسارة الشراء؟ — قياسٌ من الحساب، لا رأي.

## لماذا هذا السكربت موجود

`CFD_ALLOW_SHORT = False` مكتوبةٌ في الدستور تحت كتلة سياسة أسهم IBKR
مباشرة. وفي بيع الأسهم النقدي ثلاثةُ مخاطر: أجرةُ اقتراضٍ، واستدعاءُ
مُقرِض، وخسارةٌ بلا سقف. ولا واحدٌ منها قائمٌ في عقد فروقات بوقفٍ إلزامي
عند الوسيط، بلا مبيت، وبلا اقتراض.

فالسؤال ليس رأياً — هو قياس. وهذا ما يقيسه هذا الملف على حسابها:

  ١ · الزوج المتناظر: شراءٌ وبيعٌ بالمسافة نفسها والكمية نفسها. كم يخسر
      كلٌّ منهما إن ضُرب الوقف؟ (النموذج لا يعرف الجهة أصلاً — فالتساوي
      بنيويٌّ، ويُطبع هنا ليُرى.)

  ٢ · **الفرق الحقيقي الوحيد: الذيل.** السعر ينزل إلى الصفر ويصعد بلا
      سقف. وهذا لا يهمّ إلا إن **قفز السعر فوق الوقف**. فتُقاس الفجوات
      الفعلية على الأداة: كم مرّة فتحت شمعةٌ بعيداً عن إغلاق سابقتها،
      وبكم — صعوداً (يؤذي البيع) وهبوطاً (يؤذي الشراء).

إن كان أسوأ قفزٍ صعوداً قريباً من أسوأ قفزٍ هبوطاً، فالذيل متماثلٌ عملياً
على هذه الأداة وفي هذه الأطر. وإن لم يكن، يُقال بالرقم.

## ما لا يفعله

لا يغيّر رايةً، ولا يرسل أمراً. يقرأ ويطبع.

    /opt/mathrah/.venv/bin/python scripts/prove_short_symmetry.py --epic GOLD
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

OK, BAD, WARN, DIM, BOLD, END = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)

FRAMES = (
    ("DAY", "يومي"), ("HOUR_4", "٤ ساعات"), ("HOUR", "ساعة"),
    ("MINUTE_30", "نصف ساعة"), ("MINUTE_15", "ربع ساعة"),
)

#: مضاعف الوقف لأوسع استراتيجيتين — كما في `prove_gold_economics.py`.
STOP_MULT = Decimal("1.5")


def main() -> int:
    ap = argparse.ArgumentParser(description="قياس تماثل البيع مع الشراء")
    ap.add_argument("--epic", default="GOLD")
    a = ap.parse_args()

    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.factory import build_capital_adapter
    from app.config import get_settings
    from app.contracts import Bar, DataSource
    from app.money import D
    from app.risk.capital_costs import CapitalComCostModel, StopKind, ValueProvenance
    from app.risk.constitution import (
        CFD_ALLOW_HEDGING, CFD_ALLOW_SHORT, CFD_REQUIRE_BROKER_STOP,
        Broker, RiskLimits, RiskMode,
    )
    from app.risk.instrument_registry import InstrumentRegistry
    from app.secretstore.provider import build_secret_provider
    from app.strategies.indicators import atr

    epic = a.epic.upper()
    settings = get_settings()
    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)
    adapter = build_capital_adapter(CapitalEnvironment.DEMO, secrets=secrets)
    adapter.connect()

    is_live = getattr(adapter, "is_live", True)
    if is_live is not False:
        print(f"{BAD}⛔ الوسيط لا يقول إنه تجريبي (is_live={is_live!r}). توقّف.{END}")
        return 2
    print(f"\n{OK}✅{END} متصل بالحساب التجريبي — {adapter.name}\n")

    row = InstrumentRegistry.load().get(epic)
    if row is None or not row.executable:
        print(f"{BAD}⛔ {epic} غير مقيس في السجل — لا يُبنى على تخمين.{END}")
        print(f"   {DIM}شغّلي discover_instrument_economics.py أولاً.{END}")
        return 3
    econ = row.economics
    model = CapitalComCostModel(econ, row.assumptions)
    size = econ.min_deal_size

    baseline = D(str(settings.baseline_equity_usd))
    limits = RiskLimits.for_mode(RiskMode.VALIDATION, baseline, Broker.CAPITAL_COM)

    # ---- ٠ · القيود المشتركة التي تجعل السؤال قابلاً للقياس --------------
    print(f"{BOLD}ما الذي يقيّد الخسارة — وهو نفسه في الجهتين{END}")
    for label, value, want in (
        ("وقفٌ إلزامي عند الوسيط", CFD_REQUIRE_BROKER_STOP, True),
        ("المبيت ممنوع", limits.allow_overnight, False),
        ("عبور العطلة ممنوع", limits.allow_weekend_hold, False),
        ("التحوّط ممنوع", CFD_ALLOW_HEDGING, False),
    ):
        mark = f"{OK}·{END}" if value is want else f"{BAD}✗{END}"
        print(f"  {mark} {label:<26} {value}")
    print(f"  {DIM}ولا اقتراضَ في عقد الفروقات — فلا أجرةَ سهمٍ ولا استدعاء مُقرِض.{END}")
    print(f"\n  الراية الآن: CFD_ALLOW_SHORT = "
          f"{BAD if not CFD_ALLOW_SHORT else OK}{CFD_ALLOW_SHORT}{END}")

    # ---- ١ · الزوج المتناظر ---------------------------------------------
    print(f"\n{BOLD}١ · الزوج المتناظر — نفس الأداة ونفس الكمية ونفس المسافة{END}")

    def bars_for(resolution: str):
        try:
            raw = adapter.get_candles(epic, resolution=resolution, max_bars=200)
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"
        two = D("2")
        try:
            return [
                Bar(
                    symbol=epic, start_utc=c.snapshot_time_utc,
                    open=(c.open_bid + c.open_ask) / two,
                    high=(c.high_bid + c.high_ask) / two,
                    low=(c.low_bid + c.low_ask) / two,
                    close=(c.close_bid + c.close_ask) / two,
                    volume=c.volume if c.volume is not None else D(0),
                    source=DataSource.HISTORICAL,
                )
                for c in raw
            ], None
        except Exception as exc:  # noqa: BLE001
            return None, f"شموع غير صالحة: {exc}"

    frames = {}
    for resolution, label in FRAMES:
        bars, problem = bars_for(resolution)
        if bars is None or len(bars) < 30:
            frames[resolution] = (None, problem or f"{len(bars or [])} شمعة فقط")
            continue
        frames[resolution] = (bars, None)

    usable = [(r, l) for r, l in FRAMES if frames[r][0] is not None]
    if not usable:
        print(f"{BAD}⛔ لم تُقرأ شموعٌ على أي إطار — لا قياس.{END}")
        for r, l in FRAMES:
            print(f"   {l}: {frames[r][1]}")
        return 4

    # الإطار الذي يعمل عليه النظام فعلاً أولاً، فإن لم يُقرأ فأوّل ما قُرئ.
    preferred = [pair for pair in usable if pair[0] == "HOUR_4"]
    resolution, label = (preferred or usable)[0]
    bars = frames[resolution][0]
    volatility = atr(bars, 14)
    stop_price_distance = STOP_MULT * volatility
    stop_pips = model.price_to_pips(stop_price_distance)
    entry = bars[-1].close

    econ_est = model.estimate(
        size=size, entry_price=entry,
        stop_distance_pips=stop_pips, take_profit_distance_pips=stop_pips * 2,
        stop_kind=StopKind.NORMAL, nights_held=0,
    )
    print(f"  {DIM}الإطار المقيس: {label} · ATR14 = {volatility:.2f} · "
          f"وقف {STOP_MULT}×ATR = {stop_price_distance:.2f} · كمية {size}{END}")
    print(f"  {DIM}{'':<24}{'شراء':>14}{'بيع':>14}{END}")
    for name, value in (
        ("خسارة عند الوقف", econ_est.price_loss_at_stop),
        ("سبريد", econ_est.spread_cost),
        ("فائدة تبييت", econ_est.overnight_cost),
        ("التكلفة الكاملة", econ_est.total_costs),
        ("الخسارة الكلية", econ_est.all_in_risk),
        ("الهامش المحجوز", econ_est.margin_required),
        ("التعرّض الاسمي", econ_est.notional_exposure),
    ):
        print(f"  · {name:<24}{value:>14.4f}{value:>14.4f}")
    print(f"  {OK}✓{END} الجهة لا تدخل النموذج إطلاقاً — "
          f"{DIM}`estimate()` بلا وسيط `side`، فالتساوي بنيويٌّ لا صدفة.{END}")
    print(f"  {DIM}وميزانية الصفقة الواحدة: {limits.target_risk_per_trade:.2f} دولار "
          f"على رأس مال {baseline}.{END}")

    # ---- ٢ · الذيل: الفجوات ---------------------------------------------
    print(f"\n{BOLD}٢ · الفرق الحقيقي — كم يقفز السعر فوق الوقف، صعوداً وهبوطاً{END}")
    print(f"  {DIM}القفزة = فتحُ الشمعة ناقص إغلاق سابقتها. الصعود يؤذي البيع،{END}")
    print(f"  {DIM}والهبوط يؤذي الشراء. والدولار محسوبٌ على الكمية الدنيا {size}.{END}\n")
    per_point = size * econ.lot_size

    print(f"  {DIM}{'الإطار':<10}{'شموع':>7}{'قفزات':>8}"
          f"{'أسوأ صعود':>13}{'أسوأ هبوط':>13}{'فرق $':>10}{END}")
    verdicts = []
    for resolution, label in FRAMES:
        bars, problem = frames[resolution]
        if bars is None:
            print(f"  {label:<10} {WARN}○ لم تُقرأ — {problem}{END}")
            continue
        ups, downs = [], []
        for prev, cur in zip(bars, bars[1:]):
            gap = cur.open - prev.close
            (ups if gap > 0 else downs).append(abs(gap))
        worst_up = max(ups) if ups else D("0")
        worst_down = max(downs) if downs else D("0")
        n_gaps = sum(1 for g in ups + downs if g > 0)
        up_usd = worst_up * per_point
        down_usd = worst_down * per_point
        diff = up_usd - down_usd
        colour = OK if abs(diff) <= limits.target_risk_per_trade else WARN
        print(f"  {label:<10}{len(bars):>7}{n_gaps:>8}"
              f"{up_usd:>12.2f}${down_usd:>12.2f}${colour}{diff:>+9.2f}${END}")
        verdicts.append((label, diff))

    # ---- ٣ · الحكم -------------------------------------------------------
    print(f"\n{BOLD}الحكم{END}")
    budget = limits.target_risk_per_trade
    worst = max((abs(d) for _, d in verdicts), default=D("0"))
    if not verdicts:
        print(f"  {WARN}○ لا إطار قِيس — لا حكم.{END}")
        return 5
    if worst <= budget:
        print(f"  {OK}✓{END} أكبر فرقٍ بين ذيلَي الجهتين {worst:.2f} دولار — "
              f"دون ميزانية الصفقة ({budget:.2f}).")
        print(f"  {DIM}أي أن البيع لا يحمل خطراً زائداً يقاس بالدولار على هذه الأداة{END}")
        print(f"  {DIM}وفي هذه الأطر، بالقيود أعلاه. والقرار يبقى قرار المالكة.{END}")
    else:
        print(f"  {WARN}○{END} أكبر فرقٍ بين ذيلَي الجهتين {worst:.2f} دولار — "
              f"فوق ميزانية الصفقة ({budget:.2f}).")
        print(f"  {DIM}الذيل الصاعد أثقل هنا. لا يُفتح البيع على هذه الأداة{END}")
        print(f"  {DIM}قبل وقفٍ مضمون أو إطارٍ أقصر.{END}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
