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


class Strategy(ABC):
    metadata: StrategyMetadata

    @abstractmethod
    def evaluate(self, *, symbol: str, bars: Sequence[Bar], quote: Quote, now: datetime) -> Optional[Signal]:
        """يعيد Signal أو None. لا يرمي استثناءً على 'لا توجد فرصة'."""

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
