"""
DETERMINISTIC EXPLANATION — الشرح القالبي بلا نموذج لغوي.

هذا هو الشرح **الافتراضي**، لا الاحتياطي المتواضع. النموذج اللغوي يحسّن صياغته
حين يتوفر ويجتاز الحراسة، ولا يضيف رقماً واحداً.

كل رقم في النص أدناه مأخوذ حرفياً من السجل الحتمي — ولهذا يجتاز فحص
`LlmOutputGuard` دائماً بالتعريف.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def _bullets(lines: Sequence[str]) -> str:
    return "\n".join(f"  · {l}" for l in lines if l)


def why_no_trade(
    *,
    decision_code: str,
    primary_reason_ar: str,
    failed_gates: Sequence[str] = (),
    mandatory_failures: Sequence[str] = (),
    contradictions: Sequence[str] = (),
    missing_data: Sequence[str] = (),
    missing_providers: Sequence[str] = (),
    score: int | None = None,
    threshold: int | None = None,
) -> str:
    """
    شرح `NO_TRADE` بحيث **يبدو مفهوماً لا معطّلاً**.
    الامتناع قرار، والقرار يُشرح.
    """
    parts: list[str] = [f"القرار: لا صفقة ({decision_code}).", "", f"السبب: {primary_reason_ar}"]

    if mandatory_failures:
        parts += [
            "",
            "أسباب إلزامية — لا تُعوَّض بأي درجة جودة:",
            _bullets(mandatory_failures),
        ]
    if failed_gates:
        parts += ["", "بوابات لم تُجتَز:", _bullets(failed_gates)]
    if contradictions:
        parts += ["", "تناقضات مسجَّلة:", _bullets(contradictions)]
    if missing_data:
        parts += ["", "بيانات ناقصة (لم تُقدَّر ولم تُستبدل):", _bullets(missing_data)]
    if missing_providers:
        parts += ["", "مزوّدون غير مُعدّين:", _bullets(missing_providers)]
    if score is not None and threshold is not None:
        parts += ["", f"درجة الجودة: {score} من 100 · عتبة الملف: {threshold}."]

    parts += [
        "",
        "هذا سلوك سليم وليس عطلاً: الامتناع عند نقص الدليل أو تناقضه هو القرار "
        "الصحيح، ولا يوجد ملف تداول يجبر النظام على الدخول.",
    ]
    return "\n".join(parts)


def why_trade(
    *,
    strategy_key: str,
    regime_ar: str,
    direction_ar: str,
    entry: str,
    stop: str,
    take_profit: str,
    notional: str,
    margin: str,
    all_in_risk: str,
    reward_risk: str,
    score: int,
    threshold: int,
    profile_name_ar: str,
    profile_max_risk: str,
    supporting: Sequence[str] = (),
    residual_risks: Sequence[str] = (),
) -> str:
    """
    شرح `TRADE`. القيم الثلاث (تعرّض / هامش / خسارة) تُعرض **منفصلة دائماً**.
    """
    parts = [
        f"القرار: صفقة مقترحة ({direction_ar}).",
        "",
        f"الاستراتيجية: {strategy_key} · نظام السوق: {regime_ar}",
        f"الملف الفعّال: {profile_name_ar} · حد المخاطرة: {profile_max_risk} دولار",
        "",
        "الأسعار:",
        _bullets([f"الدخول: {entry}", f"الوقف: {stop}", f"الهدف: {take_profit}"]),
        "",
        "ثلاث قيم منفصلة — لا تُخلط:",
        _bullets([
            f"قيمة التعرّض: {notional} دولار",
            f"الهامش المحجوز (ليس خسارة): {margin} دولار",
            f"الخسارة النقدية عند الوقف: {all_in_risk} دولار",
        ]),
        "",
        f"العائد/المخاطرة بعد كل التكاليف: {reward_risk}",
        f"درجة الجودة: {score} من 100 · عتبة الملف: {threshold}",
    ]
    if supporting:
        parts += ["", "ما يدعم الإعداد:", _bullets(supporting)]
    parts += [
        "",
        "مخاطر متبقية:",
        _bullets(list(residual_risks) + [
            "الوقف العادي لا يضمن الخسارة المقدَّرة عند فجوة سعرية.",
            "درجة عالية لا تعني ربحاً — تعني أن الشروط المعلنة تحققت.",
        ]),
    ]
    return "\n".join(parts)


def morning_brief(
    *,
    date_riyadh: str,
    profile_name_ar: str,
    market_status_ar: str,
    regime_ar: str,
    upcoming_events: Sequence[str] = (),
    data_quality_ar: str = "",
    decision_summary_ar: str = "",
    missing_providers: Sequence[str] = (),
) -> str:
    parts = [
        f"موجز الصباح — {date_riyadh}",
        "",
        f"الملف الفعّال: {profile_name_ar}",
        f"حالة السوق: {market_status_ar}",
        f"نظام السوق: {regime_ar}",
    ]
    if data_quality_ar:
        parts += [f"جودة البيانات: {data_quality_ar}"]
    if upcoming_events:
        parts += ["", "أحداث قادمة:", _bullets(upcoming_events)]
    if missing_providers:
        parts += ["", "مزوّدون ناقصون:", _bullets(missing_providers)]
    if decision_summary_ar:
        parts += ["", f"الخلاصة: {decision_summary_ar}"]
    return "\n".join(parts)


def build_prompt(facts: Mapping[str, Any], task_ar: str) -> str:
    """
    مطالبة النموذج. تُمرَّر إليه الحقائق المُهيكلة **بعد** اتخاذ القرار،
    ومهمته إعادة صياغتها بالعربية لا استنتاج شيء منها.
    """
    return (
        f"{task_ar}\n\n"
        "قواعد إلزامية:\n"
        "1. لا تذكر أي رقم غير موجود حرفياً في الحقائق أدناه.\n"
        "2. لا تقترح صفقة ولا تعارض القرار المذكور.\n"
        "3. لا تخمّن سبباً غير مذكور.\n"
        "4. اكتب بالعربية الفصحى، بإيجاز.\n\n"
        f"الحقائق:\n{facts}\n"
    )


__all__ = ["why_no_trade", "why_trade", "morning_brief", "build_prompt"]
