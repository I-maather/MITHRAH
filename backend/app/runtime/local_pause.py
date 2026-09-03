"""
الإيقاف المحلي — قرارٌ يجب أن يعيش أطول من العملية التي حملته.

## ما وقع

`SystemState.locally_paused` كانت `True` عند كل بناء، وقاطع الطوارئ
يُحفَظ على القرص. فكل نشرٍ يُعيد الإيقاف المحلي **بصمت**: الخادم يقلع،
والخدمة تعمل، والحلقة تدور، وكل دورةٍ تخرج «التداول موقوف محلياً بقرارك»
— وهو ليس قراراً اتُّخذ للتوّ، بل أثرُ إعادة تشغيل.

وهو العيب الحاكم في صورةٍ أخرى: **حالةٌ تُعرَض على أنها قرار المالكة وهي
قيمةُ إقلاع**. والفرق بينهما أن الأولى تُراجَع والثانية لا يعرف أحدٌ أنها
هناك.

## القاعدة

* الحالة تُكتب على القرص عند كل تغيير، وتُقرأ عند الإقلاع.
* **الغياب يعني إيقافاً**: أوّل إقلاعٍ بلا ملف يبدأ موقوفاً. الافتراض
  الآمن أن المجهول «لا» لا «نعم».
* ملفٌ تالف يُعامَل معاملة الغياب — ولا يُخمَّن منه شيء.
* تُكتب معه لحظتُه وسببه ومصدره، كي يُقرأ **من** أوقف و**لماذا**.

## وما لا يفعله

لا يرفع قاطع طوارئ، ولا يفتح قفل تنفيذ، ولا يغيّر وضع مخاطرة. ملفٌ
واحد بمعنى واحد.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

#: **مجلّد الحالة القابل للكتابة**، وهو `<repo>/data` لا `backend/data`.
#:
#: وحدة الخدمة على الخادم تُقيّد الكتابة: `ProtectSystem=strict` مع
#: `ReadWritePaths=/opt/mathrah/data`. فملفٌ تحت `backend/data` **يُرفض
#: عند الكتابة** وقتَ التشغيل — والقياسات المقروءة تسكن هناك لأنها تُكتب
#: بيد المشغّل لا بيد الخدمة.
#:
#: وهذا الملف تكتبه الخدمة نفسها عند كل إيقاف واستئناف، فمكانه مع
#: `mobile-state.json` في المجلّد المسموح.
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "local-pause.json"

#: متغيّرُ بيئةٍ يعزل المسار.
#:
#: بلا هذا يكتب أيّ فحصٍ يستدعي `/api/trading/resume` في ملفِ التشغيل
#: نفسه، فيقرأه الفحص التالي ويبدأ «غير موقوف» — وهو تسرّبُ حالةٍ بين
#: الفحوص عبر القرص، وأخبثُ من تسرّب الذاكرة لأنه يعبر العمليات.
PATH_ENV_VAR = "MATHRAH_LOCAL_PAUSE_FILE"


def _resolved(path: Optional[Path]) -> Path:
    if path is not None:
        return Path(path)
    override = os.environ.get(PATH_ENV_VAR)
    return Path(override) if override else DEFAULT_PATH


@dataclass(frozen=True)
class LocalPauseState:
    paused: bool
    reason_ar: str = ""
    source: str = ""
    at_utc: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "paused": self.paused,
            "reason_ar": self.reason_ar,
            "source": self.source,
            "at_utc": self.at_utc,
        }


#: الغياب = إيقاف. مكتوبٌ مرّةً واحدة كي لا يُعاد افتراضه في كل موضع.
ABSENT = LocalPauseState(
    paused=True,
    reason_ar="لا حالة محفوظة — الإقلاع يبدأ موقوفاً حتى يُرفع الإيقاف صراحةً.",
    source="default",
)


def load(path: Optional[Path] = None) -> LocalPauseState:
    target = _resolved(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return ABSENT
    if not isinstance(raw, dict) or "paused" not in raw:
        return ABSENT
    return LocalPauseState(
        paused=bool(raw.get("paused", True)),
        reason_ar=str(raw.get("reason_ar") or ""),
        source=str(raw.get("source") or ""),
        at_utc=raw.get("at_utc"),
    )


def save(
    paused: bool,
    *,
    reason_ar: str = "",
    source: str = "",
    path: Optional[Path] = None,
) -> LocalPauseState:
    """كتابةٌ ذرّية: ملفٌ مؤقّت ثم `os.replace`. فلا حالةٌ نصفية على القرص."""
    target = _resolved(path)
    state = LocalPauseState(
        paused=bool(paused),
        reason_ar=reason_ar,
        source=source,
        at_utc=datetime.now(timezone.utc).isoformat(),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".local-pause-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state.as_dict(), fh, ensure_ascii=False, indent=1)
        os.replace(tmp, target)
    except Exception:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return state


def set_local_pause(
    sys_state,
    paused: bool,
    *,
    reason_ar: str = "",
    source: str = "",
    path: Optional[Path] = None,
) -> LocalPauseState:
    """
    **الموضع الوحيد الذي يغيّر الإيقاف المحلي.**

    كل إسنادٍ مباشر لـ`locally_paused` خارج هذه الدالة يترك القرص متخلّفاً
    عن الذاكرة — وهو المدخل نفسه الذي أنتج «قيمةٌ تُعرَض ولا تُقرأ من
    مصدرها». يحرس ذلك فحصٌ ساكن.
    """
    state = save(paused, reason_ar=reason_ar, source=source, path=path)
    sys_state.locally_paused = state.paused
    return state


__all__ = [
    "LocalPauseState", "ABSENT", "DEFAULT_PATH", "PATH_ENV_VAR",
    "load", "save", "set_local_pause",
]
