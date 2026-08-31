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
import sys
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

#: حدّ التعادل المحسوب عند R:R صافٍ 1.75 — مصدره §5 في `PROJECT-TRUTH`.
BREAKEVEN_WIN_RATE = 0.364

OK, BAD, WARN, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


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
        out = list(got) + out
        end = start
    return out


def verdict(result, minimum: int) -> tuple[str, str]:
    """(الرمز، الحكم) — ثلاث حالات لا اثنتان: **غير حاسم ليس فشلاً**."""
    if result.trade_count < minimum:
        return "INCONCLUSIVE", (
            f"{result.trade_count} صفقة أقلّ من {minimum} — لا يُستنتج منها شيء."
        )
    if result.win_rate is None:
        return "INCONCLUSIVE", "لا معدّل فوز محسوب."
    if float(result.win_rate) > BREAKEVEN_WIN_RATE:
        return "ABOVE_BREAKEVEN", (
            f"{float(result.win_rate) * 100:.1f}٪ فوق حدّ التعادل "
            f"{BREAKEVEN_WIN_RATE * 100:.1f}٪ — إشارة أوّلية لا اعتماد."
        )
    return "BELOW_BREAKEVEN", (
        f"{float(result.win_rate) * 100:.1f}٪ تحت حدّ التعادل — لا حافّة في هذا الإعداد."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="مسح التاريخ وقياس الاستراتيجية عليه")
    ap.add_argument("--source", choices=["live", "demo"], default="live")
    ap.add_argument("--epics", nargs="*", default=list(PRICED_EPICS))
    ap.add_argument("--resolutions", nargs="*", default=list(LADDER))
    ap.add_argument("--stop-pips", default="30")
    ap.add_argument("--tp-pips", default="60")
    ap.add_argument("--size", default="100")
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

    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.factory import build_capital_adapter
    from app.config import get_settings
    from app.contracts import StopKind
    from app.money import D
    from app.risk.capital_costs import PROVISIONAL_EURUSD, CapitalComCostModel
    from app.secretstore.provider import build_secret_provider
    from app.strategies.backtest import BacktestConfig, Backtester, InsufficientData
    from app.strategies.trend_pullback_v1 import TrendPullbackV1

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
    engine = Backtester(cost_model=CapitalComCostModel(PROVISIONAL_EURUSD), config=config)

    report: dict = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "config": {
            "size": a.size, "stop_pips": a.stop_pips, "tp_pips": a.tp_pips,
            "breakeven_win_rate": BREAKEVEN_WIN_RATE,
            "cost_model": "PROVISIONAL_EURUSD",
        },
        "runs": [],
    }

    for epic in a.epics:
        for resolution in a.resolutions:
            if resolution not in LADDER:
                print(f"  {WARN}○{END} {resolution} — دقّة غير معروفة، تُخطّى")
                continue
            candles = sweep(adapter, epic, resolution)
            if len(candles) < 120:
                print(f"  {WARN}○{END} {epic:<8} {resolution:<10} "
                      f"{len(candles):>5} شمعة — أقلّ من ١٢٠، تُخطّى")
                report["runs"].append({
                    "epic": epic, "resolution": resolution, "bars": len(candles),
                    "verdict": "INSUFFICIENT_BARS",
                })
                continue

            bars = to_bars(candles, epic)
            try:
                result = engine.run(TrendPullbackV1(), bars, symbol=epic)
            except InsufficientData as exc:
                print(f"  {WARN}○{END} {epic:<8} {resolution:<10} {exc}")
                report["runs"].append({
                    "epic": epic, "resolution": resolution, "bars": len(bars),
                    "verdict": "INSUFFICIENT_DATA", "detail": str(exc),
                })
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"  {BAD}⛔{END} {epic:<8} {resolution:<10} "
                      f"{type(exc).__name__}: {exc}")
                report["runs"].append({
                    "epic": epic, "resolution": resolution, "bars": len(bars),
                    "verdict": "ERROR", "detail": f"{type(exc).__name__}: {exc}",
                })
                continue

            code, sentence = verdict(result, config.min_trades_for_conclusion)
            report["runs"].append({
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
                    "BELOW_BREAKEVEN": f"{BAD}❌{END}"}.get(code, f"{WARN}○{END}")
            print(f"  {mark} {epic:<8} {resolution:<10} {len(bars):>5} شمعة · "
                  f"{result.trade_count:>3} صفقة · {sentence}")

    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    conclusive = [r for r in report["runs"] if r["verdict"] in
                  ("ABOVE_BREAKEVEN", "BELOW_BREAKEVEN")]
    above = [r for r in conclusive if r["verdict"] == "ABOVE_BREAKEVEN"]

    print(f"\n{DIM}   التقرير: {a.report}{END}")
    if not conclusive:
        print(f"\n{WARN}○ لا نتيجة حاسمة: لم تبلغ أي دقّة الحدّ الأدنى للصفقات.{END}")
        print(f"{DIM}  وهذا ليس فشلاً — هو أن العمق المتاح لا يكفي للحكم بعد.{END}\n")
    elif above:
        print(f"\n{OK}✅ {len(above)} من {len(conclusive)} إعداد فوق حدّ التعادل.{END}")
        print(f"{DIM}  إشارة أوّلية لا اعتماد. البوابة التالية: Walk-forward ثم Shadow.{END}\n")
    else:
        print(f"\n{BAD}❌ لا إعداد فوق حدّ التعادل بعد التكلفة الحقيقية.{END}")
        print(f"{DIM}  وهذا **جوابٌ نافع**: لا تُبنى بنية إطلاق فوق حافّة غير موجودة.{END}\n")

    print(f"{DIM}   لم يُرسل أمر، ولم يُفتح قفل.{END}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
