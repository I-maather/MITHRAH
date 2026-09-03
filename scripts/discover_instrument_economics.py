#!/usr/bin/env python3
"""
قياس اقتصاديات الأدوات من الوسيط — **قراءة محضة، ولا أمر يُرسَل.**

    /opt/mathrah/.venv/bin/python ../scripts/discover_instrument_economics.py

## السؤال الذي يجيبه

**بأي شروطٍ يقبل هذا الوسيط صفقةً على هذه الأداة؟** أدنى مسافة وقف، وحجم
النقطة، وأصغر كمية، والهامش، والسبريد. وبلا هذه الخمسة لا يُحسَب حجمٌ ولا
مخاطرةٌ ولا حدُّ تعادل — ويُرسَل الأمر ليُرفَض.

## لماذا لزم

المشروع يملك نموذج تكلفةٍ واحداً لليورو، وقيمُه **من صفحة كابيتال العامة
لا من الحساب** (`PROVISIONAL_PUBLIC_SITE`). فقائمة التنفيذ أداةٌ واحدة،
والنظام يمسح أربعاً: ثلاثٌ تُمسح ولا تُنفَّذ، والرابعة تُنفَّذ بافتراض.

وأثرُه على المالكة: إشارةٌ كل أسبوعين بدل واحدة كل أربعة أيام.

## السبريد يُرصَد لا يُفترَض — ويُذكر عدد رصداته

السبريد متغيّر: يتّسع عند الأخبار وفي فجوة الجلسات. ورصدةٌ واحدة **ليست
قياساً**، ولذلك تُؤخذ عدّة رصدات ويُحفَظ **أوسعها** لا متوسّطها: نموذج
التكلفة يجب أن يكون متحفّظاً، وتقديرٌ متفائل للسبريد يجعل كل حساب تعادلٍ
أقلّ من الحقيقة.

ويُحفَظ عدد الرصدات معه، كي يُقرأ الرقم بما يستحقّ من ثقة.

## وما لا يفعله

لا يفتح قفل تنفيذ، ولا يرسل أمراً، ولا يكتب في إعدادات الخدمة. يقرأ
ويكتب ملفاً واحداً: `data/instrument-economics.json`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

OK, BAD, WARN, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

#: عدد رصدات السبريد والفاصل بينها. قليلٌ عمداً: الغرض ألّا نبني على رصدةٍ
#: واحدة، لا أن نُنشئ سلسلةً زمنية.
SPREAD_SAMPLES = 5
SPREAD_PAUSE_SECONDS = 1.2


def _s(value) -> str | None:
    return None if value is None else str(value)


def main() -> int:
    ap = argparse.ArgumentParser(description="قياس اقتصاديات الأدوات من الوسيط")
    ap.add_argument("--source", choices=["demo", "live"], default="demo")
    ap.add_argument("--epics", nargs="*", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    from app.brokers.capital.adapter import DEFAULT_DISCOVERY_ALLOWLIST
    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.factory import build_capital_adapter
    from app.config import get_settings
    from app.risk.capital_costs import ValueProvenance
    from app.risk.instrument_registry import DEFAULT_PATH
    from app.secretstore.provider import build_secret_provider

    settings = get_settings()
    env = CapitalEnvironment.DEMO if a.source == "demo" else CapitalEnvironment.LIVE
    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)
    adapter = build_capital_adapter(env, secrets=secrets)
    adapter.connect()
    print(f"\n{OK}✅{END} متصل — {adapter.name} (قراءة فقط)\n")

    epics = [e.upper() for e in (a.epics or sorted(DEFAULT_DISCOVERY_ALLOWLIST))]
    out_path = Path(a.out) if a.out else DEFAULT_PATH
    rows: dict[str, dict] = {}

    for epic in epics:
        try:
            details = adapter.get_instrument_details(epic)
        except Exception as exc:  # noqa: BLE001
            print(f"  {BAD}⛔{END} {epic:<8} تعذّر القياس: {type(exc).__name__}: {exc}")
            continue

        # **السبريد من اللقطات نفسها.** الوسيط لا يعلنه رقماً؛ يُقرأ من الفرق
        # بين الطلب والعرض، ويؤخذ أوسع ما رُصد.
        widest: Decimal | None = None
        samples = 0
        for _ in range(SPREAD_SAMPLES):
            try:
                market = adapter.get_market(epic)
                bid = getattr(market.snapshot, "bid", None)
                offer = getattr(market.snapshot, "offer", None)
                if bid is not None and offer is not None and offer > bid:
                    observed = offer - bid
                    widest = observed if widest is None else max(widest, observed)
                    samples += 1
            except Exception:  # noqa: BLE001
                pass
            time.sleep(SPREAD_PAUSE_SECONDS)

        if details.pip_size is None:
            print(f"  {WARN}○{END} {epic:<8} حجم النقطة غير معروف — تُترك بلا قياس.")
            continue

        rows[epic] = {
            "epic": epic,
            "pip_size": _s(details.pip_size),
            "lot_size": _s(details.lot_size or 1),
            "min_deal_size": _s(details.min_quantity),
            "size_increment": _s(details.quantity_increment or 1),
            "margin_factor": _s(details.margin_factor),
            "margin_factor_unit": details.margin_factor_unit or "PERCENTAGE",
            # **الوحدة تُحفَظ مع القيمة.** حُفِظت من قبل بلا وحدة، فقُرئت
            # سعراً وهي نسبة — ورُفضت ٤٨٦ إشارة من ٤٨٦ بسببها.
            "min_stop_distance": _s(details.min_stop_distance),
            "min_stop_distance_unit": details.min_stop_distance_unit,
            "min_guaranteed_stop_distance": _s(details.min_guaranteed_stop_distance),
            "min_guaranteed_stop_distance_unit": details.min_guaranteed_stop_distance_unit,
            "guaranteed_stop_available": bool(details.guaranteed_stop_available),
            # **لا تُملأ عملةُ التسعير صامتة.**
            #
            # كان `... or details.currency or "USD"`، و`details.currency`
            # نفسها مشتقّةٌ من `market.quote_currency or "USD"` — أي أن
            # الغياب يصير «دولاراً» بمرورين. فكُتب لـUSD/JPY أنها مسعَّرة
            # بالدولار، وهي بالين؛ ومسار التنفيذ يعرف الحقيقة من قائمته
            # فيعزلها، والملف يقول غير ذلك. طرفان لحقيقةٍ واحدة.
            #
            # والغياب يُكتب `null`، وطبقةُ الأهلية تقول صراحةً إنها مفترضة.
            "quote_currency": details.quote_currency or None,
            "overnight_fee_rate_daily": _s(details.overnight_fee),
            "spread_price": _s(widest),
            "spread_samples": samples,
            "provenance": ValueProvenance.BROKER_DISCOVERY.value,
            "measured_at_utc": datetime.now(timezone.utc).isoformat(),
            "market_status": getattr(details, "market_status", None),
        }

        # المسافة تُعرَض **بعد حلّ وحدتها** عند السعر الحالي، لا خاماً.
        reference = None
        try:
            q = adapter.get_market_data(epic)
            reference = getattr(q, "mid", None) or getattr(q, "last", None) or getattr(q, "bid", None)
        except Exception:  # noqa: BLE001
            reference = None
        min_stop_price = details.min_stop_price_at(reference)
        stop_pips = (
            min_stop_price / details.pip_size if min_stop_price is not None else None
        )
        spread_pips = widest / details.pip_size if widest is not None else None
        print(
            f"  {OK}✅{END} {epic:<8} "
            f"أدنى وقف {stop_pips if stop_pips is not None else '؟':>7} نقطة · "
            f"سبريد {spread_pips if spread_pips is not None else '؟'} نقطة ({samples} رصدة) · "
            f"أصغر كمية {details.min_quantity} · هامش {details.margin_factor}{details.margin_factor_unit}"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "generated_utc": datetime.now(timezone.utc).isoformat(),
                "source": adapter.name,
                "note_ar": (
                    "قياسٌ من الوسيط. أداةٌ غير مذكورة هنا **غير قابلة للتنفيذ** — "
                    "ولا يُفترَض لها شيء."
                ),
                "instruments": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n{DIM}   كُتب: {out_path}{END}")

    from app.risk.instrument_registry import InstrumentRegistry

    registry = InstrumentRegistry.load(out_path)
    executable = sorted(registry.executable_epics(within=DEFAULT_DISCOVERY_ALLOWLIST))
    print(f"\n{OK}✅{END} قابلة للتنفيذ: {'، '.join(executable) if executable else 'لا شيء'}")
    for epic in epics:
        if epic not in executable:
            print(f"   {WARN}○{END} {registry.why_not(epic)}")
    print(f"\n{DIM}   لم يُرسل أمر، ولم يُفتح قفل.{END}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
