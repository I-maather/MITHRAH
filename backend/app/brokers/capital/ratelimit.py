"""
حدود الطلبات المعلنة رسمياً من Capital.com (تُحقق 2026-08-28):

  * 10 طلبات/ثانية كحد عام لكل مستخدم
  * طلب واحد/ثانية لـ POST /session لكل مفتاح
  * طلب واحد/0.1 ثانية لفتح المراكز وإنشاء الأوامر
  * 1000 طلب/ساعة لعمليات المراكز والأوامر في حساب Demo

نستخدم دلو رموز بسيطاً بلا خيوط: يعمل بالساعة المحقونة فيسهل اختباره
بلا انتظار حقيقي في الاختبارات.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .errors import CapitalRateLimited

GENERAL_LIMIT_PER_SECOND = 10.0
SESSION_LIMIT_PER_SECOND = 1.0
ORDER_LIMIT_PER_SECOND = 10.0
DEMO_ORDER_LIMIT_PER_HOUR = 1000


@dataclass
class TokenBucket:
    rate_per_second: float
    capacity: float
    _tokens: float = field(init=False)
    _last: float = field(init=False)
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last = self.clock()

    def _refill(self) -> None:
        now = self.clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate_per_second)

    def try_acquire(self, tokens: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def time_until_available(self, tokens: float = 1.0) -> float:
        self._refill()
        if self._tokens >= tokens:
            return 0.0
        return (tokens - self._tokens) / self.rate_per_second


@dataclass
class RateLimiter:
    """
    يجمع الدلاء الثلاثة. لا ينام تلقائياً في الاختبارات:
    `sleeper` قابل للحقن، والافتراضي `time.sleep`.
    """

    clock: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    max_wait_seconds: float = 2.0

    def __post_init__(self) -> None:
        self.general = TokenBucket(GENERAL_LIMIT_PER_SECOND, GENERAL_LIMIT_PER_SECOND, clock=self.clock)
        self.session = TokenBucket(SESSION_LIMIT_PER_SECOND, 1.0, clock=self.clock)
        self.orders = TokenBucket(ORDER_LIMIT_PER_SECOND, ORDER_LIMIT_PER_SECOND, clock=self.clock)

    def acquire(self, kind: str = "general") -> None:
        bucket = {"general": self.general, "session": self.session, "orders": self.orders}[kind]
        if bucket.try_acquire():
            return
        wait = bucket.time_until_available()
        if wait > self.max_wait_seconds:
            raise CapitalRateLimited(
                f"تجاوز حد الطلبات ({kind}). الانتظار المطلوب {wait:.2f} ثانية يتجاوز الحد المسموح."
            )
        self.sleeper(wait)
        if not bucket.try_acquire():
            raise CapitalRateLimited(f"تعذّر الحصول على إذن الطلب ({kind}) بعد الانتظار.")
