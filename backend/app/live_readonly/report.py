"""
SANITIZED OUTPUTS — تقريرا الاكتشاف والجدوى، مُنقّيان بالبناء.

ما **لا يظهر أبداً** في أي مخرَج من هذا الملف:
مفتاح API · المعرّف/البريد · كلمة مرور المفتاح · الحمولة المشفّرة ·
`CST` · `X-SECURITY-TOKEN` · معرّف الحساب الكامل · ترويسات خام ·
استجابة مصادقة خام · قيمة 2FA.

الرصيد وعملة الحساب **يظهران في تقرير Markdown** لأنه تقرير مالي محلي
للمالكة — ويُصنَّف صراحةً **معلومة محلية حسّاسة لا تُرفع**.
ملف JSON يبقى في `data/` المُدرَج في `.gitignore`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from ..money import D
from ..profiles import PROFILE_SPECS, ProfileLimits, TradingProfile
from ..secretstore.redaction import redact
from .allowlist import describe_allowlist
from .discovery import LiveDiscoveryReport, LiveInstrumentInfo

#: مفاتيح لا يجوز أن تظهر في JSON بأي حال — فحص أخير قبل الكتابة.
FORBIDDEN_JSON_KEYS: tuple[str, ...] = (
    "apiKey", "api_key", "identifier", "password", "encryptedPassword",
    "cst", "CST", "securityToken", "x-security-token", "accountId",
    "headers", "authorization", "twoFactor", "otp",
)


class SanitisationError(RuntimeError):
    """رُفعت لأن مخرَجاً كان سيحمل ما لا يجوز — لا يُكتب الملف."""


def _fmt(value: Optional[Decimal], places: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{places}f}"


def _assert_sanitised(payload: dict) -> None:
    """فحص متكرر على كل المفاتيح والقيم قبل الكتابة."""
    blob = json.dumps(payload, ensure_ascii=False, default=str)
    for key in FORBIDDEN_JSON_KEYS:
        if f'"{key}"' in blob:
            raise SanitisationError(f"مفتاح محظور في المخرَج: {key}")
    if redact(blob) != blob:
        raise SanitisationError("المخرَج يحتوي قيمة مُسجَّلة كسرّ.")


def write_discovery_json(report: LiveDiscoveryReport, path: Path) -> Path:
    payload = report.as_dict()
    payload["sanitised"] = True
    payload["contains"] = (
        "قيم حساب وأدوات فقط. لا مفاتيح ولا رموز ولا معرّف حساب كامل."
    )
    _assert_sanitised(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def render_discovery_markdown(report: LiveDiscoveryReport) -> str:
    a = report.account
    lines: list[str] = [
        "# Capital.com Live Discovery — اكتشاف الحساب الحقيقي",
        "",
        "> ⚠️ **معلومة محلية حسّاسة.** هذا التقرير يحتوي رصيد حسابك الحقيقي.",
        "> **لا يُرفع إلى مستودع بعيد ولا يُشارَك.** الملف تحت `docs/` محلياً.",
        "",
        "> **قراءة فقط.** لم يُرسل أمر ولا فُتح مركز ولا عُدِّل تفضيل.",
        "> نتيجة هذا التقرير **لا تأذن بالتنفيذ**.",
        "",
        "| البند | القيمة |",
        "|---|---|",
        f"| التوقيت (UTC) | {report.generated_at_utc.isoformat()} |",
        f"| التوقيت (الرياض) | {report.generated_at_riyadh} |",
        "| البيئة | **LIVE — الحساب الحقيقي** |",
        "| الوضع | قراءة فقط بقائمة بيضاء على مستوى HTTP |",
        f"| رموز جلسة محفوظة | {'نعم ⚠️' if report.tokens_retained else 'لا'} |",
        "",
        "## الحساب",
        "",
    ]

    if a is None:
        lines.append("> تعذّر استخراج معلومات الحساب.")
    else:
        lines += [
            "| البند | القيمة |",
            "|---|---|",
            f"| المعرّف (مُقنَّع) | `{a.masked_id}` |",
            f"| العملة | {a.currency or '—'} |",
            f"| النوع | {a.account_type or '—'} |",
            f"| الرصيد | {_fmt(a.balance)} |",
            f"| المتاح | {_fmt(a.available)} |",
            f"| الربح/الخسارة | {_fmt(a.profit_loss)} |",
            f"| الحالة | {a.status or '—'} |",
            f"| وضع التحوّط | {a.hedging_mode if a.hedging_mode is not None else '—'} |",
            f"| التداول مُفعَّل | {a.dealing_enabled if a.dealing_enabled is not None else '—'} |",
        ]
        if a.leverage_preferences:
            lines += ["", "**تفضيلات الرافعة (قراءة فقط):**", ""]
            lines += ["| الفئة | الحالي | الأقصى |", "|---|---|---|"]
            for key, value in sorted(a.leverage_preferences.items()):
                if isinstance(value, dict):
                    lines.append(f"| {key} | {value.get('current', '—')} | {value.get('max', '—')} |")
                else:
                    lines.append(f"| {key} | {value} | — |")

    lines += ["", "## الأدوات", ""]
    lines += [
        "| Epic | الحالة | العرض | الطلب | السبريد | أدنى كمية | الزيادة | "
        "معامل الهامش | أدنى وقف | أدنى وقف مضمون | وقف مضمون |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i in report.instruments:
        if not i.found:
            lines.append(f"| {i.epic} | ⛔ لم تُقرأ | — | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {i.epic} | {i.market_status or '—'} | {_fmt(i.bid, 5)} | {_fmt(i.ask, 5)} | "
            f"{_fmt(i.spread, 5)} | {_fmt(i.min_deal_size, 2)} | {_fmt(i.size_increment, 2)} | "
            f"{_fmt(i.margin_factor, 3)} {i.margin_factor_unit or ''} | "
            f"{_fmt(i.min_stop_distance, 2)} {i.min_stop_distance_unit or ''} | "
            f"{_fmt(i.min_guaranteed_stop_distance, 2)} | "
            f"{i.guaranteed_stop_available if i.guaranteed_stop_available is not None else '—'} |"
        )

    lines += ["", "### تفاصيل إضافية", ""]
    for i in report.instruments:
        if not i.found:
            continue
        lines += [
            f"**{i.epic}**",
            "",
            f"- تعريف النقطة: {i.pip_definition or '—'}",
            f"- حجم العقد: {_fmt(i.contract_size, 2)} · تفسير الكمية: {i.quantity_interpretation or '—'}",
            f"- علاوة الوقف المضمون: {_fmt(i.guaranteed_stop_premium, 4)}",
            f"- تبييت (شراء/بيع): {_fmt(i.overnight_fee_long, 6)} / {_fmt(i.overnight_fee_short, 6)}"
            f" · وقت الاحتساب: {i.overnight_fee_time or '—'}",
            f"- ساعات التداول: {i.trading_hours or '—'}",
            f"- شموع تاريخية: {'متاحة' if i.candles_available else 'غير متاحة'}"
            + (f" ({i.candles_count})" if i.candles_count is not None else ""),
            f"- طزاجة السعر: {('%.0f ثانية' % i.data_age_seconds) if i.data_age_seconds is not None else '—'}",
        ]
        if i.notes:
            lines.append("- ملاحظات: " + "؛ ".join(i.notes))
        lines.append("")

    lines += ["## العمليات المرسَلة فعلاً", ""]
    for method, path in report.operations_sent:
        lines.append(f"- `{method} {path}`")

    allow = describe_allowlist()
    lines += [
        "",
        "## القائمة البيضاء المفروضة على مستوى HTTP",
        "",
        f"- المضيف الوحيد: `{allow['host']}`",
        "- `GET` المسموح: " + "، ".join(f"`{p}`" for p in allow["get_exact"]),
        "- أنماط `GET`: " + "، ".join(f"`{p}`" for p in allow["get_patterns"]),
        "- `POST` الوحيد: " + "، ".join(f"`{p}`" for p in allow["post_exact"]) + " (مصادقة فقط)",
        "- طرق مرفوضة دائماً: " + "، ".join(f"`{m}`" for m in allow["blocked_methods"]),
        "",
    ]

    if report.errors:
        lines += ["## أخطاء مسجّلة", ""]
        lines += [f"- {e}" for e in report.errors]
        lines.append("")

    lines += ["## ملاحظات", ""]
    lines += [f"- {n}" for n in report.notes]
    lines += [
        "",
        "---",
        "",
        "**لم يظهر في هذا التقرير:** مفتاح API · المعرّف · كلمة المرور · "
        "الحمولة المشفّرة · CST · رمز الأمان · معرّف الحساب الكامل · ترويسات خام.",
    ]
    return redact("\n".join(lines))


def write_discovery_markdown(report: LiveDiscoveryReport, path: Path) -> Path:
    text = render_discovery_markdown(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# الجدوى
# ---------------------------------------------------------------------------

STOP_DISTANCES_PIPS: tuple[int, ...] = (25, 50, 75)
SLIPPAGE_RESERVE_PIPS = D("1")
PLANNED_CAPITAL_USD = D("150.00")


@dataclass(frozen=True)
class FeasibilityRow:
    stop_pips: int
    price_loss: Decimal
    spread_cost: Decimal
    slippage_reserve: Decimal
    gsl_premium: Optional[Decimal]
    all_in_risk: Decimal
    net_reward_risk: Decimal
    overnight_one_night: Optional[Decimal]


def _pip_size_for(epic: str) -> Decimal:
    return D("0.01") if epic.upper().endswith("JPY") else D("0.0001")


def compute_feasibility(
    instrument: LiveInstrumentInfo,
    *,
    equity: Decimal,
    quantity: Optional[Decimal] = None,
    take_profit_multiple: Decimal = D("2"),
) -> Optional[dict]:
    """
    يحسب الجدوى من **قيم الوسيط المُكتشَفة**. يعيد `None` إن نقص ما يلزم —
    ولا يُقدَّر أي حقل غائب.
    """
    if not instrument.found or instrument.bid is None or instrument.ask is None:
        return None
    size = quantity or instrument.min_deal_size
    if size is None or size <= 0:
        return None

    pip_size = _pip_size_for(instrument.epic)
    contract = instrument.contract_size or D("1")
    price = instrument.ask
    spread_price = instrument.spread if instrument.spread is not None else D("0")

    pip_value = size * contract * pip_size
    notional = size * contract * price

    margin: Optional[Decimal] = None
    if instrument.margin_factor is not None:
        unit = (instrument.margin_factor_unit or "").upper()
        rate = (
            instrument.margin_factor / D("100")
            if unit in ("PERCENTAGE", "PERCENT", "%")
            else instrument.margin_factor
        )
        margin = notional * rate

    spread_cost = spread_price * size * contract
    slippage = SLIPPAGE_RESERVE_PIPS * pip_value

    overnight: Optional[Decimal] = None
    if instrument.overnight_fee_long is not None:
        overnight = abs(instrument.overnight_fee_long) * notional

    rows: list[FeasibilityRow] = []
    for stop in STOP_DISTANCES_PIPS:
        price_loss = D(stop) * pip_value
        gsl = instrument.guaranteed_stop_premium
        all_in = price_loss + spread_cost + slippage
        gross_reward = D(stop) * take_profit_multiple * pip_value
        net_reward = gross_reward - spread_cost
        rr = (net_reward / all_in) if all_in > 0 else D("0")
        rows.append(FeasibilityRow(
            stop_pips=stop,
            price_loss=price_loss,
            spread_cost=spread_cost,
            slippage_reserve=slippage,
            gsl_premium=gsl,
            all_in_risk=all_in,
            net_reward_risk=rr,
            overnight_one_night=overnight,
        ))

    profiles: dict[str, dict] = {}
    for profile in TradingProfile:
        limits = ProfileLimits.for_profile(profile, equity)
        fits = []
        for row in rows:
            within_risk = row.all_in_risk <= limits.max_risk_per_trade
            meets_rr = row.net_reward_risk >= limits.min_net_reward_risk
            fits.append({
                "stop_pips": row.stop_pips,
                "all_in_risk": f"{row.all_in_risk:.4f}",
                "within_risk_cap": within_risk,
                "net_reward_risk": f"{row.net_reward_risk:.2f}",
                "meets_min_rr": meets_rr,
                "tradable": bool(within_risk and meets_rr),
            })
        profiles[profile.value] = {
            "name_ar": PROFILE_SPECS[profile].name_ar,
            "max_risk_per_trade": f"{limits.max_risk_per_trade:.2f}",
            "min_net_reward_risk": f"{limits.min_net_reward_risk:.2f}",
            "min_quality_score": limits.min_quality_score,
            "stops": fits,
            "any_stop_fits": any(f["tradable"] for f in fits),
        }

    return {
        "epic": instrument.epic,
        "equity_used": f"{equity:.2f}",
        "quantity": f"{size:.2f}",
        "reference_price": f"{price:.5f}",
        "pip_size": str(pip_size),
        "contract_size": f"{contract:.2f}",
        "pip_value": f"{pip_value:.6f}",
        "notional_exposure": f"{notional:.2f}",
        "required_margin": f"{margin:.4f}" if margin is not None else None,
        "spread_price": f"{spread_price:.6f}",
        "spread_cost": f"{rows[0].spread_cost:.6f}",
        "slippage_reserve": f"{rows[0].slippage_reserve:.6f}",
        "guaranteed_stop_premium": (
            f"{instrument.guaranteed_stop_premium:.6f}"
            if instrument.guaranteed_stop_premium is not None else None
        ),
        "guaranteed_stop_available": instrument.guaranteed_stop_available,
        "overnight_one_night": (
            f"{rows[0].overnight_one_night:.6f}"
            if rows[0].overnight_one_night is not None else None
        ),
        "rows": [
            {
                "stop_pips": r.stop_pips,
                "price_loss": f"{r.price_loss:.6f}",
                "spread_cost": f"{r.spread_cost:.6f}",
                "slippage_reserve": f"{r.slippage_reserve:.6f}",
                "all_in_risk": f"{r.all_in_risk:.4f}",
                "net_reward_risk": f"{r.net_reward_risk:.2f}",
            }
            for r in rows
        ],
        "profiles": profiles,
    }


def render_feasibility_markdown(
    report: LiveDiscoveryReport, *, actual: Optional[dict], planned: Optional[dict]
) -> str:
    lines: list[str] = [
        "# جدوى EUR/USD — من قيم الوسيط المُكتشَفة",
        "",
        "> ⚠️ **معلومة محلية حسّاسة** — تحتوي أرقام حسابك. لا تُرفع ولا تُشارَك.",
        "",
        "> **هذه ليست توقّع ربح.** الجدوى هنا تعني: هل تقع الخسارة الكاملة عند",
        "> الوقف ضمن حد الملف؟ لا أكثر. **الكفاية التقنية ≠ الربحية.**",
        "",
        f"مصدر القيم: اكتشاف حقيقي بتاريخ {report.generated_at_riyadh} (الرياض).",
        "",
    ]

    for title, data in (("الرصيد الفعلي", actual), ("رأس المال المخطَّط 150 دولاراً", planned)):
        lines += [f"## {title}", ""]
        if data is None:
            lines += ["> تعذّر الحساب: قيم الأداة ناقصة.", ""]
            continue
        lines += [
            "| البند | القيمة |",
            "|---|---|",
            f"| حقوق الملكية المستعملة | {data['equity_used']} |",
            f"| الكمية | {data['quantity']} |",
            f"| السعر المرجعي | {data['reference_price']} |",
            f"| حجم العقد | {data['contract_size']} |",
            f"| قيمة النقطة | {data['pip_value']} |",
            f"| **قيمة التعرّض** | **{data['notional_exposure']}** |",
            f"| **الهامش المطلوب** | **{data['required_margin'] or '—'}** |",
            f"| تكلفة السبريد | {data['spread_cost']} |",
            f"| احتياطي الانزلاق | {data['slippage_reserve']} |",
            f"| علاوة الوقف المضمون | {data['guaranteed_stop_premium'] or '—'} |",
            f"| تبييت ليلة واحدة | {data['overnight_one_night'] or '—'} |",
            "",
            "**التعرّض والهامش والخسارة ثلاث قيم مختلفة ولا يجوز الخلط بينها.**",
            "",
            "| مسافة الوقف | خسارة السعر | السبريد | الانزلاق | **الخسارة الكلية** | R:R الصافي |",
            "|---|---|---|---|---|---|",
        ]
        for row in data["rows"]:
            lines.append(
                f"| {row['stop_pips']} نقطة | {row['price_loss']} | {row['spread_cost']} | "
                f"{row['slippage_reserve']} | **{row['all_in_risk']}** | {row['net_reward_risk']} |"
            )
        lines += ["", "### حسب ملف التداول", ""]
        lines += ["| الملف | حد المخاطرة | أدنى R:R | 25 نقطة | 50 نقطة | 75 نقطة | صالح؟ |",
                  "|---|---|---|---|---|---|---|"]
        for key, p in data["profiles"].items():
            marks = []
            for stop in p["stops"]:
                marks.append("✅" if stop["tradable"] else "❌")
            lines.append(
                f"| {p['name_ar']} | {p['max_risk_per_trade']} | {p['min_net_reward_risk']} | "
                + " | ".join(marks)
                + f" | {'نعم' if p['any_stop_fits'] else 'لا'} |"
            )
        lines.append("")

    lines += [
        "## ما لا يعنيه هذا التقرير",
        "",
        "- **لا يعني أن التداول مربح.** يعني فقط أن الخسارة المحسوبة تقع ضمن الحد.",
        "- **لا يأذن بالتنفيذ.** لا استراتيجية معتمدة، وقفل Live العام مغلق.",
        "- التبييت محسوب للعلم فقط: **ممنوع في كل الملفات**.",
        "- الوقف العادي **لا يضمن** الخسارة المقدَّرة عند فجوة سعرية.",
    ]
    return redact("\n".join(lines))


__all__ = [
    "write_discovery_json",
    "write_discovery_markdown",
    "render_discovery_markdown",
    "compute_feasibility",
    "render_feasibility_markdown",
    "SanitisationError",
    "FORBIDDEN_JSON_KEYS",
    "STOP_DISTANCES_PIPS",
    "PLANNED_CAPITAL_USD",
]
