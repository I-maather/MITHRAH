"""
Shadow Mode — تشغيل كامل على أسعار Demo الحيّة **بلا إرسال أي أمر**.

الفرق عن الاختبار التاريخي: هنا البيانات حيّة والتوقيت حقيقي، فتُقاس أشياء
لا يقيسها Backtest: تأخّر البيانات، اتساع السبريد الفعلي، ساعات السوق،
وسلوك الاستراتيجية عند الأحداث.

الفرق عن التشغيل الحقيقي: لا يوجد `place_order` في هذا الملف إطلاقاً.
الوحدة لا تستورد `ExecutionService` ولا تملك مرجعاً لأي دالة مُرسِلة.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from ..clock import format_riyadh, now_utc
from ..contracts import Bar, Decision, Quote, RiskDecision, Signal, StopKind
from ..marketdata.service import assess_quote
from ..money import D
from ..risk.capital_costs import CapitalComCostModel, CfdTradeEconomics
from .base import Strategy


@dataclass(frozen=True)
class ShadowObservation:
    """لقطة قرار واحدة في وضع الظل."""

    observed_at_utc: datetime
    symbol: str
    decision: Decision
    reason_code: Optional[str]
    reason_ar: str
    data_verdict: str
    spread: Optional[Decimal]
    quote_age_seconds: Optional[float]
    signal: Optional[Signal]
    economics: Optional[CfdTradeEconomics]
    would_have_submitted: bool

    @property
    def observed_at_riyadh(self) -> str:
        return format_riyadh(self.observed_at_utc)

    def as_dict(self) -> dict:
        return {
            "observed_at_utc": self.observed_at_utc.isoformat(),
            "observed_at_riyadh": self.observed_at_riyadh,
            "symbol": self.symbol,
            "decision": self.decision.value,
            "reason_code": self.reason_code,
            "reason_ar": self.reason_ar,
            "data_verdict": self.data_verdict,
            "spread": str(self.spread) if self.spread is not None else None,
            "quote_age_seconds": self.quote_age_seconds,
            "would_have_submitted": self.would_have_submitted,
            "economics": self.economics.as_display_dict() if self.economics else None,
            "submitted": False,
        }


@dataclass
class ShadowSession:
    """
    جلسة ظل. تجمع الملاحظات وتنتج ملخصاً قابلاً للمراجعة.

    `submitted_orders` موجودة عمداً وتبقى صفراً دائماً — وهي ما يتحقق منه
    الاختبار ليثبت أن وضع الظل لم يرسل شيئاً.
    """

    strategy_name: str
    strategy_version: str
    started_at_utc: datetime = field(default_factory=now_utc)
    observations: list[ShadowObservation] = field(default_factory=list)
    submitted_orders: int = 0

    @property
    def session_id(self) -> str:
        return hashlib.sha256(
            f"{self.strategy_name}@{self.strategy_version}|{self.started_at_utc.isoformat()}".encode()
        ).hexdigest()[:16]

    @property
    def would_have_traded(self) -> int:
        return sum(1 for o in self.observations if o.would_have_submitted)

    @property
    def no_trade_reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for observation in self.observations:
            if observation.would_have_submitted:
                continue
            key = observation.reason_code or "NO_SETUP"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "strategy": f"{self.strategy_name}@{self.strategy_version}",
            "started_at_riyadh": format_riyadh(self.started_at_utc),
            "observations": len(self.observations),
            "would_have_traded": self.would_have_traded,
            "orders_actually_submitted": self.submitted_orders,
            "no_trade_reasons": self.no_trade_reasons,
        }

    def to_json(self) -> str:
        return json.dumps(
            {
                "summary": self.summary(),
                "observations": [o.as_dict() for o in self.observations],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


class ShadowRunner:
    """
    يشغّل الاستراتيجية ومحرّك المخاطر على بيانات حيّة، ويسجّل ما **كان سيحدث**.

    لا يستورد ولا يستدعي أي مسار إرسال. هذا قيد بنيوي لا وعد نصي.
    """

    def __init__(
        self,
        *,
        strategy: Strategy,
        cost_model: CapitalComCostModel,
        risk_engine,
        stop_distance_pips: Decimal,
        take_profit_distance_pips: Decimal,
        stop_kind: StopKind = StopKind.NORMAL,
    ) -> None:
        self.strategy = strategy
        self.cost_model = cost_model
        self.risk_engine = risk_engine
        self.stop_distance_pips = stop_distance_pips
        self.take_profit_distance_pips = take_profit_distance_pips
        self.stop_kind = stop_kind
        self.session = ShadowSession(
            strategy_name=strategy.metadata.name, strategy_version=strategy.metadata.version
        )

    def observe(
        self,
        *,
        symbol: str,
        bars: Sequence[Bar],
        quote: Quote,
        state,
        balances,
        kill_switch_active: bool,
        now: Optional[datetime] = None,
    ) -> ShadowObservation:
        now = now or now_utc()
        quality = assess_quote(quote, now=now)

        if not quality.tradable:
            observation = ShadowObservation(
                observed_at_utc=now,
                symbol=symbol,
                decision=Decision.NO_TRADE,
                reason_code=quality.verdict.value,
                reason_ar=quality.reason_ar,
                data_verdict=quality.verdict.value,
                spread=quote.spread if quote else None,
                quote_age_seconds=quality.age_seconds,
                signal=None,
                economics=None,
                would_have_submitted=False,
            )
            self.session.observations.append(observation)
            return observation

        signal = self.strategy.evaluate(symbol=symbol, bars=list(bars), quote=quote, now=now)
        if signal is None:
            observation = ShadowObservation(
                observed_at_utc=now,
                symbol=symbol,
                decision=Decision.NO_TRADE,
                reason_code="NO_SETUP",
                reason_ar="لا توجد فرصة مطابقة لشروط الاستراتيجية.",
                data_verdict=quality.verdict.value,
                spread=quote.spread,
                quote_age_seconds=quality.age_seconds,
                signal=None,
                economics=None,
                would_have_submitted=False,
            )
            self.session.observations.append(observation)
            return observation

        economics = self.cost_model.estimate(
            size=self.cost_model.economics.min_deal_size,
            entry_price=quote.ask,
            stop_distance_pips=self.stop_distance_pips,
            take_profit_distance_pips=self.take_profit_distance_pips,
            stop_kind=self.stop_kind,
        )

        decision: RiskDecision = self.risk_engine.evaluate_cfd(
            signal=signal,
            state=state,
            balances=balances,
            economics=economics,
            kill_switch_active=kill_switch_active,
            now=now,
        )

        observation = ShadowObservation(
            observed_at_utc=now,
            symbol=symbol,
            decision=decision.decision,
            reason_code=decision.reason_code,
            reason_ar=decision.reason_ar,
            data_verdict=quality.verdict.value,
            spread=quote.spread,
            quote_age_seconds=quality.age_seconds,
            signal=signal,
            economics=economics,
            would_have_submitted=decision.approved,
        )
        self.session.observations.append(observation)
        return observation
