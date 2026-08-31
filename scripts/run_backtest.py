#!/usr/bin/env python3
"""
Backtest حقيقي على شموع Capital.com التاريخية.

قراءة فقط: قفل التنفيذ مغلق صراحةً، ولا يُرسَل أمر ولا يُلمَس مركز.
المحرّك (Backtester) ونموذج التكلفة (CapitalComCostModel) موجودان في المشروع
منذ 0.3.x — هذا الملف يصلهما بواجهة تشغيل، لا أكثر.

    python3 scripts/run_backtest.py --epic EURUSD --resolution DAY --max 200
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.brokers.capital.adapter import CapitalComAdapter          # noqa: E402
from app.brokers.capital.endpoints import CapitalEnvironment        # noqa: E402
from app.brokers.capital.errors import CapitalAuthError, CapitalAuthLockout  # noqa: E402
from app.brokers.capital.ratelimit import RateLimiter               # noqa: E402
from app.brokers.capital.safety import LIVE_API_ENABLED, ExecutionLock  # noqa: E402
from app.brokers.capital.session import CapitalSession              # noqa: E402
from app.brokers.capital.transport import GuardedTransport, HttpxTransport  # noqa: E402
from app.contracts import Bar, DataSource, StopKind                 # noqa: E402
from app.money import D                                             # noqa: E402
from app.risk.capital_costs import PROVISIONAL_EURUSD, CapitalComCostModel  # noqa: E402
from app.secretstore.provider import (                              # noqa: E402
    REQUIRED_CAPITAL_SECRETS,
    build_secret_provider,
)
from app.brokers.capital.models import CapitalCandle                    # noqa: E402
from app.live_readonly.session import LiveAuthError, LiveSession        # noqa: E402
from app.live_readonly.transport import LiveReadOnlyTransport           # noqa: E402
from app.strategies.backtest import Backtester, BacktestConfig, InsufficientData  # noqa: E402
from app.strategies.trend_pullback_v1 import TrendPullbackV1        # noqa: E402


def to_bars(candles, symbol: str) -> list[Bar]:
    """شمعة الوسيط تحمل bid وask؛ الاستراتيجية تعمل على الوسط."""
    two = D(2)
    return [
        Bar(
            symbol=symbol,
            start_utc=c.snapshot_time_utc,
            open=(c.open_bid + c.open_ask) / two,
            high=(c.high_bid + c.high_ask) / two,
            low=(c.low_bid + c.low_ask) / two,
            close=(c.close_bid + c.close_ask) / two,
            volume=c.volume if c.volume is not None else D(0),
            source=DataSource.HISTORICAL,
        )
        for c in candles
    ]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Backtest على شموع Capital.com")
    p.add_argument("--source", default="live", choices=["live", "demo"],
                   help="live = الحساب الحقيقي قراءةً فقط (قائمة بيضاء HTTP)")
    p.add_argument("--epic", default="EURUSD")
    p.add_argument("--resolution", default="DAY",
                   choices=["MINUTE", "MINUTE_5", "MINUTE_15", "MINUTE_30",
                            "HOUR", "HOUR_4", "DAY", "WEEK"])
    p.add_argument("--max", type=int, default=200, help="عدد الشموع (سقف الوسيط 200 لكل نداء)")
    p.add_argument("--size", default="100", help="الكمية — الحد الأدنى للوسيط")
    p.add_argument("--stop-pips", default="30")
    p.add_argument("--tp-pips", default="60")
    a = p.parse_args(argv)

    if LIVE_API_ENABLED:
        print("⛔ قفل Live مفتوح في الكود. توقّف.", file=sys.stderr)
        return 2

    provider = build_secret_provider(
        env_file=REPO / "secrets" / "capital.env", allow_process_env=False
    )
    missing = provider.missing(REQUIRED_CAPITAL_SECRETS)
    if missing:
        print("اعتمادات Capital.com ناقصة: " + ", ".join(missing) +
              "\nشغّلي scripts/configure_capital_credentials.sh", file=sys.stderr)
        return 1

    print(f"المصدر: {a.source} · جلب {a.max} شمعة {a.resolution} لـ{a.epic} …")

    if a.source == "live":
        # قراءة فقط: القائمة البيضاء ترفض PUT/PATCH/DELETE دائماً،
        # وتسمح بـPOST /session وحده. لا مسار إرسال في هذا الملف أصلاً.
        session = LiveSession(transport=LiveReadOnlyTransport(), secrets=provider)
        try:
            session.authenticate()
            resp = session.get(f"/api/v1/prices/{a.epic}",
                               params={"resolution": a.resolution, "max": a.max})
        except LiveAuthError as exc:
            print(f"⛔ تعذّرت المصادقة على الحساب الحقيقي: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"⛔ فشل جلب الشموع: {exc}", file=sys.stderr)
            return 1
        finally:
            try:
                session.discard()
            except Exception:  # noqa: BLE001
                pass
        if not getattr(resp, "ok", False) or not isinstance(resp.body, dict):
            print(f"⛔ استجابة أسعار غير صالحة (HTTP {getattr(resp, 'status', '?')}).",
                  file=sys.stderr)
            return 1
        candles = CapitalCandle.parse_list(resp.body)
    else:
        adapter = CapitalComAdapter(
            session=CapitalSession(
                transport=GuardedTransport(
                    inner=HttpxTransport(),
                    execution_lock=ExecutionLock.locked(),
                    rate_limiter=RateLimiter(),
                ),
                secrets=provider,
                environment=CapitalEnvironment.DEMO,
            ),
            execution_lock=ExecutionLock.locked(),
        )
        try:
            adapter.connect()
            candles = adapter.get_candles(a.epic, resolution=a.resolution, max_bars=a.max)
        except (CapitalAuthError, CapitalAuthLockout) as exc:
            print(f"⛔ تعذّر الاتصال بالوسيط: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"⛔ فشل جلب الشموع: {exc}", file=sys.stderr)
            return 1

    bars = to_bars(candles, a.epic)
    if not bars:
        print("⛔ الوسيط أعاد صفر شمعة. المحرّك لا يولّد بيانات.", file=sys.stderr)
        return 1

    model = CapitalComCostModel(PROVISIONAL_EURUSD)
    config = BacktestConfig(
        size=D(a.size),
        stop_distance_pips=D(a.stop_pips),
        take_profit_distance_pips=D(a.tp_pips),
        stop_kind=StopKind.NORMAL,
        allow_overnight=False,
    )
    strategy = TrendPullbackV1()

    try:
        r = Backtester(cost_model=model, config=config).run(strategy, bars, symbol=a.epic)
    except InsufficientData as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 1

    pct = lambda v: "—" if v is None else f"{v * 100:.1f}٪"
    num = lambda v: "—" if v is None else f"{v:.4f}"

    print("\n" + "═" * 58)
    print(f"  {r.strategy_name} v{r.strategy_version}   ·   run {r.run_id}")
    print("═" * 58)
    print(f"  الشموع            {r.bars_count}   ({r.first_bar_utc} → {r.last_bar_utc})")
    print(f"  الصفقات           {r.trade_count}   (رابحة {r.wins} · خاسرة {r.losses})")
    print(f"  معدل الفوز        {pct(r.win_rate)}")
    print(f"  التوقّع للصفقة     {num(r.expectancy)} USD")
    print(f"  صافي الربح        {r.net_pnl:.4f} USD")
    print(f"  عامل الربح        {num(r.profit_factor)}")
    print(f"  أقصى تراجع        {r.max_drawdown:.4f} USD")
    print("─" * 58)

    for w in r.warnings:
        print(f"  ⚠️  {w}")

    need = config.min_trades_for_conclusion
    if r.trade_count < need:
        print(f"\n  ⛔ غير حاسم: {r.trade_count} صفقة أقلّ من {need}."
              f"\n     وسّعي المدى (--resolution HOUR) قبل أي استنتاج.")
    elif r.win_rate is not None and r.win_rate > D("0.364"):
        print(f"\n  ✅ فوق حدّ التعادل 36.4٪ — إشارة أوّلية، وليست اعتماداً."
              f"\n     البوابة التالية: Walk-forward ثم Shadow.")
    else:
        print("\n  ❌ تحت حدّ التعادل 36.4٪ بعد التكلفة — لا حافّة في هذا الإعداد.")

    print("\n  لم يُرسَل أمر. قفل التنفيذ مغلق طوال التشغيل.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
