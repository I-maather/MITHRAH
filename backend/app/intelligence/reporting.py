"""
المرحلتان 16 و17 — الشرح المقروء وقيد التدقيق.

الشرح يُبنى **بعد** أن يصبح القرار نهائياً، من السجل الحتمي وحده.
لو تعذّر توليد صياغة أجمل بنموذج لغوي، يُعرض القالب الحتمي — والقرار لا يتأثر.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Optional

from ..contracts import Decision
from ..llm import GuardResult, LlmOutputGuard, NullSummaryProvider, SummaryProvider
from ..llm.explain import build_prompt, why_no_trade, why_trade
from ..profiles import PROFILE_SPECS
from .pipeline import PipelineResult, Stage, STAGE_NAME_AR, StageRecord
from .scoring import MANDATORY_FAILURE_AR


def deterministic_facts(result: PipelineResult, limits) -> dict[str, Any]:
    """
    السجل المُتحقَّق منه الذي يُقارَن به كل رقم في أي ملخص لغوي.
    أي رقم خارج هذا القاموس يُعتبر مختلَقاً.
    """
    facts: dict[str, Any] = {
        "decision": result.decision.value,
        "reason_code": result.reason_code,
        "snapshot_id": result.snapshot_id,
        "profile": result.profile.value,
        "profile_max_risk": f"{limits.max_risk_per_trade:.2f}",
        "profile_min_quality_score": limits.min_quality_score,
        "profile_min_reward_risk": f"{limits.min_net_reward_risk:.2f}",
        "daily_limit": f"{limits.max_daily_loss:.2f}",
        "weekly_limit": f"{limits.max_weekly_loss:.2f}",
        "operational_drawdown_stop": f"{limits.operational_drawdown_stop:.2f}",
        "absolute_loss_boundary": f"{limits.absolute_loss_boundary:.2f}",
        "missing_providers": list(result.missing_providers),
        "missing_data": list(result.missing_data),
    }
    if result.score:
        facts["quality_score"] = result.score.total
        facts["quality_max"] = 100
    if result.regime:
        facts["regime"] = result.regime.regime.value
        facts["regime_ar"] = result.regime.name_ar
    if result.strategy and result.strategy.matched:
        facts["strategy"] = result.strategy.matched.key
        facts["strategy_state"] = result.strategy.matched.state.value
    if result.position:
        p = result.position
        facts.update({
            "size": str(p.size),
            "notional": f"{p.notional:.2f}",
            "margin": f"{p.margin:.2f}",
            "all_in_risk": f"{p.all_in_risk:.2f}",
            "net_reward_risk": f"{p.net_reward_risk:.2f}",
            "stop_pips": f"{p.stop_pips:.1f}",
            "spread": str(p.spread),
            "pip_value": str(p.pip_value),
        })
    if result.setup:
        s = result.setup
        facts.update({
            "side": s.side.value,
            "entry_price": str(s.entry_price),
            "stop_price": str(s.stop_price),
            "take_profit_price": str(s.take_profit_price),
        })
    if result.contradictions:
        facts["contradiction_count"] = len(result.contradictions.items)
        facts["contradiction_penalty"] = result.contradictions.total_penalty
    return facts


def template_explanation(result: PipelineResult, limits) -> str:
    """الشرح القالبي الحتمي — كل رقم فيه من السجل."""
    if result.decision is Decision.TRADE and result.position and result.setup:
        p, s = result.position, result.setup
        return why_trade(
            strategy_key=result.strategy.matched.key if result.strategy and result.strategy.matched else "—",
            regime_ar=result.regime.name_ar if result.regime else "—",
            direction_ar="شراء" if s.side.value == "BUY" else "بيع",
            entry=str(s.entry_price),
            stop=str(s.stop_price),
            take_profit=str(s.take_profit_price),
            notional=f"{p.notional:.2f}",
            margin=f"{p.margin:.2f}",
            all_in_risk=f"{p.all_in_risk:.2f}",
            reward_risk=f"{p.net_reward_risk:.2f}",
            score=result.score.total if result.score else 0,
            threshold=limits.min_quality_score,
            profile_name_ar=PROFILE_SPECS[result.profile].name_ar,
            profile_max_risk=f"{limits.max_risk_per_trade:.2f}",
            supporting=(
                [l.reason_ar for l in result.score.lines if l.awarded > 0][:5]
                if result.score else []
            ),
            residual_risks=(
                [c.side_b_ar for c in result.contradictions.items]
                if result.contradictions else []
            ),
        )

    failed = [
        f"{STAGE_NAME_AR[s.stage]}: {s.detail_ar}" for s in result.stages if not s.passed
    ]
    return why_no_trade(
        decision_code=result.reason_code,
        primary_reason_ar=result.reason_ar,
        failed_gates=failed,
        mandatory_failures=(
            [MANDATORY_FAILURE_AR[f] for f in result.score.mandatory_failures]
            if result.score else []
        ),
        contradictions=(
            [f"{c.side_a_ar} ↔ {c.side_b_ar} ⇒ {c.resolution_ar}"
             for c in result.contradictions.items]
            if result.contradictions else []
        ),
        missing_data=list(result.missing_data),
        missing_providers=list(result.missing_providers),
        score=result.score.total if result.score else None,
        threshold=limits.min_quality_score,
    )


def finalize(
    result: PipelineResult,
    limits,
    *,
    now: datetime,
    provider: Optional[SummaryProvider] = None,
    guard: Optional[LlmOutputGuard] = None,
) -> tuple[PipelineResult, GuardResult]:
    """
    المرحلتان 16 و17. تعيد نتيجة مكتملة الشرح + تقرير الحراسة.

    **القرار في `result` لا يتغيّر هنا بأي حال** — تُضاف حقول عرض فقط.
    """
    facts = deterministic_facts(result, limits)
    fallback = template_explanation(result, limits)

    g = guard or LlmOutputGuard()
    p = provider or NullSummaryProvider()
    guard_result = g.explain(
        p,
        prompt=build_prompt(facts, "اشرحي القرار التالي للمالكة بالعربية."),
        facts=facts,
        deterministic_decision=result.decision.value,
        fallback_text=fallback,
        now=now,
    )

    stages = list(result.stages)
    stages.append(StageRecord(
        stage=Stage.EXPLANATION,
        name_ar=STAGE_NAME_AR[Stage.EXPLANATION],
        passed=True,
        detail_ar=(
            "شرح النموذج اللغوي اجتاز الحراسة."
            if guard_result.used_llm
            else "شرح قالبي حتمي — النموذج اللغوي غير مستعمل أو لم يجتز الحراسة."
        ),
        payload=guard_result.as_dict(),
        mandatory=False,
    ))
    stages.append(StageRecord(
        stage=Stage.AUDIT_CALIBRATION,
        name_ar=STAGE_NAME_AR[Stage.AUDIT_CALIBRATION],
        passed=True,
        detail_ar="القرار وكل مدخلاته مُسجَّلة للمعايرة اللاحقة.",
        payload={"snapshot_id": result.snapshot_id, "decided_at_utc": now.isoformat()},
        mandatory=False,
    ))

    return (
        replace(result, stages=tuple(stages), explanation_ar=guard_result.text),
        guard_result,
    )


def audit_payload(result: PipelineResult) -> dict:
    """قيد التدقيق الكامل — يدخل السلسلة المُسلسلة بالـhash."""
    return {
        "event": "INTELLIGENCE_DECISION",
        "decision": result.decision.value,
        "reason_code": result.reason_code,
        "snapshot_id": result.snapshot_id,
        "profile": result.profile.value,
        "stages": [
            {"stage": s.stage.value, "passed": s.passed, "mandatory": s.mandatory}
            for s in result.stages
        ],
        "score": result.score.total if result.score else None,
        "mandatory_failures": (
            [f.value for f in result.score.mandatory_failures] if result.score else []
        ),
        "contradictions": (
            [c.kind.value for c in result.contradictions.items]
            if result.contradictions else []
        ),
        "verification_passed": result.verification.passed if result.verification else None,
        "missing_providers": list(result.missing_providers),
        "decided_at_utc": result.decided_at_utc.isoformat() if result.decided_at_utc else None,
    }


__all__ = ["deterministic_facts", "template_explanation", "finalize", "audit_payload"]
