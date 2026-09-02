#!/usr/bin/env python3
"""
Shadow Mode — النظام يقرّر على سوق حيّ ويكتب ما **كان سيفعله**، بلا أمر.

ShadowRunner لا يستورد أي مسار إرسال — قيد بنيوي لا وعد نصي.
ويستعمل evaluate_cfd أي نموذج تكلفة Capital.com، لا عمولات IBKR.

    python3 scripts/run_shadow.py --epic EURUSD --loops 12 --sleep 300
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.brokers.capital.adapter import CapitalComAdapter                      # noqa: E402
from app.brokers.capital.endpoints import CapitalEnvironment                    # noqa: E402
from app.brokers.capital.errors import CapitalAuthError, CapitalAuthLockout     # noqa: E402
from app.brokers.capital.ratelimit import RateLimiter                           # noqa: E402
from app.brokers.capital.safety import LIVE_API_ENABLED, ExecutionLock          # noqa: E402
from app.brokers.capital.session import CapitalSession                          # noqa: E402
from app.brokers.capital.transport import GuardedTransport, HttpxTransport      # noqa: E402
from app.clock import now_utc                                                   # noqa: E402
from app.contracts import Balances, Broker, StopKind                            # noqa: E402
from app.money import D                                                         # noqa: E402
from app.risk.capital_costs import PROVISIONAL_EURUSD, CapitalComCostModel      # noqa: E402
from app.risk.constitution import INITIAL_CAPITAL_USD, RiskLimits, RiskMode     # noqa: E402
from app.risk.engine import RiskEngine, SessionRiskState                        # noqa: E402
from app.secretstore.provider import (                                          # noqa: E402
    REQUIRED_CAPITAL_SECRETS,
    build_secret_provider,
)
from app.strategies.shadow import ShadowRunner                                  # noqa: E402
from app.strategies.trend_pullback_v1 import TrendPullbackV1                    # noqa: E402

sys.path.insert(0, str(REPO / "scripts"))
from run_backtest import to_bars                                                # noqa: E402


def fallback_balances(equity):
    return Balances(
        account_id="SHADOW", currency="USD",
        total_cash=equity, settled_cash=equity, unsettled_cash=D(0),
        committed_cash=D(0), net_liquidation=equity, as_of_utc=now_utc(),
    )


#: نموذج التكلفة **للأداة المطلوبة**، مقروءاً من القياس — أو رفضٌ بسببٍ يُقرأ.
#:
#: كان هنا `CapitalComCostModel(PROVISIONAL_EURUSD)` مهما كانت `--epic`.
#: وحجم نقطة اليورو 0.0001 وحجم نقطة الذهب 0.01 — مئة ضعف؛ وسبريد اليورو
#: 0.00007 وسبريد الذهب 0.75 — عشرة آلاف ضعف. فتشغيلُ هذا السكربت على
#: الذهب كان يُخرج جدول نتائج كامل الثقة وكلّ رقمٍ فيه خاطئ.
#:
#: ولم يكن ذلك ضاراً يوم كُتب: الاستراتيجيات كانت تُعلن `EURUSD` وحدها،
#: فلا تُنتج إشارةً على غيرها. ثم صارت `FX_MARKETS` أربعاً — فانقلب سطرٌ
#: كان صحيحاً إلى سطرٍ يكذب، بلا أن يُلمَس. وهذا صنفُ عطبٍ لا يُكتشف
#: بمراجعة السطر: يُكتشف بسؤال «ما الذي تغيّر تحته؟».
#:
#: و`run_history_sweep.py` يرفض هذا بالضبط منذ يومه. فالرفض ينتقل هنا.
def cost_model_for_or_refuse(epic: str):
    from app.risk.instrument_registry import InstrumentRegistry
    registry = InstrumentRegistry.load()
    model = registry.cost_model_for(epic)
    if model is None or epic.upper() not in registry.executable_epics():
        print(
            f"\u26d4 \u0644\u0627 \u0642\u064a\u0627\u0633 \u0627\u0642\u062a\u0635\u0627\u062f\u064a\u0627\u062a \u0644\u0640{epic}: {registry.why_not(epic)}\n"
            "   \u0648\u0644\u0627 \u064a\u064f\u0633\u0639\u0651\u064e\u0631 \u0628\u0646\u0645\u0648\u0630\u062c \u0623\u062f\u0627\u0629\u064d \u0623\u062e\u0631\u0649: \u062d\u062c\u0645 \u0627\u0644\u0646\u0642\u0637\u0629 \u0648\u0627\u0644\u0633\u0628\u0631\u064a\u062f \u0648\u0627\u0644\u0643\u0645\u064a\u0629\n"
            "   \u0627\u0644\u062f\u0646\u064a\u0627 \u062a\u062e\u062a\u0644\u0641 \u0628\u064a\u0646\u0647\u0627 \u0645\u0626\u0627\u062a \u0627\u0644\u0623\u0636\u0639\u0627\u0641\u060c \u0641\u062a\u062e\u0631\u062c \u0623\u0631\u0642\u0627\u0645\u064c \u0648\u0627\u062b\u0642\u0629 \u0648\u062e\u0627\u0637\u0626\u0629.",
            file=sys.stderr,
        )
        return None
    return model


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Shadow Mode — قرار حيّ بلا تنفيذ")
    p.add_argument("--epic", default="EURUSD")
    p.add_argument("--resolution", default="DAY")
    p.add_argument("--max", type=int, default=200)
    p.add_argument("--loops", type=int, default=1, help="عدد الملاحظات")
    p.add_argument("--sleep", type=int, default=300, help="ثوانٍ بين الملاحظات")
    p.add_argument("--stop-pips", default="30")
    p.add_argument("--tp-pips", default="60")
    p.add_argument("--equity", default=str(INITIAL_CAPITAL_USD))
    a = p.parse_args(argv)

    if LIVE_API_ENABLED:
        print("⛔ قفل Live مفتوح في الكود. توقّف.", file=sys.stderr)
        return 2

    provider = build_secret_provider(
        env_file=REPO / "secrets" / "capital.env", allow_process_env=False
    )
    missing = provider.missing(REQUIRED_CAPITAL_SECRETS)
    if missing:
        print("اعتمادات ناقصة: " + ", ".join(missing), file=sys.stderr)
        return 1

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
    except (CapitalAuthError, CapitalAuthLockout) as exc:
        print(f"⛔ تعذّر الاتصال بالوسيط: {exc}", file=sys.stderr)
        return 1

    equity = D(a.equity)
    limits = RiskLimits.for_mode(RiskMode.VALIDATION, equity, Broker.CAPITAL_COM)
    model = cost_model_for_or_refuse(a.epic)
    if model is None:
        return 2
    runner = ShadowRunner(
        strategy=TrendPullbackV1(),
        cost_model=model,
        risk_engine=RiskEngine(limits),
        stop_distance_pips=D(a.stop_pips),
        take_profit_distance_pips=D(a.tp_pips),
        stop_kind=StopKind.NORMAL,
    )
    state = SessionRiskState(
        baseline_equity=equity, current_equity=equity,
        realized_pnl_today=D(0), realized_pnl_week=D(0), unrealized_pnl=D(0),
        open_positions=0, entry_orders_today=0, consecutive_losses=0,
    )
    balances = fallback_balances(equity)

    print(f"\nShadow — {a.epic} · وضع {limits.mode.value} · رأس مال مرجعي {equity}")
    print("لا أمر يُرسَل. قفل التنفيذ مغلق طوال التشغيل.\n" + "─" * 58)

    for i in range(1, a.loops + 1):
        try:
            bars = to_bars(
                adapter.get_candles(a.epic, resolution=a.resolution, max_bars=a.max), a.epic
            )
            quote = adapter.get_market_data(a.epic)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}] ⛔ تعذّر جلب البيانات: {exc}")
            if i < a.loops:
                time.sleep(a.sleep)
            continue

        obs = runner.observe(
            symbol=a.epic, bars=bars, quote=quote, state=state,
            balances=balances, kill_switch_active=False,
        )
        t = obs.observed_at_utc.astimezone(timezone.utc).strftime("%H:%M")
        mark = "✅ كان سيدخل" if obs.would_have_submitted else "⬜ لا تداول"
        print(f"[{i}] {t}Z  {mark}   {obs.decision.value} · {obs.reason_code or '—'}")
        print(f"      السبب: {obs.reason_ar}")
        print(f"      السبريد {obs.spread} · عمر التسعيرة {obs.quote_age_seconds}ث "
              f"· جودة البيانات {obs.data_verdict}")
        if obs.economics is not None:
            e = obs.economics
            print(f"      الخسارة الكاملة {e.all_in_risk:.4f}$ · التكلفة {e.total_costs:.4f}$ "
                  f"· التعرّض {e.notional_exposure:.2f}$")
        print()

        if i < a.loops:
            time.sleep(a.sleep)

    total = len(runner.session.observations)
    would = sum(1 for o in runner.session.observations if o.would_have_submitted)
    print("─" * 58)
    print(f"  ملاحظات: {total}   ·   كان سيدخل في {would} منها")
    print("  لم يُرسَل أمر واحد.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
