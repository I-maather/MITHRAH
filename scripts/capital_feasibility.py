#!/usr/bin/env python3
"""
Capital Feasibility Report generator.

يولّد docs/CAPITAL_FEASIBILITY.md من نفس نموذج التكلفة الذي يستعمله Risk Engine،
حتى لا يكون التقرير ادعاءً نصياً منفصلاً عن الكود.

    python3 scripts/capital_feasibility.py            # يطبع
    python3 scripts/capital_feasibility.py --write    # يكتب docs/CAPITAL_FEASIBILITY.md
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.money import D  # noqa: E402
from app.risk.constitution import (  # noqa: E402
    INITIAL_CAPITAL_USD,
    MODE_SPECS,
    RiskLimits,
    RiskMode,
)
from app.risk.costs import (  # noqa: E402
    IBKR_PRO_FIXED_US_STOCK,
    IBKR_PRO_TIERED_US_STOCK,
    CostAssumptions,
    estimate_trade_cost,
)
from app.risk.sizing import size_position  # noqa: E402

CAPITALS = [D("150"), D("300"), D("500"), D("1000"), D("1500"), D("2500"), D("5000")]

# أدوات واقعية عالية السيولة (أسعار افتراضية تقريبية لأغراض النمذجة فقط،
# وليست أسعاراً حية — النظام لا يتداول بناءً عليها).
INSTRUMENTS = [
    ("SPY", D("640.00"), D("0.01")),
    ("QQQ", D("580.00"), D("0.01")),
    ("IVV", D("645.00"), D("0.02")),
    ("XLU", D("85.00"), D("0.01")),
]

STOP_PCTS = [D("0.010"), D("0.015"), D("0.020")]


def fmt(d: Decimal, places: int = 2) -> str:
    return f"{d:.{places}f}"


def scenario_rows():
    rows = []
    assumptions = CostAssumptions.default()
    for capital in CAPITALS:
        limits = RiskLimits.for_mode(RiskMode.VALIDATION, capital)
        for schedule_key, schedule in (("Tiered", IBKR_PRO_TIERED_US_STOCK), ("Fixed", IBKR_PRO_FIXED_US_STOCK)):
            for symbol, price, spread in INSTRUMENTS[:1]:  # SPY as the reference instrument
                for stop_pct in STOP_PCTS:
                    stop_price = price * (Decimal("1") - stop_pct)
                    a = CostAssumptions(
                        spread_abs=spread,
                        slippage_pct_per_leg=assumptions.slippage_pct_per_leg,
                        currency_conversion_pct=Decimal("0"),
                    )
                    for budget_name, budget in (
                        ("target", limits.target_risk_per_trade),
                        ("max", limits.max_risk_per_trade),
                    ):
                        res = size_position(
                            entry_price=price,
                            stop_price=stop_price,
                            risk_budget=budget,
                            schedule=schedule,
                            assumptions=a,
                            fractional_allowed=True,
                            available_cash=capital,
                            limits=limits,
                        )
                        rows.append(
                            {
                                "capital": capital,
                                "schedule": schedule_key,
                                "symbol": symbol,
                                "stop_pct": stop_pct,
                                "budget_name": budget_name,
                                "budget": budget,
                                "result": res,
                            }
                        )
    return rows


def min_viable_capital(schedule, stop_pct: Decimal, price: Decimal, spread: Decimal,
                       mode: RiskMode = RiskMode.VALIDATION) -> Decimal | None:
    """أصغر رأس مال يجعل صفقة عند *ميزانية المخاطرة المستهدفة* (0.25%) تمر كل الفحوص."""
    a = CostAssumptions(spread_abs=spread, slippage_pct_per_leg=D("0.0005"), currency_conversion_pct=D("0"))
    lo, hi = D("100"), D("100000")
    stop_price = price * (Decimal("1") - stop_pct)

    def ok(c: Decimal) -> bool:
        limits = RiskLimits.for_mode(mode, c)
        return size_position(
            entry_price=price,
            stop_price=stop_price,
            risk_budget=limits.target_risk_per_trade,
            schedule=schedule,
            assumptions=a,
            fractional_allowed=True,
            available_cash=c,
            limits=limits,
        ).approved

    if not ok(hi):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return hi.quantize(Decimal("1"))


def build_report() -> str:
    rows = scenario_rows()
    lines: list[str] = []
    A = lines.append

    A("# Capital Feasibility Report — تقرير جدوى رأس المال")
    A("")
    A("> مُولَّد آلياً بواسطة `scripts/capital_feasibility.py` من نفس نموذج التكلفة")
    A("> الذي يستعمله Risk Engine. لا أرقام مكتوبة يدوياً في هذا الملف.")
    A("")
    A("## 0. المدخلات الثابتة")
    A("")
    A("| البند | القيمة | المصدر |")
    A("|---|---|---|")
    A(f"| رأس المال الحقيقي | {fmt(INITIAL_CAPITAL_USD)} USD | تصحيح المالكة النهائي 2026-08-28 |")
    A(f"| المخاطرة المستهدفة/صفقة (VALIDATION) | {fmt(MODE_SPECS[RiskMode.VALIDATION].target_risk_pct * 100, 2)}% | دستور المخاطر |")
    A(f"| الحد الأقصى المطلق/صفقة (VALIDATION) | {fmt(MODE_SPECS[RiskMode.VALIDATION].max_risk_pct * 100, 2)}% | دستور المخاطر |")
    A(f"| المخاطرة القصوى/صفقة (CONSERVATIVE_LIVE) | {fmt(MODE_SPECS[RiskMode.CONSERVATIVE_LIVE].max_risk_pct * 100, 2)}% all-in | دستور المخاطر |")
    A(f"| عمولة IBKR Pro Tiered | {IBKR_PRO_TIERED_US_STOCK.per_share}/سهم، حد أدنى {IBKR_PRO_TIERED_US_STOCK.min_per_order}، حد أقصى 1% من قيمة الصفقة | [IBKR]({IBKR_PRO_TIERED_US_STOCK.source_url}) — تُحقق {IBKR_PRO_TIERED_US_STOCK.verified_on} |")
    A(f"| عمولة IBKR Pro Fixed | {IBKR_PRO_FIXED_US_STOCK.per_share}/سهم، حد أدنى {IBKR_PRO_FIXED_US_STOCK.min_per_order}، حد أقصى 1% من قيمة الصفقة | [IBKR]({IBKR_PRO_FIXED_US_STOCK.source_url}) — تُحقق {IBKR_PRO_FIXED_US_STOCK.verified_on} |")
    A(f"| رسوم SEC (بيع) | {IBKR_PRO_TIERED_US_STOCK.sec_fee_rate} × قيمة البيع | نفس المصدر |")
    A(f"| رسوم FINRA TAF (بيع) | {IBKR_PRO_TIERED_US_STOCK.finra_taf_per_share} × عدد الأسهم المباعة | نفس المصدر |")
    A("| الانزلاق المفترض | 5 نقاط أساس لكل ساق | افتراض متحفظ — يجب قياسه من Paper قبل Live |")
    A(f"| حد سيطرة التكلفة | الاحتكاك ≤ {fmt(MODE_SPECS[RiskMode.VALIDATION].max_cost_ratio_of_risk * 100, 0)}% من ميزانية المخاطرة | حاجز هندسي |")
    A(f"| حد نقطة التعادل | ≤ {fmt(MODE_SPECS[RiskMode.VALIDATION].max_breakeven_move_pct * 100, 2)}% حركة سعرية | حاجز هندسي |")
    A("")
    A("**ملاحظة حاسمة:** IBKR Lite (بلا عمولة) متاح لـ *US Residents Only*، لذلك")
    A("المقيمة في السعودية تخضع لتسعير IBKR Pro بعمولة. هذا يغيّر كل الحساب.")
    A("")

    A("## 1. هل يمكن تنفيذ صفقة كاملة (دخول + خروج) ضمن مخاطرة 0.50 دولار؟")
    A("")
    A("النتائج على SPY بسعر مرجعي 640.00 دولار وسبريد 0.01:")
    A("")
    A("| رأس المال | التسعير | مسافة الستوب | ميزانية المخاطرة | القرار | الكمية | قيمة الصفقة | الاحتكاك | أقصى خسارة | نسبة الاحتكاك |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        res = r["result"]
        est = res.estimate
        decision = "✅ مقبولة" if res.approved else f"❌ {res.reason_code}"
        if est and res.approved:
            qty = fmt(res.quantity, 4)
            notional = fmt(est.notional)
            costs = fmt(est.total_costs)
            total = fmt(est.total_risk)
            ratio = fmt(est.cost_ratio * 100, 1) + "%"
        else:
            qty = notional = costs = total = ratio = "—"
        A(
            f"| {fmt(r['capital'], 0)} | {r['schedule']} | {fmt(r['stop_pct'] * 100, 1)}% | "
            f"{fmt(r['budget'])} ({r['budget_name']}) | {decision} | {qty} | {notional} | {costs} | {total} | {ratio} |"
        )
    A("")

    A("## 2. الحد الأدنى الواقعي لرأس المال")
    A("")
    A("أصغر رأس مال تمر عنده صفقة عند **المخاطرة المستهدفة 0.25%** بكل الفحوص:")
    A("")
    A("| التسعير | مسافة الستوب | الحد الأدنى لرأس المال |")
    A("|---|---|---|")
    for schedule_key, schedule in (("Tiered", IBKR_PRO_TIERED_US_STOCK), ("Fixed", IBKR_PRO_FIXED_US_STOCK)):
        for stop_pct in STOP_PCTS:
            mv = min_viable_capital(schedule, stop_pct, D("640.00"), D("0.01"))
            A(f"| {schedule_key} | {fmt(stop_pct * 100, 1)}% | {'—' if mv is None else fmt(mv, 0) + ' USD'} |")
    A("")

    A("## 2-ب. الحد الأدنى لرأس المال في وضع CONSERVATIVE_LIVE (مخاطرة 1% all-in)")
    A("")
    A("| التسعير | مسافة الستوب | الحد الأدنى لرأس المال |")
    A("|---|---|---|")
    for schedule_key, schedule in (("Tiered", IBKR_PRO_TIERED_US_STOCK), ("Fixed", IBKR_PRO_FIXED_US_STOCK)):
        for stop_pct in STOP_PCTS:
            mv = min_viable_capital(schedule, stop_pct, D("640.00"), D("0.01"),
                                    mode=RiskMode.CONSERVATIVE_LIVE)
            A(f"| {schedule_key} | {fmt(stop_pct * 100, 1)}% | {'—' if mv is None else fmt(mv, 0) + ' USD'} |")
    A("")

    A("## 2-ج. وضع LIVE_COMMISSIONING — الصفقة التجريبية الواحدة")
    A("")
    A("الحواجز الاقتصادية معطّلة في هذا الوضع عمداً (الغرض اختبار تكامل لا ربح).")
    A("")
    A("| قيمة الأمر | العمولة ذهاباً وإياباً | خسارة السعر عند ستوب 3% | أقصى خسارة إجمالية | ضمن حد 0.75؟ |")
    A("|---|---|---|---|---|")
    for notional in (D("5.00"), D("7.50"), D("10.00")):
        price = D("640.00")
        qty = notional / price
        est = estimate_trade_cost(
            quantity=qty, entry_price=price, stop_price=price * D("0.97"),
            schedule=IBKR_PRO_TIERED_US_STOCK, assumptions=CostAssumptions.default(),
            is_fractional=True,
        )
        comm = est.entry_commission + est.exit_commission + est.regulatory_fees
        cap = INITIAL_CAPITAL_USD * MODE_SPECS[RiskMode.LIVE_COMMISSIONING].max_risk_pct
        A(f"| {fmt(notional)} | {fmt(comm)} | {fmt(est.price_risk)} | {fmt(est.total_risk)} | "
          f"{'✅ نعم' if est.total_risk <= cap else '❌ لا'} |")
    A("")

    A("## 3. تكلفة الاحتكاك مقابل رأس المال")
    A("")
    A("جولة كاملة (دخول+خروج) على قيمة صفقة تساوي سُدس رأس المال، تسعير Tiered:")
    A("")
    A("| رأس المال | قيمة الصفقة | عمولة ذهاب+إياب | كنسبة من رأس المال | كنسبة من الحد الأقصى للمخاطرة |")
    A("|---|---|---|---|---|")
    a = CostAssumptions.default()
    for capital in CAPITALS:
        notional = capital / 6
        price = D("640.00")
        qty = notional / price
        if qty <= 0:
            continue
        est = estimate_trade_cost(
            quantity=qty,
            entry_price=price,
            stop_price=price * Decimal("0.985"),
            schedule=IBKR_PRO_TIERED_US_STOCK,
            assumptions=a,
            is_fractional=True,
        )
        comm = est.entry_commission + est.exit_commission + est.regulatory_fees
        max_risk = capital * MODE_SPECS[RiskMode.VALIDATION].max_risk_pct
        A(
            f"| {fmt(capital, 0)} | {fmt(est.notional)} | {fmt(comm)} | "
            f"{fmt(comm / capital * 100, 2)}% | {fmt(comm / max_risk * 100, 0)}% |"
        )
    A("")
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true")
    args = p.parse_args()
    report = build_report()
    if args.write:
        out = ROOT / "docs" / "CAPITAL_FEASIBILITY.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
