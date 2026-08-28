"""
مجدول محلي آمن.

قيد بنيوي: المجدول **لا يستطيع** تفعيل التداول الحقيقي.
كل مهمة مسجّلة تُصنَّف، والمهام المصنّفة `MUTATING` مرفوضة عند التسجيل نفسه.
لا يوجد مسار يجعل مهمة مجدولة ترسل أمراً أو تبدّل وضع المخاطرة.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional

from ..clock import format_riyadh, now_utc

logger = logging.getLogger(__name__)


class JobKind(str, Enum):
    READ_ONLY = "READ_ONLY"        # فحص صحة، تحديث أسعار، مطابقة قراءة
    ANALYSIS = "ANALYSIS"          # تحليل، تقارير، وضع الظل
    MUTATING = "MUTATING"          # إرسال أوامر أو تغيير حالة عند الوسيط


class UnsafeScheduledJob(RuntimeError):
    pass


@dataclass
class ScheduledJob:
    name: str
    kind: JobKind
    interval: timedelta
    func: Callable[[], None]
    next_run_utc: datetime
    last_run_utc: Optional[datetime] = None
    last_error: Optional[str] = None
    runs: int = 0
    failures: int = 0
    enabled: bool = True


@dataclass
class SafeScheduler:
    """
    مجدول بلا خيوط: `tick()` تُستدعى من الحلقة الرئيسية أو من اختبار،
    فيصبح السلوك حتمياً وقابلاً للاختبار بلا انتظار حقيقي.
    """

    clock: Callable[[], datetime] = field(default_factory=lambda: now_utc)
    jobs: dict[str, ScheduledJob] = field(default_factory=dict)
    trading_enabled: bool = False   # لا يغيّرها المجدول أبداً

    def register(
        self,
        name: str,
        *,
        kind: JobKind,
        interval: timedelta,
        func: Callable[[], None],
        start_immediately: bool = True,
    ) -> ScheduledJob:
        if kind is JobKind.MUTATING:
            raise UnsafeScheduledJob(
                f"رُفض تسجيل المهمة «{name}»: المجدول لا يشغّل مهام تُعدّل حالة عند الوسيط. "
                "التنفيذ يحتاج قراراً بشرياً لا جدولاً."
            )
        if name in self.jobs:
            raise ValueError(f"مهمة مسجّلة مسبقاً: {name}")
        now = self.clock()
        job = ScheduledJob(
            name=name,
            kind=kind,
            interval=interval,
            func=func,
            next_run_utc=now if start_immediately else now + interval,
        )
        self.jobs[name] = job
        return job

    def tick(self, at: Optional[datetime] = None) -> list[str]:
        """يشغّل المهام المستحقّة. خطأ مهمة لا يُسقط بقية المهام."""
        now = at or self.clock()
        ran: list[str] = []
        for job in list(self.jobs.values()):
            if not job.enabled or now < job.next_run_utc:
                continue
            try:
                job.func()
                job.last_error = None
            except Exception as exc:  # noqa: BLE001
                job.failures += 1
                job.last_error = f"{type(exc).__name__}"
                logger.warning("فشل المهمة المجدولة %s: %s", job.name, type(exc).__name__)
            job.runs += 1
            job.last_run_utc = now
            job.next_run_utc = now + job.interval
            ran.append(job.name)
        return ran

    def disable(self, name: str) -> None:
        self.jobs[name].enabled = False

    def enable(self, name: str) -> None:
        self.jobs[name].enabled = True

    def status(self) -> list[dict]:
        return [
            {
                "name": j.name,
                "kind": j.kind.value,
                "enabled": j.enabled,
                "interval_seconds": int(j.interval.total_seconds()),
                "runs": j.runs,
                "failures": j.failures,
                "last_run_riyadh": format_riyadh(j.last_run_utc) if j.last_run_utc else None,
                "next_run_riyadh": format_riyadh(j.next_run_utc),
                "last_error": j.last_error,
            }
            for j in self.jobs.values()
        ]
