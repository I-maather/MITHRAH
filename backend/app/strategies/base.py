"""
Strategy framework — إطار الاستراتيجيات.

كل استراتيجية: deterministic، بلا LLM، بلا عشوائية، وقابلة لإعادة التشغيل
على نفس المدخلات لتعطي نفس المخرجات بالضبط (يوجد اختبار لذلك).
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from ..audit.log import canonical_json
from ..contracts import Bar, Quote, Signal, StrategyState


@dataclass(frozen=True)
class StrategyMetadata:
    name: str
    version: str
    hypothesis_ar: str
    markets: tuple[str, ...]
    timeframe: str
    entry_conditions_ar: tuple[str, ...]
    exit_conditions_ar: tuple[str, ...]
    invalidations_ar: tuple[str, ...]
    min_bars_required: int
    assumed_costs_ar: str
    no_trade_conditions_ar: tuple[str, ...]
    state: StrategyState
    changelog_ar: tuple[str, ...]
    backtest_evidence_ar: str
    walkforward_evidence_ar: str

    #: **الأطر التي يجوز تشغيلها عليها فعلاً**، ولكلٍّ دليلُه.
    #:
    #: ## لماذا صار للإطار حقلٌ ثانٍ
    #:
    #: `timeframe` كان يُعلَن ولا يُقرأ. جرّبتُ البحث في الخادم كلّه: يظهر
    #: عند تعريفه وفي نصوصٍ حرفية، ولا مقارنة تحكم. فشُغِّلت استراتيجياتٌ
    #: تُعلن «1D» على شمعة أربع ساعات — وسجلّ اليوم الواحد يحمل ٧١٥٤ حدث
    #: `TIMEFRAME_MISMATCH` مكتوباً ولا يمنع شيئاً.
    #:
    #: وقيمةٌ تُعلَن ولا تُقرأ هي العيب الحاكم في هذا المشروع. والأثر هنا
    #: أن النتائج تُنسَب إلى فرضيةٍ لم تُختبَر: الفرضية المعلَنة على اليوم،
    #: والمقيس على أربع ساعات — وهما فرضيتان لا واحدة.
    #:
    #: ## القاعدة
    #:
    #: فارغة ⇒ الإطار المُعلَن وحده. وإضافةُ إطارٍ تحتاج **دليلاً مُسمّى**
    #: في `timeframe_evidence_ar` (معرّف تشغيلٍ من مسح التاريخ)، لا رأياً.
    approved_timeframes: tuple[str, ...] = ()
    timeframe_evidence_ar: str = ""

    def runs_on(self, timeframe: Optional[str]) -> bool:
        """
        هل يجوز تشغيل هذه الاستراتيجية على هذا الإطار؟

        `None` تعني «الإطار غير معروف» — وتمرّ: منعُ التشغيل لأن الإعداد لم
        يُصرّح بإطارٍ يوقف نظاماً سليماً بسبب غياب معلومةٍ لا بسبب تعارض.
        والتعارض وحده يمنع.
        """
        if not timeframe:
            return True
        allowed = set(self.approved_timeframes) or {self.timeframe}
        return timeframe in allowed

    @property
    def allowed_timeframes(self) -> tuple[str, ...]:
        return tuple(self.approved_timeframes) or (self.timeframe,)


class Strategy(ABC):
    metadata: StrategyMetadata

    @abstractmethod
    def evaluate(self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime) -> Optional[Signal]:
        """يعيد Signal أو None. لا يرمي استثناءً على 'لا توجد فرصة'."""

    def assess(self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime):
        """
        القرار **ومعه سببه**. الافتراضي هنا صادقٌ لا مفيد: يقول إن هذه
        الاستراتيجية لا تُفصّل شروطها بعد — ولا يختلق سبباً.

        واستراتيجيةٌ تُفصّل تُعيد تعريفها؛ و`evaluate` تبقى هي القرار في
        الحالتين، فلا يتغيّر سلوكٌ قائم بإضافة التشخيص.
        """
        from .assessment import Assessment, Check

        signal = self.evaluate(symbol=symbol, bars=bars, quote=quote, now=now)
        return Assessment(
            signal,
            (
                Check(
                    "التقييم",
                    signal is not None,
                    "هذه الاستراتيجية لا تُفصّل شروطها بعد — لا سبب مفصّل.",
                ),
            ),
        )

    def inputs_digest(self, symbol: str, bars: Sequence[Bar]) -> str:
        payload = {
            "strategy": self.metadata.name,
            "version": self.metadata.version,
            "symbol": symbol,
            "bars": [
                {"t": b.start_utc, "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
                for b in bars
            ],
        }
        return hashlib.sha256(canonical_json(payload).encode()).hexdigest()[:32]


class StrategyRegistry:
    """
    سجل الاستراتيجيات. أي استراتيجية غير APPROVED لا تُشغَّل أبداً،
    ولا يوجد مسار برمجي يرفع حالة استراتيجية في وقت التشغيل.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        key = f"{strategy.metadata.name}@{strategy.metadata.version}"
        if key in self._strategies:
            raise ValueError(f"استراتيجية مسجلة مسبقاً: {key}")
        self._strategies[key] = strategy

    def all(self) -> list[Strategy]:
        return list(self._strategies.values())

    def active(self) -> list[Strategy]:
        return [s for s in self._strategies.values() if s.metadata.state is StrategyState.APPROVED]

    def get(self, name: str, version: str) -> Strategy:
        return self._strategies[f"{name}@{version}"]
