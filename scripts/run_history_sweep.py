"""
مسح التاريخ الكامل — يقرأ ما يسمح به الوسيط ويقيس عليه.

    backend/.venv/bin/python scripts/run_history_sweep.py --source live

## لماذا سكربت منفصل عن run_backtest

`run_backtest` يقرأ نافذةً واحدة (`max` شمعة على دقّة واحدة)، وسقف الوسيط
٢٠٠ شمعة لكل نداء. فطلب «التاريخ الكامل» لا يُنفَّذ بتمرير رقم أكبر: يُنفَّذ
بالنزول في الزمن نداءً بعد نداء (`from`/`to`)، وعبر أكثر من دقّة.

## ما يقيسه

على كل دقّة، وعلى كل أداة، يمرّر الشموع على الاستراتيجية ويعدّ:

  * الفرص التي تجاوزت عتبة الجودة
  * أيّها كان سيُنفَّذ فعلاً بعد حدود المخاطرة وحجم الحساب
  * الرابح والخاسر، والعائد إلى المخاطرة المُلاحَظ
  * أطول سلسلة خسائر، وأكبر تراجع

## ما لا يفعله

**لا يرسل أمراً، ولا يفتح قفلاً، ولا يغيّر إعداداً.** قراءةٌ وحساب وتقرير.
والوصول إلى الحساب الحقيقي يمرّ من القائمة البيضاء نفسها: GET فقط.

## قيدٌ مُعلَن

سقف الوسيط ٢٠٠ شمعة لكل نداء، والعمق المتاح يختلف بالدقّة: الدقيقة تعود
أسابيع، واليوم يعود سنوات. فـ«التاريخ الكامل» هنا يعني **أقصى ما يعطيه
الوسيط**، لا أكثر — ولا يُدَّعى غير ذلك.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

#: الدقّة → (طول الشمعة، عدد النداءات المطلوبة للنزول عميقاً)
LADDER = {
    "DAY": (timedelta(days=1), 10),
    "HOUR_4": (timedelta(hours=4), 12),
    "HOUR": (timedelta(hours=1), 12),
    "MINUTE_15": (timedelta(minutes=15), 12),
}
PAGE = 200  # سقف الوسيط لكل نداء

DEFAULT_EPICS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]


def fetch_window(adapter, epic: str, resolution: str, start, end):
    """نداء واحد بنافذة زمنية. يعيد [] عند أي رفض بدل أن يوقف المسح كلّه."""
    from app.brokers.capital.endpoints import prices_path

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
        print(f"      ⚠️  {epic}/{resolution}: {type(exc).__name__}")
        return []
    from app.brokers.capital.models import CapitalCandle

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


def main() -> None:
    ap = argparse.ArgumentParser(description="مسح التاريخ وقياس الاستراتيجية عليه")
    ap.add_argument("--source", choices=["live", "demo"], default="live")
    ap.add_argument("--epics", nargs="*", default=DEFAULT_EPICS)
    ap.add_argument("--report", default=str(REPO / "data" / "history-sweep.json"))
    a = ap.parse_args()

    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.factory import build_capital_adapter
    from app.config import get_settings
    from app.secretstore.provider import build_secret_provider

    settings = get_settings()
    env = CapitalEnvironment.LIVE if a.source == "live" else CapitalEnvironment.DEMO
    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)
    adapter = build_capital_adapter(env, secrets=secrets)
    adapter.connect()
    print(f"✅ متصل — {adapter.name} (قراءة فقط)\n")

    from app.backtest.runner import Backtester  # نفس المحرّك الذي يستعمله run_backtest
    from scripts.run_backtest import to_bars     # نفس التحويل، بلا ازدواج منطق

    report: dict = {"generated_utc": datetime.now(timezone.utc).isoformat(), "runs": []}
    for epic in a.epics:
        for resolution in LADDER:
            candles = sweep(adapter, epic, resolution)
            if len(candles) < 120:
                print(f"  {epic:<8} {resolution:<10} {len(candles):>5} شمعة — أقلّ من ١٢٠، تُخطّى")
                continue
            bars = to_bars(candles, epic)
            try:
                result = Backtester().run(bars)
                row = {
                    "epic": epic,
                    "resolution": resolution,
                    "bars": len(bars),
                    "from": str(bars[0].timestamp),
                    "to": str(bars[-1].timestamp),
                    "result": getattr(result, "as_dict", lambda: str(result))(),
                }
            except Exception as exc:  # noqa: BLE001
                row = {"epic": epic, "resolution": resolution, "bars": len(bars),
                       "error": f"{type(exc).__name__}: {exc}"}
            report["runs"].append(row)
            print(f"  {epic:<8} {resolution:<10} {len(bars):>5} شمعة  "
                  f"{bars[0].timestamp} → {bars[-1].timestamp}")

    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                              encoding="utf-8")
    print(f"\n✅ التقرير: {a.report}")
    print("   لم يُرسل أمر، ولم يُفتح قفل.")


if __name__ == "__main__":
    main()
