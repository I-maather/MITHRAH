#!/usr/bin/env python3
"""
مسح التاريخ الكامل — يقرأ ما يسمح به الوسيط ويقيس عليه.

    /opt/mathrah/.venv/bin/python scripts/run_history_sweep.py

## السؤال الذي يجيبه

**هل توجد حافّة أصلاً؟** وهو المجهول الأكبر في المشروع، وشرط بوابة
`G3 — Viability`. كل ما بُني حتى الآن — الأقفال والحدود والمزوّدون
والشاشات — بنيةٌ حول جواب لم يُقَس بعد.

## لماذا سكربت منفصل عن `run_backtest`

`run_backtest` يقرأ نافذةً واحدة وسقف الوسيط ٢٠٠ شمعة لكل نداء. فطلب
«التاريخ الكامل» لا يُنفَّذ بتمرير رقم أكبر: يُنفَّذ بالنزول في الزمن نداءً
بعد نداء (`from`/`to`)، وعبر أكثر من دقّة.

## ما كان مكسوراً فيه — ولم يُشغَّل مرّة

كُتب هذا الملف ولم يُنفَّذ قط، فحمل أربعة أعطال كان أوّلها يقتله عند أوّل
سطر: وحدةٌ باسم `app.backtest.runner` **لا وجود لها** (الصحيح
`app.strategies.backtest`)، واستيرادٌ من `scripts` وهي ليست على المسار،
وحقلٌ باسم `bars[0].timestamp` والصحيح `start_utc`، ونداءُ
`Backtester().run(bars)` بينما المُنشئ يطلب نموذج تكلفة وإعداداً،
و`run` يطلب استراتيجية.

أربعة أخطاء في اثني عشر سطراً — وكلّها من كتابةٍ عن ظنٍّ بلا تشغيل. وهذا
سبب وجود الملاحظة هنا: **سكربتٌ لم يُشغَّل ليس كوداً، بل نيّة.**

## العطل الذي كشفه أوّل تشغيل — وكان صامتاً تماماً

أعطى المسح **صفر صفقة على 1711 شمعة يومية** (نحو سبع سنوات)، وعلى 1699
ساعية، وعلى 1631 ربع ساعية. وقال التقرير: «العمق المتاح لا يكفي للحكم».

والسبب لم يكن العمق. أوّل سطر في `TrendPullbackV1.evaluate`:

    if symbol not in self.metadata.markets:   # ("SPY", "QQQ", "IVV")
        return None

**الاستراتيجية ترفض النظر إلى EURUSD أصلاً.** كُتبت لمؤشرات أسهم أمريكية
يومية — ونصّها يقول ذلك: «عمولة IBKR Pro»، والأسواق ثلاثة صناديق مؤشرات.
ثم تحوّل المنتج إلى فوركس ولم ينتقل معه شيء.

أُثبت بالقياس: على **نفس الشموع** بالضبط، الرمز `SPY` يولّد ٥ إشارات
و`EURUSD` يولّد صفراً. الفرق كله في قائمة الأسواق.

فصار الرفض يُقال بالاسم: `DECLINED_INSTRUMENT`. وحكمٌ يقول «لا يكفي
العمق» عن استراتيجية لم تنظر إلى البيانات أصلاً هو نفس صنف العطل الذي
نطارده — تشخيصٌ يشير إلى المكان الخطأ.

## أداةٌ واحدة عمداً

EUR/USD وحده. نموذج التكلفة الوحيد المعرَّف في المشروع
(`PROVISIONAL_EURUSD`) — وحجم النقطة فيه 0.0001، وهو **يستحيل** لزوجٍ
مقوَّم بالين حيث النقطة 0.01. وتشغيله على USDJPY يُنتج أرقاماً بخانات
عشرية جميلة وخاطئة بمئة ضعف. رقمٌ خاطئٌ في تقرير حافّة أسوأ من لا رقم.

## ما لا يفعله

**لا يرسل أمراً، ولا يفتح قفلاً، ولا يغيّر إعداداً.** قراءةٌ وحساب وتقرير.

## قيدٌ مُعلَن

«التاريخ الكامل» هنا يعني **أقصى ما يعطيه الوسيط**، لا أكثر — والعمق
يختلف بالدقّة.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO))          # كي يُستورَد `scripts.run_backtest`

#: الدقّة → (طول الشمعة، عدد النداءات المطلوبة للنزول عميقاً)
LADDER = {
    "DAY": (timedelta(days=1), 10),
    "HOUR_4": (timedelta(hours=4), 12),
    "HOUR": (timedelta(hours=1), 12),
    "MINUTE_15": (timedelta(minutes=15), 12),
}
PAGE = 200  # سقف الوسيط لكل نداء

#: الأداة الوحيدة التي يملك المشروع لها نموذج تكلفة. انظري الشرح أعلاه.
PRICED_EPICS = ("EURUSD",)

#: فاصلٌ بين نداءات الأسعار. أوّل تشغيل نجح، والثاني بعده مباشرةً أعاد
#: `CapitalTransportError` على ثلاث دقّات — الوسيط يحدّ المعدّل.
PAGE_PAUSE_SECONDS = 0.6

#: حدّ التعادل **يُحسَب من الإعداد المُختبَر**، لا يُنقَل ثابتاً.
#:
#: كان هنا `0.364` منقولاً من §5 في `PROJECT-TRUTH` — وهو محسوب لعائدٍ إلى
#: مخاطرة صافٍ 1.75. والمسح يُشغَّل بوقف 30 وهدف 60، وصافيهما بعد التكلفة
#: أقلّ من ذلك. فكنّا نقيس معدّل فوز إعدادٍ ونقارنه بحدّ تعادل إعدادٍ آخر.
#:
#: والصحيح أن الحدّ = 1 ÷ (1 + العائد إلى المخاطرة الصافي)، ويُؤخذ الصافي
#: من نموذج التكلفة نفسه للإعداد الجاري. قياسٌ من المصدر لا نقلٌ من وثيقة.
def breakeven_win_rate(cost_model, config, reference_price) -> float:
    economics = cost_model.estimate(
        size=config.size,
        entry_price=reference_price,
        stop_distance_pips=config.stop_distance_pips,
        take_profit_distance_pips=config.take_profit_distance_pips,
        stop_kind=config.stop_kind,
        nights_held=0,
    )
    net_rr = float(economics.net_reward_risk_ratio)
    if net_rr <= 0:
        return 1.0          # عائدٌ غير موجب: لا معدّل فوز ينقذه
    return 1.0 / (1.0 + net_rr)

OK, BAD, WARN, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def transplanted(strategy_class, epic: str):
    """
    نسخةٌ من الاستراتيجية تقبل أداةً خارج أسواقها المُعلَنة.

    **تُستعمل بعلم وبعلامة.** الفرضية كُتبت لمؤشرات أسهم يومية، ونقلُها إلى
    زوج عملات ليس ترقيةً بل **فرضية جديدة تُختبَر من الصفر**. فلا يُغيَّر
    ملف الاستراتيجية — يُبنى صنفٌ مشتقّ لهذا التشغيل وحده، ويُوسَم التقرير.
    """
    from dataclasses import replace

    class Transplanted(strategy_class):  # type: ignore[misc, valid-type]
        metadata = replace(
            strategy_class.metadata,
            markets=tuple(strategy_class.metadata.markets) + (epic,),
        )

    Transplanted.__name__ = f"{strategy_class.__name__}Transplanted"
    return Transplanted()


def fetch_window(adapter, epic: str, resolution: str, start, end):
    """نداء واحد بنافذة زمنية. يعيد [] عند أي رفض بدل أن يوقف المسح كلّه."""
    from app.brokers.capital.endpoints import prices_path
    from app.brokers.capital.models import CapitalCandle

    fmt = "%Y-%m-%dT%H:%M:%S"
    try:
        body = adapter._get(  # noqa: SLF001
            prices_path(epic),
            {
                "resolution": resolution,
                "max": PAGE,
                "from": start.strftime(fmt),
                "to": end.strftime(fmt),
            },
        )
    except Exception as exc:  # noqa: BLE001
        print(f"      {WARN}⚠️{END}  {epic}/{resolution}: {type(exc).__name__}")
        return []
    return CapitalCandle.parse_list(body)


def sweep(adapter, epic: str, resolution: str) -> list:
    """ينزل في الزمن نداءً بعد نداء حتى يتوقّف الوسيط عن الإعطاء."""
    span, pages = LADDER[resolution]
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    out: list = []
    for _ in range(pages):
        start = end - span * PAGE
        got = fetch_window(adapter, epic, resolution, start, end)
        if not got:
            break
        time.sleep(PAGE_PAUSE_SECONDS)
        out = list(got) + out
        end = start
    return out


#: أدنى عدد أخطاء معيارية بين معدّل الفوز وحدّ التعادل ليُقال «فوق».
#:
#: **لماذا هذا الحارس موجود.** أوّل تشغيل ناجح أعطى 37.8٪ و36.6٪ و36.7٪
#: و38.5٪ مقابل حدّ تعادل 36.4٪ — وطبعت الأداة «✅ فوق حدّ التعادل» أربع
#: مرّات. والفارق 0.2 إلى 2.1 نقطة مئوية على 39–111 صفقة، والخطأ المعياري
#: عند هذه الأعداد **4.6 إلى 7.8 نقطة**. أي أن الفارق كلّه داخل الضجيج.
#:
#: فكانت الأداة تقول «حافّة» عن أرقام لا تفرّق بين وجود الحافّة وعدمها —
#: وهو نفس صنف العطل الذي بُنيت لتكشفه، واقعاً فيها للمرّة الثالثة.
#:
#: 1.645 = حدّ 95٪ من طرف واحد. أقلّ منه: «لم يُرجَّح ولم يُستبعَد».
MIN_Z_FOR_EDGE = 1.645


def win_rate_z(wins: int, trades: int, breakeven: float) -> float:
    """كم خطأً معيارياً يفصل معدّل الفوز عن حدّ التعادل."""
    if trades <= 0:
        return 0.0
    p = wins / trades
    variance = p * (1.0 - p) / trades
    if variance <= 0:
        return 0.0
    return (p - breakeven) / math.sqrt(variance)


def verdict(result, minimum: int, breakeven: float) -> tuple[str, str]:
    """
    (الرمز، الحكم) — أربع حالات.

    و**«لم يُحسم» ليس فشلاً ولا نجاحاً**: هو أن العيّنة لا تفرّق. وخلطُه
    بأيّ منهما يُنتج قراراً على ضجيج.
    """
    if result.trade_count < minimum:
        return "INCONCLUSIVE", (
            f"{result.trade_count} صفقة أقلّ من {minimum} — لا يُستنتج منها شيء."
        )
    if result.win_rate is None:
        return "INCONCLUSIVE", "لا معدّل فوز محسوب."

    rate = float(result.win_rate)
    z = win_rate_z(result.wins, result.trade_count, breakeven)
    margin = (rate - breakeven) * 100
    tail = (
        f"{rate * 100:.1f}٪ مقابل تعادل {breakeven * 100:.1f}٪ "
        f"(فارق {margin:+.1f} نقطة · z={z:.2f} على {result.trade_count} صفقة) "
        f"· صافي {result.net_pnl:.2f}$"
    )

    # **الصافي يحكم قبل معدّل الفوز.**
    #
    # أعطى أوّل تشغيلٍ صادق أربعة إعدادات معدّل فوزها فوق التعادل وصافيها
    # **سالب في الأربعة**: ‎−0.70 و‎−3.81 و‎−3.39 و‎−0.17 دولار. ولا تناقض:
    # حدّ التعادل يفترض أن كل صفقة تنتهي عند الوقف أو الهدف، والمحرّك يُخرج
    # الصفقة أيضاً بانتهاء المهلة — فيقع خروجٌ ثالث بعائد أسوأ من الهدف،
    # ولا يدخل في الحساب.
    #
    # فمعدّل الفوز مقارنةٌ بنموذج، والصافي هو ما وقع فعلاً. وحين يختلفان
    # يُصدَّق ما وقع.
    if result.net_pnl <= 0:
        return "LOSING", f"**خاسر بالصافي** — {tail}"
    if z >= MIN_Z_FOR_EDGE:
        return "ABOVE_BREAKEVEN", f"فوق التعادل بفارق يُعتدّ به — {tail}"
    if z <= -MIN_Z_FOR_EDGE:
        return "BELOW_BREAKEVEN", f"تحت التعادل بفارق يُعتدّ به — {tail}"
    return "INDISTINGUISHABLE", f"**رابح بالصافي، لكن لا يُفرَّق عن التعادل** — {tail}"


def main() -> int:
    ap = argparse.ArgumentParser(description="مسح التاريخ وقياس الاستراتيجية عليه")
    ap.add_argument("--source", choices=["live", "demo"], default="live")
    ap.add_argument("--epics", nargs="*", default=list(PRICED_EPICS))
    ap.add_argument("--resolutions", nargs="*", default=list(LADDER))
    ap.add_argument("--stop-pips", default="30")
    ap.add_argument("--tp-pips", default="60")
    ap.add_argument("--size", default="100")
    ap.add_argument(
        "--strategies", nargs="*", default=["all"],
        help="أسماء الاستراتيجيات، أو all لكلّها.",
    )
    ap.add_argument(
        "--transplant", action="store_true",
        help="اسمحي للاستراتيجية بأداة خارج أسواقها المُعلَنة — فرضية جديدة تُختبَر.",
    )
    ap.add_argument("--report", default=str(REPO / "data" / "history-sweep.json"))
    a = ap.parse_args()

    unpriced = [e for e in a.epics if e not in PRICED_EPICS]
    if unpriced:
        print(
            f"{BAD}⛔ لا نموذج تكلفة لـ{'، '.join(unpriced)}.{END}\n"
            f"   نموذج المشروع الوحيد لـEUR/USD، وحجم نقطته 0.0001 — يستحيل\n"
            f"   لزوجٍ مقوَّم بالين. تشغيلُه عليها يُنتج أرقاماً خاطئة بمئة ضعف.",
            file=sys.stderr,
        )
        return 2

    # **الفحص قبل الأسرار والشبكة.** اسمٌ مكتوبٌ خطأً يجب أن يُردّ في
    # جزءٍ من الثانية، لا بعد فتح جلسةٍ عند الوسيط ثم الانفجار على
    # سرٍّ مفقود — فيبدو الخطأ في الاعتماد وهو في سطر الأوامر.
    from app.strategies.breakout_retest import BreakoutRetest
    from app.strategies.range_mean_reversion import RangeMeanReversion
    from app.strategies.trend_pullback_v1 import TrendPullbackV1
    from app.strategies.trend_pullback_v2 import TrendPullbackV2

    catalogue = {
        "TREND_PULLBACK_V2": TrendPullbackV2,
        "RANGE_MEAN_REVERSION": RangeMeanReversion,
        "BREAKOUT_RETEST": BreakoutRetest,
        "TREND_PULLBACK_V1": TrendPullbackV1,      # للمقارنة التاريخية وحدها
    }
    default_three = ["TREND_PULLBACK_V2", "RANGE_MEAN_REVERSION", "BREAKOUT_RETEST"]
    wanted = default_three if a.strategies == ["all"] else a.strategies
    unknown = [name for name in wanted if name not in catalogue]
    if unknown:
        print(f"{BAD}⛔ استراتيجيات غير معروفة: {'، '.join(unknown)}{END}\n"
              f"   المتاح: {'، '.join(catalogue)}", file=sys.stderr)
        return 2


    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.factory import build_capital_adapter
    from app.config import get_settings
    from app.contracts import StopKind
    from app.money import D
    from app.risk.capital_costs import PROVISIONAL_EURUSD, CapitalComCostModel
    from app.secretstore.provider import build_secret_provider
    from app.strategies.backtest import BacktestConfig, Backtester, InsufficientData

    from scripts.run_backtest import to_bars   # نفس التحويل، بلا ازدواج منطق

    settings = get_settings()
    env = CapitalEnvironment.LIVE if a.source == "live" else CapitalEnvironment.DEMO
    # مسار الأسرار من الإعدادات لا مثبَّتاً: تثبيتُه كان يجعل مفتاحاً كُتب
    # على الخادم في ملفٍ آخر «موجوداً وغير مقروء». هذه رابع مرّة.
    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)
    adapter = build_capital_adapter(env, secrets=secrets)
    adapter.connect()
    print(f"\n{OK}✅{END} متصل — {adapter.name} (قراءة فقط)\n")

    config = BacktestConfig(
        size=D(a.size),
        stop_distance_pips=D(a.stop_pips),
        take_profit_distance_pips=D(a.tp_pips),
        stop_kind=StopKind.NORMAL,
        allow_overnight=False,
    )
    cost_model = CapitalComCostModel(PROVISIONAL_EURUSD)
    engine = Backtester(cost_model=cost_model, config=config)
    breakeven = breakeven_win_rate(cost_model, config, D("1.15837"))
    print(f"{DIM}   حدّ التعادل لهذا الإعداد: {breakeven * 100:.1f}٪ "
          f"(وقف {a.stop_pips} · هدف {a.tp_pips} نقطة){END}\n")

    report: dict = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "config": {
            "size": a.size, "stop_pips": a.stop_pips, "tp_pips": a.tp_pips,
            "breakeven_win_rate": round(breakeven, 4),
            "breakeven_source": "محسوب من نموذج التكلفة للإعداد الجاري",
            "cost_model": "PROVISIONAL_EURUSD",
            "transplanted": bool(a.transplant),
        },
        "runs": [],
    }

    print(f"{DIM}   الاستراتيجيات: {'، '.join(wanted)}{END}\n")

    for strategy_name in wanted:
        strategy_class = catalogue[strategy_name]
        declared = tuple(strategy_class.metadata.markets)
        print(f"\n\033[1m▸ {strategy_name}\033[0m  "
              f"(أسواقها: {'، '.join(declared)})")
        run_one_strategy(
            strategy_class=strategy_class, strategy_name=strategy_name,
            declared=declared, epics=a.epics, resolutions=a.resolutions,
            adapter=adapter, engine=engine, config=config, breakeven=breakeven,
            transplant=a.transplant, report=report, to_bars=to_bars,
        )
    return finish(report, a.report)


def run_one_strategy(
    *, strategy_class, strategy_name, declared, epics, resolutions,
    adapter, engine, config, breakeven, transplant, report, to_bars,
):
    from app.strategies.backtest import InsufficientData

    for epic in epics:
        # **يُسأل أوّلاً: هل تنظر الاستراتيجية إلى هذه الأداة أصلاً؟**
        # صفرُ صفقة من استراتيجية رفضت الأداة ليس «لا حافّة» ولا «عيّنة
        # صغيرة» — هو لا شيء. وقولُ غير ذلك يُرسل القارئ إلى المكان الخطأ.
        if epic not in declared:
            if not a.transplant:
                print(
                    f"  {BAD}⛔{END} {epic:<8} الاستراتيجية لا تقبل هذه الأداة.\n"
                    f"     {strategy_name} أسواقها المُعلَنة: "
                    f"{'، '.join(declared)}\n"
                    f"     وهي فرضية كُتبت لمؤشرات أسهم أمريكية يومية، لا لزوج عملات.\n"
                    f"     لتشغيلها على {epic} بوصفها **فرضية جديدة**: أضيفي --transplant"
                )
                report["runs"].append({
                    "strategy": strategy_name,
                    "epic": epic, "verdict": "DECLINED_INSTRUMENT",
                    "declared_markets": list(declared),
                })
                continue
            print(
                f"  {WARN}⚠️{END}  فرضية منقولة: {strategy_name} كُتبت لـ"
                f"{'، '.join(declared)} وتُختبَر هنا على {epic}.\n"
                f"     النتيجة **بحثٌ من الصفر** لا امتداد لنتيجة سابقة.\n"
            )
        strategy = (
            transplanted(strategy_class, epic) if epic not in declared else strategy_class()
        )
        for resolution in a.resolutions:
            if resolution not in LADDER:
                print(f"  {WARN}○{END} {resolution} — دقّة غير معروفة، تُخطّى")
                continue
            candles = sweep(adapter, epic, resolution)
            if len(candles) < 120:
                print(f"  {WARN}○{END} {epic:<8} {resolution:<10} "
                      f"{len(candles):>5} شمعة — أقلّ من ١٢٠، تُخطّى")
                report["runs"].append({
                    "strategy": strategy_name,
                    "epic": epic, "resolution": resolution, "bars": len(candles),
                    "verdict": "INSUFFICIENT_BARS",
                })
                continue

            bars = to_bars(candles, epic)
            try:
                result = engine.run(strategy, bars, symbol=epic)
            except InsufficientData as exc:
                print(f"  {WARN}○{END} {epic:<8} {resolution:<10} {exc}")
                report["runs"].append({
                    "strategy": strategy_name,
                    "epic": epic, "resolution": resolution, "bars": len(bars),
                    "verdict": "INSUFFICIENT_DATA", "detail": str(exc),
                })
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"  {BAD}⛔{END} {epic:<8} {resolution:<10} "
                      f"{type(exc).__name__}: {exc}")
                report["runs"].append({
                    "strategy": strategy_name,
                    "epic": epic, "resolution": resolution, "bars": len(bars),
                    "verdict": "ERROR", "detail": f"{type(exc).__name__}: {exc}",
                })
                continue

            code, sentence = verdict(result, config.min_trades_for_conclusion, breakeven)
            report["runs"].append({
                "strategy": strategy_name,
                "epic": epic,
                "resolution": resolution,
                "bars": len(bars),
                "from": bars[0].start_utc.isoformat(),
                "to": bars[-1].start_utc.isoformat(),
                "trades": result.trade_count,
                "wins": result.wins,
                "losses": result.losses,
                "win_rate": None if result.win_rate is None else str(result.win_rate),
                "expectancy": None if result.expectancy is None else str(result.expectancy),
                "net_pnl": str(result.net_pnl),
                "profit_factor": (
                    None if result.profit_factor is None else str(result.profit_factor)
                ),
                "max_drawdown": str(result.max_drawdown),
                "warnings": list(result.warnings),
                "verdict": code,
                "verdict_ar": sentence,
                "run_id": result.run_id,
                "config_digest": result.config_digest,
            })
            mark = {"ABOVE_BREAKEVEN": f"{OK}✅{END}",
                    "BELOW_BREAKEVEN": f"{BAD}❌{END}",
                    "LOSING": f"{BAD}❌{END}",
                    "INDISTINGUISHABLE": f"{WARN}≈{END}"}.get(code, f"{WARN}○{END}")
            print(f"  {mark} {epic:<8} {resolution:<10} {len(bars):>5} شمعة · "
                  f"{result.trade_count:>3} صفقة · {sentence}")

def finish(report: dict, report_path: str) -> int:
    """يكتب التقرير ويطبع الخلاصة. فُصلت عن `main` حين صار المسح
    يمرّ على أكثر من استراتيجية — فلا تُكرَّر الخلاصة لكلٍّ منها."""
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    conclusive = [r for r in report["runs"] if r["verdict"] in
                  ("ABOVE_BREAKEVEN", "BELOW_BREAKEVEN")]
    above = [r for r in conclusive if r["verdict"] == "ABOVE_BREAKEVEN"]
    unclear = [r for r in report["runs"] if r["verdict"] == "INDISTINGUISHABLE"]
    declined = [r for r in report["runs"] if r["verdict"] == "DECLINED_INSTRUMENT"]

    losing = [r for r in report["runs"] if r["verdict"] == "LOSING"]
    measured = [r for r in report["runs"]
                if r["verdict"] in ("ABOVE_BREAKEVEN", "BELOW_BREAKEVEN",
                                    "INDISTINGUISHABLE", "LOSING")]

    print(f"\n{DIM}   التقرير: {report_path}{END}")
    # الترتيب مقصود: الأخصّ أوّلاً. وكان «لا نتيجة حاسمة» يسبق الجميع فيبتلع
    # أحكاماً وقعت فعلاً — أربعة إعدادات حُكم عليها، والخلاصة تقول «لم يُبلَغ
    # الحدّ الأدنى». خلاصةٌ تناقض سطورها التي فوقها.
    if declined:
        print(f"\n{BAD}⛔ لم يُقَس شيء: الاستراتيجية لا تقبل الأداة المطلوبة.{END}")
        print(f"{DIM}  ليست «لا حافّة» ولا «عيّنة صغيرة» — هي أنها لم تنظر إلى البيانات.{END}\n")
    elif losing and not above:
        print(f"\n{BAD}❌ {len(losing)} من {len(measured)} إعداد **خاسر بالصافي**.{END}")
        print(f"{DIM}  معدّل الفوز فوق التعادل لا ينفع حين يكون المال الخارج أكثر من الداخل.{END}")
        print(f"{DIM}  وهذا **جوابٌ نافع**: لا تُبنى بنية إطلاق فوق حافّة غير موجودة.{END}\n")
    elif above:
        print(f"\n{OK}✅ {len(above)} إعداد فوق التعادل بفارق يُعتدّ به وبصافٍ موجب.{END}")
        print(f"{DIM}  إشارة أوّلية لا اعتماد — والقياس داخل العيّنة.{END}")
        print(f"{DIM}  البوابة التالية: Walk-forward خارج العيّنة، ثم Shadow.{END}\n")
    elif unclear:
        print(f"\n{WARN}≈ {len(unclear)} إعداد رابح بالصافي ولا يُفرَّق عن التعادل.{END}")
        print(f"{DIM}  العيّنة أصغر من أن تُظهر فارقاً بهذا الحجم — والبناء عليه بناءٌ على ضجيج.{END}\n")
    elif not measured:
        print(f"\n{WARN}○ لا نتيجة: لم تبلغ أي دقّة الحدّ الأدنى للصفقات.{END}")
        print(f"{DIM}  الشموع وصلت وقُرئت، لكن الإشارات أقلّ من أن يُحكَم عليها.{END}\n")
    else:
        print(f"\n{BAD}❌ لا إعداد فوق حدّ التعادل بعد التكلفة الحقيقية.{END}\n")

    print(f"{DIM}   لم يُرسل أمر، ولم يُفتح قفل.{END}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
