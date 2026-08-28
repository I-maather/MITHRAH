"""
SANITIZED OUTPUTS — تقريرا الاكتشاف والجدوى، مُنقّيان بالبناء.

ما **لا يظهر أبداً** في أي مخرَج من هذا الملف:
مفتاح API · المعرّف/البريد · كلمة مرور المفتاح · الحمولة المشفّرة ·
`CST` · `X-SECURITY-TOKEN` · معرّف الحساب الكامل · ترويسات خام ·
استجابة مصادقة خام · قيمة 2FA.

## أين يُكتب ماذا

    data/private/capital_live/   ← كل ما يخص الحساب الفعلي (رصيد، متاح،
                                   ربح/خسارة، معرّف مُقنَّع). متجاهَل وغير
                                   متتبَّع، وصلاحياته 700/600، ويُثبَت ذلك
                                   قبل أي كتابة.

    docs/                        ← **لا شيء يخص الحساب**. تقرير جدوى عام
                                   بسيناريو 150 دولاراً المخطَّط وشروط
                                   الأداة من الوسيط فقط.
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
from .overnight import (
    OVERNIGHT_RATE_UNIT_UNKNOWN,
    OvernightRateUnit,
    compute_overnight,
    implied_annual_percent,
)
from ..profiles.thresholds import (
    EquityThreshold,
    LossSequence,
    loss_sequence_limits,
    minimum_equity_for,
)
from .private_store import (
    ACTUAL_FEASIBILITY_MARKDOWN,
    DISCOVERY_JSON,
    DISCOVERY_MARKDOWN,
    write_private_text,
)

#: مفاتيح لا يجوز أن تظهر في JSON بأي حال — فحص أخير قبل الكتابة.
FORBIDDEN_JSON_KEYS: tuple[str, ...] = (
    "apiKey", "api_key", "identifier", "password", "encryptedPassword",
    "cst", "CST", "securityToken", "x-security-token", "accountId",
    "headers", "authorization", "twoFactor", "otp",
)


class SanitisationError(RuntimeError):
    """رُفعت لأن مخرَجاً كان سيحمل ما لا يجوز — لا يُكتب الملف."""


# ---------------------------------------------------------------------------
# حالة تمويل الحساب — حسابٌ غير مموَّل حالةٌ صحيحة، لا خطأ
# ---------------------------------------------------------------------------

#: التصنيف حين يتعذّر تحجيم المراكز على الرصيد الفعلي.
ACCOUNT_NOT_FUNDED = "ACCOUNT_NOT_FUNDED"
ACCOUNT_FUNDED = "FUNDED"


@dataclass(frozen=True)
class EquityAssessment:
    """
    تقييم رصيد الحساب الفعلي **قبل** أي محاولة تحجيم.

    `ProfileLimits.for_profile` ترفض حقوق ملكية غير موجبة — وهذا صحيح: لا يوجد
    حجم مركز صالح على رصيد صفر. الخطأ كان في المستدعي الذي مرّر القيمة كما هي
    فانهار الاكتشاف كله. الحساب غير المموَّل **حالة صحيحة** تُصنَّف ولا تُسقط
    عملية القراءة.
    """
    status: str            # ACCOUNT_FUNDED | ACCOUNT_NOT_FUNDED
    reason_code: str       # FUNDED | ZERO | NEGATIVE | MISSING | MALFORMED
    reason_ar: str
    equity: Optional[Decimal]   # صالحة للتحجيم فقط حين status == FUNDED

    @property
    def usable(self) -> bool:
        return self.status == ACCOUNT_FUNDED and self.equity is not None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "reason_ar": self.reason_ar,
            "position_sizing_available": self.usable,
        }


def assess_equity(raw: object) -> EquityAssessment:
    """
    يصنّف الرصيد الفعلي بلا اختلاق أي قيمة.

    **لا يوجد بديل افتراضي.** استبدال رصيد مفقود بـ150 دولاراً — كما كان
    التنفيذ السابق يفعل — يُنتج تقريراً معنوناً «بالرصيد الفعلي» وهو ليس كذلك.
    الغياب يُصنَّف غياباً.
    """
    if raw is None:
        return EquityAssessment(
            ACCOUNT_NOT_FUNDED, "MISSING",
            "لم يُعِد الوسيط قيمة رصيد لهذا الحساب.", None,
        )
    if isinstance(raw, bool):
        return EquityAssessment(
            ACCOUNT_NOT_FUNDED, "MALFORMED", "قيمة الرصيد ليست عدداً.", None,
        )
    try:
        value = raw if isinstance(raw, Decimal) else D(str(raw))
    except Exception:
        return EquityAssessment(
            ACCOUNT_NOT_FUNDED, "MALFORMED", "تعذّر تفسير قيمة الرصيد عدداً.", None,
        )
    # `Decimal("NaN")` لا يرفع استثناءً، و`NaN <= 0` تساوي False — فيمرّ فحص
    # «موجب» بلا أن يكون موجباً. يُرفض غير المنتهي صراحةً.
    if not value.is_finite():
        return EquityAssessment(
            ACCOUNT_NOT_FUNDED, "MALFORMED", "قيمة الرصيد غير منتهية (NaN/∞).", None,
        )
    if value == 0:
        return EquityAssessment(
            ACCOUNT_NOT_FUNDED, "ZERO", "رصيد الحساب صفر — الحساب غير مموَّل.", None,
        )
    if value < 0:
        return EquityAssessment(
            ACCOUNT_NOT_FUNDED, "NEGATIVE", "رصيد الحساب سالب.", None,
        )
    return EquityAssessment(ACCOUNT_FUNDED, "FUNDED", "الحساب مموَّل.", value)


def parse_unit_enum(value: Optional[str]) -> OvernightRateUnit:
    """يحوّل الوحدة المحفوظة نصاً إلى العدّاد. كل ما لا يُعرف ⇒ `UNKNOWN`."""
    try:
        return OvernightRateUnit(str(value))
    except ValueError:
        return OvernightRateUnit.UNKNOWN


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


def build_discovery_payload(report: LiveDiscoveryReport) -> dict:
    payload = report.as_dict()
    payload["sanitised"] = True
    payload["sensitivity"] = "PRIVATE_LOCAL_ONLY"
    payload["contains"] = (
        "قيم حساب وأدوات. لا مفاتيح ولا رموز ولا معرّف حساب كامل. "
        "يحتوي رصيداً حقيقياً ⇒ يُكتب في data/private/ فقط."
    )
    _assert_sanitised(payload)
    return payload


def write_discovery_json(report: LiveDiscoveryReport, path: Path) -> Path:
    """
    ⚠️ للاختبارات والمسارات المؤقتة فقط. المسار الإنتاجي هو
    `write_private_discovery_json()` الذي يمر عبر المخزن الخاص.
    """
    payload = build_discovery_payload(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def render_discovery_markdown(report: LiveDiscoveryReport) -> str:
    a = report.account
    lines: list[str] = [
        "# Capital.com Live Discovery — اكتشاف الحساب الحقيقي",
        "",
        "> ⚠️ **معلومة محلية حسّاسة.** هذا التقرير يحتوي رصيد حسابك الحقيقي.",
        "> **لا يُرفع إلى مستودع بعيد ولا يُشارَك.**",
        "> مكانه `data/private/capital_live/` — متجاهَل في git وغير متتبَّع.",
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
    """⚠️ للاختبارات فقط — انظري `write_private_discovery_markdown()`."""
    text = render_discovery_markdown(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# المسارات الإنتاجية — عبر المخزن الخاص وحده
# ---------------------------------------------------------------------------

def write_private_discovery_json(report: LiveDiscoveryReport, repo_root: Path) -> Path:
    payload = build_discovery_payload(report)
    return write_private_text(
        repo_root, DISCOVERY_JSON, json.dumps(payload, ensure_ascii=False, indent=2)
    )


def write_private_discovery_markdown(report: LiveDiscoveryReport, repo_root: Path) -> Path:
    return write_private_text(
        repo_root, DISCOVERY_MARKDOWN, render_discovery_markdown(report)
    )


def write_private_actual_feasibility(
    report: LiveDiscoveryReport,
    repo_root: Path,
    *,
    actual: Optional[dict],
    assessment: Optional[EquityAssessment] = None,
) -> Path:
    return write_private_text(
        repo_root,
        ACTUAL_FEASIBILITY_MARKDOWN,
        render_actual_feasibility_markdown(report, actual=actual, assessment=assessment),
    )


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

    حقوق ملكية غير موجبة أو غير منتهية تعيد `None` **قبل** بلوغ
    `ProfileLimits.for_profile`. المستدعي يصنّف الحالة بـ`assess_equity`؛
    وهذا الفحص خطُّ دفاعٍ ثانٍ كي لا يعيد مستدعٍ مستقبليٌّ الانهيار نفسه.
    """
    if not instrument.found or instrument.bid is None or instrument.ask is None:
        return None
    if equity is None or not Decimal(equity).is_finite() or equity <= 0:
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

    # التبييت: **لا يُضرب المعدّل الخام في التعرّض** قبل إثبات وحدته.
    # كان ذلك مصدر خطأ المئة ضعف. انظر `overnight.py`.
    overnight_rate = compute_overnight(
        instrument.overnight_fee_long,
        notional=notional,
        unit=parse_unit_enum(instrument.overnight_rate_unit),
        unit_source_ar=instrument.overnight_rate_unit_source_ar or "",
        raw_text=(
            str(instrument.overnight_fee_long)
            if instrument.overnight_fee_long is not None else None
        ),
    )
    overnight = overnight_rate.cash_fee

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
        # العتبات لكل سيناريو وقف: **ثلاثة أرقام مختلفة لا رقم واحد**.
        thresholds = {
            str(row.stop_pips): minimum_equity_for(profile, row.all_in_risk).as_dict()
            for row in rows
        }
        sequences = {
            str(row.stop_pips): loss_sequence_limits(
                profile, row.all_in_risk, equity=equity
            ).as_dict()
            for row in rows
        }
        profiles[profile.value] = {
            "name_ar": PROFILE_SPECS[profile].name_ar,
            "max_risk_per_trade": f"{limits.max_risk_per_trade:.2f}",
            "min_net_reward_risk": f"{limits.min_net_reward_risk:.2f}",
            "min_quality_score": limits.min_quality_score,
            "stops": fits,
            "any_stop_fits": any(f["tradable"] for f in fits),
            "equity_thresholds": thresholds,
            "loss_sequences": sequences,
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
        "overnight": overnight_rate.as_dict(),
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


def _feasibility_block(data: dict) -> list[str]:
    lines = [
        "| البند | القيمة |",
        "|---|---|",
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
    for _key, profile in data["profiles"].items():
        marks = ["✅" if stop["tradable"] else "❌" for stop in profile["stops"]]
        lines.append(
            f"| {profile['name_ar']} | {profile['max_risk_per_trade']} | "
            f"{profile['min_net_reward_risk']} | " + " | ".join(marks)
            + f" | {'نعم' if profile['any_stop_fits'] else 'لا'} |"
        )
    return lines


_NO_PROFIT_CLAIM = [
    "## ما لا يعنيه هذا التقرير",
    "",
    "- **لا يعني أن التداول مربح.** يعني فقط أن الخسارة المحسوبة تقع ضمن الحد.",
    "- **لا يأذن بالتنفيذ.** لا استراتيجية معتمدة، وقفل Live العام مغلق.",
    "- التبييت محسوب للعلم فقط: **ممنوع في كل الملفات**.",
    "- الوقف العادي **لا يضمن** الخسارة المقدَّرة عند فجوة سعرية.",
]


def render_actual_feasibility_markdown(
    report: LiveDiscoveryReport,
    *,
    actual: Optional[dict],
    assessment: Optional[EquityAssessment] = None,
) -> str:
    """
    تقرير **خاص**: يستعمل رصيد الحساب الفعلي.
    يُكتب في `data/private/capital_live/` وحده — لا تحت `docs/` بحال.
    """
    lines: list[str] = [
        "# جدوى EUR/USD — بالرصيد الفعلي",
        "",
        "> 🔒 **ملف خاص.** يحتوي رصيد حسابك الحقيقي.",
        "> مكانه `data/private/capital_live/` — متجاهَل في git وغير متتبَّع،",
        "> وصلاحياته 600. **لا يُرفع ولا يُشارَك ولا يُنسخ إلى `docs/`.**",
        "",
        "> **هذه ليست توقّع ربح.** الجدوى تعني: هل تقع الخسارة الكاملة عند",
        "> الوقف ضمن حد الملف؟ لا أكثر. **الكفاية التقنية ≠ الربحية.**",
        "",
        f"مصدر القيم: اكتشاف حقيقي بتاريخ {report.generated_at_riyadh} (الرياض).",
        "",
        "## الرصيد الفعلي",
        "",
    ]
    if assessment is not None and not assessment.usable:
        lines += [
            f"## الحالة: `{assessment.status}`",
            "",
            f"**{assessment.reason_ar}**",
            "",
            "**تحجيم المراكز على الرصيد الفعلي غير متاح.** لا يوجد حجم مركز",
            "صالح على رصيد غير موجب، ولم يُختلَق أي رقم بديل: التقرير يقول",
            "«لا أعرف» بدل أن يقول رقماً لا أساس له.",
            "",
            "هذا **ليس عطلاً**. الاكتشاف نجح، وقراءات الوسيط كلها اكتملت،",
            "وشروط الأداة مسجَّلة في تقرير الاكتشاف. الناقص هو التمويل وحده.",
            "",
            "الجدوى بسيناريو **150 دولاراً المخطَّط** محسوبة كاملة في التقرير",
            "العام `docs/CAPITAL_COM_150_USD_FEASIBILITY.md` — وهي المرجع",
            "الصالح إلى أن يُموَّل الحساب.",
            "",
            f"| رمز السبب | `{assessment.reason_code}` |",
            "|---|---|",
            "| تحجيم المراكز | غير متاح |",
            "| قرار الجدوى الفعلية | **NO-GO** |",
            "",
        ]
    elif actual is None:
        lines += ["> تعذّر الحساب: قيم الأداة ناقصة.", ""]
    else:
        lines += [f"حقوق الملكية المستعملة: **{actual['equity_used']}**", ""]
        lines += _feasibility_block(actual)
        lines.append("")
    lines += _NO_PROFIT_CLAIM
    return redact("\n".join(lines))


#: حقول شروط الأداة التي تظهر في التقرير العام.
#:
#: كلها **شروط أداة لدى الوسيط**، لا بيانات حساب: تُنشر كما هي لأي حامل للأداة
#: نفسها، ولا تكشف عن الحساب شيئاً. غيابها من التقرير هو ما عطّل التدقيق سابقاً.
PUBLIC_INSTRUMENT_FIELDS: tuple[tuple[str, str, Optional[str]], ...] = (
    # (مفتاح القيمة، الاسم العربي، مفتاح الوحدة إن وُجد)
    ("market_status", "حالة السوق", None),
    ("snapshot_time", "طابع اللقطة", None),
    ("data_age_seconds", "عمر البيانات (ثانية)", None),
    ("bid", "العرض (Bid)", None),
    ("ask", "الطلب (Ask)", None),
    ("spread", "السبريد (لقطة واحدة)", None),
    ("min_deal_size", "أدنى حجم صفقة", "min_deal_size_unit"),
    ("size_increment", "أصغر زيادة حجم", "size_increment_unit"),
    ("margin_factor", "معامل الهامش", "margin_factor_unit"),
    ("min_step_distance", "أدنى مسافة خطوة", "min_step_distance_unit"),
    ("min_stop_distance", "أدنى مسافة وقف/هدف", "min_stop_distance_unit"),
    ("min_guaranteed_stop_distance", "أدنى مسافة وقف مضمون",
     "min_guaranteed_stop_distance_unit"),
    ("guaranteed_stop_available", "الوقف المضمون متاح؟", None),
    ("guaranteed_stop_premium", "علاوة الوقف المضمون", None),
    ("lot_size", "حجم اللوت", None),
    ("contract_size", "حجم العقد", None),
    ("pip_definition", "تعريف النقطة (onePipMeans)", None),
    ("pip_position", "موضع النقطة (pipPosition)", None),
    ("tick_size", "حجم التِّك", None),
    ("decimal_places_factor", "معامل المنازل العشرية", None),
    ("scaling_factor", "معامل التحجيم", None),
    ("quantity_interpretation", "تفسير الكمية", None),
    ("trading_hours", "ساعات التداول", None),
    ("overnight_fee_long", "معدّل التبييت الخام (شراء)", None),
    ("overnight_fee_short", "معدّل التبييت الخام (بيع)", None),
    ("overnight_rate_unit", "وحدة معدّل التبييت", None),
    ("overnight_fee_time", "وقت احتساب التبييت", None),
)

#: مفاتيح **ممنوعة** في التقرير العام — بيانات حساب لا شروط أداة.
FORBIDDEN_PUBLIC_KEYS: tuple[str, ...] = (
    "balance", "available", "profit_loss", "masked_id", "account_id",
    "accountId", "email", "identifier", "dealing_enabled", "leverage_preferences",
)


def render_instrument_conditions_markdown(
    instrument: Optional[LiveInstrumentInfo],
) -> list[str]:
    """
    جدول **شروط الأداة العامة** بوحداتها.

    القيمة الغائبة تظهر «—» صراحةً. الحقل الغائب من التقرير كان يعني سابقاً
    أنه لا يمكن تدقيقه أصلاً — وهو ما حدث مع أدنى مسافة وقف والوقف المضمون.
    """
    lines = [
        "## شروط الأداة لدى الوسيط",
        "",
        "> كل ما في هذا الجدول **شرط أداة عام**، لا بيانات حساب. القيمة «—»",
        "> تعني أن الوسيط لم يُعِدها — لا أنها صفر ولا أنها غير مهمة.",
        "",
    ]
    if instrument is None or not instrument.found:
        return lines + ["> الأداة لم تُقرأ في هذا الاكتشاف.", ""]

    data = instrument.as_dict()
    lines += ["| الشرط | القيمة | الوحدة |", "|---|---|---|"]
    for key, label, unit_key in PUBLIC_INSTRUMENT_FIELDS:
        value = data.get(key)
        if isinstance(value, bool):
            shown = "نعم" if value else "لا"
        elif value is None:
            shown = "—"
        else:
            shown = str(value)
        unit = data.get(unit_key) if unit_key else None
        lines.append(f"| {label} | {shown} | {unit or '—'} |")

    if instrument.notes:
        lines += ["", "**ملاحظات الاكتشاف:**"]
        lines += [f"- {note}" for note in instrument.notes]
    lines.append("")
    return lines


def render_overnight_section(planned: Optional[dict]) -> list[str]:
    """
    التبييت بقيمه **الأربع منفصلة**: الخام · الوحدة · المطبَّع · النقدي.

    دمجها في رقم واحد هو ما سمح بخطأ المئة ضعف بلا أن يلاحظه أحد.
    """
    lines = ["## تكلفة التبييت — الوحدة تُثبَت ولا تُخمَّن", ""]
    block = (planned or {}).get("overnight")
    if not block:
        return lines + ["> غير محسوبة.", ""]

    lines += [
        "| البند | القيمة |",
        "|---|---|",
        f"| القيمة الخام من الوسيط | {block.get('raw_value') or '—'} |",
        f"| الوحدة المُثبتة | `{block.get('unit')}` |",
        f"| مصدر إثبات الوحدة | {block.get('unit_source_ar') or '—'} |",
        f"| المعدّل المطبَّع (كسر/ليلة) | {block.get('normalized_rate_per_night') or '—'} |",
        f"| **التكلفة النقدية لليلة** | **{block.get('cash_fee_one_night') or '—'}** |",
        "",
    ]
    if block.get("failure_code") == OVERNIGHT_RATE_UNIT_UNKNOWN:
        lines += [
            f"> ⛔ **`{OVERNIGHT_RATE_UNIT_UNKNOWN}`** — الوسيط لم يُعلن وحدة",
            "> المعدّل، ولا يوجد عقد مُثبَت في الكود. **فلا تُحسب تكلفة.**",
            "",
            "> القسمة على 100 «لأن الرقم يبدو كبيراً» تخمينٌ في الاتجاه المعاكس.",
            "> تُثبَت الوحدة من وثائق الوسيط، ثم تُعلَن مرة واحدة في",
            "> `DECLARED_CAPITAL_OVERNIGHT_UNIT`.",
            "",
            "> **لا أثر على قرار التداول:** التبييت ممنوع في كل الملفات الثلاثة.",
            "> الأثر على **Backtest**: تكلفة مضخّمة مئة ضعف تُسقط استراتيجيات صالحة.",
            "",
        ]
    elif block.get("normalized_rate_per_night"):
        annual = implied_annual_percent(D(block["normalized_rate_per_night"]))
        lines += [
            f"المعدّل السنوي الضمني (365 ليلة): **{annual:.2f}%** — "
            "للفحص العقلي لا للتسعير.",
            "",
        ]
    return lines


def render_thresholds_section(planned: Optional[dict]) -> list[str]:
    """
    ثلاثة أرقام **مختلفة** كانت مدموجة في واحد.

    قول «150 دولاراً هي الحد الأدنى» كان خطأً: 150 هي نقطة انقلاب السقف
    الدولاري، والحد الأدنى لخسارة 0.54 في المتوازن هو **108**.
    """
    lines = [
        "## الحد الأدنى لحقوق الملكية — ثلاثة أرقام لا رقم واحد",
        "",
        "| المفهوم | المعنى |",
        "|---|---|",
        "| **الحد الأدنى للسيناريو** | أقل حقوق ملكية تجعل النسبة تسمح بهذه "
        "الخسارة = الخسارة ÷ النسبة |",
        "| **نقطة انقلاب السقف** | حقوق الملكية التي يبدأ عندها السقف الدولاري "
        "في الحكم بدل النسبة = السقف ÷ النسبة |",
        "| **رأس المال المخطَّط** | 150 دولاراً — قرار المالكة، لا نتيجة حساب |",
        "",
        "> تصادُف رقمين منها في مثال واحد لا يجعلهما شيئاً واحداً.",
        "",
    ]
    if not planned:
        return lines + ["> غير محسوبة.", ""]

    lines += [
        "| الملف | الوقف | الخسارة الكلية | الحد الأدنى | انقلاب السقف | ممكن أصلاً؟ |",
        "|---|---|---|---|---|---|",
    ]
    for _key, profile in planned["profiles"].items():
        for stop, threshold in profile["equity_thresholds"].items():
            minimum = threshold["minimum_equity_from_percentage"]
            possible = threshold["possible_at_any_equity"]
            lines.append(
                f"| {profile['name_ar']} | {stop} نقطة | "
                f"{threshold['all_in_risk']} | "
                f"{minimum or '**مستحيل**'} | "
                f"{threshold['cap_binding_equity']} | "
                f"{'نعم' if possible else 'لا — تتجاوز السقف الثابت'} |"
            )
    lines += [
        "",
        "> «مستحيل» تعني أن الخسارة تتجاوز **السقف الدولاري الثابت** للملف،",
        "> وهو لا يرتفع بزيادة رأس المال أبداً. لا مبلغ يُصلح ذلك.",
        "",
    ]
    return lines


def render_loss_sequence_section(planned: Optional[dict]) -> list[str]:
    """
    سلسلة الخسائر تحت **كل** الحدود: التواتر اليومي، واليومي، والأسبوعي،
    والتوقّف التشغيلي. لا حدّ واحد يُقتبَس منفرداً.
    """
    lines = [
        "## سلسلة الخسائر المأذون بها",
        "",
        "> الحدود **لا تُجمع** — الأشد يفوز. والعمود الأخير يقول أيها الأشد.",
        "> وعدد أوامر الدخول اليومي محدود بواحد في كل الملفات، وهو قيدٌ كثيراً",
        "> ما يسبق حدّ الخسارة اليومي.",
        "",
    ]
    if not planned:
        return lines + ["> غير محسوبة.", ""]

    lines += [
        "| الملف | الوقف | الخسارة | باليوم | بالأسبوع | حتى التوقّف "
        "(6.50) | التراكم | أيام | القيد الأشد |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _key, profile in planned["profiles"].items():
        for stop, seq in profile["loss_sequences"].items():
            lines.append(
                f"| {profile['name_ar']} | {stop} نقطة | {seq['loss_per_trade']} | "
                f"{seq['losses_per_day_effective']} | "
                f"{seq['losses_per_week_effective']} | "
                f"{seq['losses_until_operational_stop']} | "
                f"{seq['cumulative_at_operational_limit']} | "
                f"{seq['trading_days_to_operational_stop'] or '—'} | "
                f"`{seq['binding_constraint']}`"
                + ("" if seq["scenario_permitted"] else " · ⛔ غير مسموح أصلاً")
                + " |"
            )
    lines += [
        "",
        "> عمود «التراكم» هو مجموع الخسائر عند العدد المذكور — وهو **لا يتجاوز**",
        "> حدّ التوقّف التشغيلي 6.50. الخسارة التالية هي التي تتجاوزه.",
        "",
    ]
    return lines


def render_public_feasibility_markdown(
    *,
    planned: Optional[dict],
    instrument_epic: str = "EURUSD",
    instrument: Optional[LiveInstrumentInfo] = None,
) -> str:
    """
    تقرير **عام** صالح للبقاء تحت `docs/`.

    يستعمل **سيناريو 150 دولاراً المخطَّط وحده** وشروط الأداة من الوسيط.
    **لا يحتوي**: رصيداً فعلياً ولا أموالاً متاحة ولا ربحاً/خسارة ولا معرّف
    حساب (كاملاً أو مُقنَّعاً) ولا بريداً ولا أي قيمة خاصة بالحساب.
    """
    lines: list[str] = [
        f"# جدوى {instrument_epic} — سيناريو مخطَّط: 150 دولاراً",
        "",
        "> **تقرير عام.** لا يحتوي أي قيمة خاصة بحساب: لا رصيد فعلي، ولا أموالاً",
        "> متاحة، ولا ربحاً/خسارة، ولا معرّف حساب، ولا بريداً.",
        "> الأرقام هنا من **شروط الأداة لدى الوسيط** ومن رأس المال المخطَّط فقط.",
        "",
        "> التقرير المقابل بالرصيد الفعلي **خاص** ومكانه",
        "> `data/private/capital_live/` — خارج git تماماً.",
        "",
        "> **هذه ليست توقّع ربح.** الكفاية التقنية ≠ الربحية.",
        "",
        "## رأس المال المخطَّط: 150.00 دولاراً",
        "",
    ]
    if planned is None:
        lines += ["> تعذّر الحساب: شروط الأداة غير متوفرة بعد.", ""]
    else:
        lines += _feasibility_block(planned)
        lines.append("")

    lines += render_thresholds_section(planned)
    lines += render_loss_sequence_section(planned)
    lines += render_overnight_section(planned)
    lines += render_instrument_conditions_markdown(instrument)

    text = redact("\n".join(lines + _NO_PROFIT_CLAIM))
    _assert_public_text(text)
    return text


def _assert_public_text(text: str) -> None:
    """
    فحص أخير قبل إعادة النص العام: لا مفتاح حساب فيه.

    التقرير العام يُكتب تحت `docs/` وهو مسار **متتبَّع**. الخطأ هنا يدخل السجل
    ولا يخرج منه، فالفحص يسبق الكتابة لا يتبعها.
    """
    for key in FORBIDDEN_PUBLIC_KEYS:
        if key in text:
            raise SanitisationError(f"مفتاح حساب في التقرير العام: {key}")


__all__ = [
    "ACCOUNT_FUNDED",
    "ACCOUNT_NOT_FUNDED",
    "EquityAssessment",
    "assess_equity",
    "build_discovery_payload",
    "write_discovery_json",
    "write_discovery_markdown",
    "write_private_discovery_json",
    "write_private_discovery_markdown",
    "write_private_actual_feasibility",
    "render_discovery_markdown",
    "compute_feasibility",
    "render_actual_feasibility_markdown",
    "render_public_feasibility_markdown",
    "render_instrument_conditions_markdown",
    "render_overnight_section",
    "render_thresholds_section",
    "render_loss_sequence_section",
    "PUBLIC_INSTRUMENT_FIELDS",
    "FORBIDDEN_PUBLIC_KEYS",
    "parse_unit_enum",
    "SanitisationError",
    "FORBIDDEN_JSON_KEYS",
    "STOP_DISTANCES_PIPS",
    "PLANNED_CAPITAL_USD",
]
