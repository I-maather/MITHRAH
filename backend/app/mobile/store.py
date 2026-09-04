"""
تخزين دائم لحالة أمن الجوال — الأجهزة والرموز.

## لماذا هذا الملف موجود

`MobileSecurityService` كان يحتفظ بالأجهزة والرموز **في الذاكرة**. وهذا مقبول
ما دام لا يوجد تسجيل حقيقي، وكارثيّ لحظةَ يوجد:

    إعادة تشغيل الخادم  ⇒  كل الأجهزة تختفي  ⇒  إعادة مسح QR في كل مرة

وعلى خادم يعمل ٢٤ ساعة ويُعاد تشغيله عند كل تحديث أو انقطاع، يعني ذلك أن
المالكة تُخرج جوالها لتمسح رمزاً كلما سعل الخادم. الاستمرارية هنا **شرط
صلاحية لا تحسين**.

## ما لا يُخزَّن

أي سرّ وسيط أو مفتاح مزوّد. الملف يحوي **رموز جلسة الجوال وحدها**.

## ولماذا تُحفَظ التحدّيات رغم قصر عمرها

أمرُ الاقتران عمليةٌ منفصلة عن الخادم. فلو بقي التحدّي في ذاكرة الأمر لما
رآه الخادم أصلاً، ولفشل كل تسجيل. فالمشاركة عبر الملف **ضرورة بنيوية لا
تساهل أمني**: حمولة التحدّي مصمَّمة أصلاً بلا سرّ (`contains_secret: False`)،
وتموت بعد دقيقتين، وتُستهلَك مرة واحدة. والمنتهي منها يُطرح عند كل حفظ.

## الصلاحيات

الملف يُكتب بـ`0600` ويُفحَص عند القراءة. ملفٌ يقرأه غير مالكه **يُرفَض**،
لأن رموز التجديد فيه تعيش ثلاثين يوماً وتكفي للوصول إلى واجهة الجوال.

الكتابة **ذرّية**: ملف مؤقت في المجلّد نفسه ثم `os.replace`. انقطاع التيار
أثناء الكتابة يترك الملف القديم سليماً لا ملفاً مبتوراً.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1

#: صلاحيات الملف المقبولة: المالك وحده يقرأ ويكتب.
REQUIRED_MODE = 0o600


class MobileStoreError(RuntimeError):
    """خطأ تخزين. **لا يحمل محتوى الملف** — الرسالة لا تُسرِّب رمزاً."""


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _from_iso(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


class MobileStateStore:
    """
    يقرأ ويكتب حالة الجوال في ملف JSON واحد.

    لا يعرف هذا الصنف شيئاً عن قواعد الأمن — يحفظ ما يُعطى ويعيد ما حُفظ.
    القرار الأمني يبقى في `MobileSecurityService`.
    """

    def __init__(self, path: Path | str, *, enforce_permissions: bool = True) -> None:
        self.path = Path(path)
        self.enforce_permissions = enforce_permissions

    # -- القراءة ------------------------------------------------------------

    def _check_permissions(self) -> None:
        """
        الصلاحيات **والمالك**.

        ## ولماذا المالك أيضاً

        الكتابة هنا ذرّيّة: ملفٌ مؤقّت ثم `os.replace`. والمؤقّت يملكه من
        كتبه. فحين وُلِّد رمزُ اقترانٍ بـ`root` — والأداة منفصلة عن الخدمة
        عمداً — انتقلت ملكيةُ الملف إلى `root`، فصارت الخدمة العاملة باسم
        `mathrah` تُرفَض عند القراءة:

            MobileStoreError: تعذّرت قراءة حالة الجوال (PermissionError)
            POST /api/mobile/session/enroll → 500

        والتطبيق يقرأ الخمسمئة «رمزٌ منتهٍ أو مُستهلَك» فتُولَّد رموزٌ بلا
        نهاية، وكلٌّ منها يُعمّق العطل. حدث ذلك فعلاً.

        فالمالك يُفحَص **قبل** أيّ كتابة: أداةٌ تعمل بمستخدمٍ آخر تتوقّف
        برسالةٍ تحمل علاجها، ولا تكسر الخدمة صامتةً.
        """
        if not self.enforce_permissions or os.name != "posix":
            return
        info = self.path.stat()
        mode = stat.S_IMODE(info.st_mode)
        if mode & 0o077:
            raise MobileStoreError(
                f"ملف حالة الجوال مقروء لغير مالكه (الصلاحيات {oct(mode)}). "
                f"صحّحيها بـ: chmod 600 {self.path}"
            )
        if info.st_uid != os.geteuid():
            raise MobileStoreError(
                f"ملف حالة الجوال يملكه المستخدم {info.st_uid} وهذه العملية "
                f"تعمل بالمستخدم {os.geteuid()}. الكتابة تنقل الملكية فتتوقّف "
                f"الخدمة عن قراءته. شغّلي الأداة بمستخدم الخدمة نفسه، أو: "
                f"chown {info.st_uid} {self.path}"
            )

    def load(self) -> dict[str, Any]:
        """
        يعيد `{"devices": [...], "tokens": [...]}`.

        ملفٌ غائب حالةٌ طبيعية (أول تشغيل) ويعيد فارغاً. أما ملفٌ **تالف**
        فيرفع استثناءً ولا يُتجاهَل: تجاهله يعني بدء الخادم بلا أجهزة
        مسجَّلة، فتظنّ المالكة أن جوالها أُلغي.
        """
        if not self.path.exists():
            return {"devices": [], "tokens": [], "challenges": []}
        self._check_permissions()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MobileStoreError(
                f"تعذّرت قراءة حالة الجوال ({type(exc).__name__}). "
                "الملف موجود لكنه غير صالح — لا يُتجاهَل بصمت."
            ) from exc

        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_VERSION:
            raise MobileStoreError(
                "إصدار مخطط حالة الجوال غير متوقَّع. لا تُقرأ بيانات بمخطط مجهول."
            )
        return {
            "devices": list(raw.get("devices", [])),
            "tokens": list(raw.get("tokens", [])),
            "challenges": list(raw.get("challenges", [])),
        }

    # -- الكتابة ------------------------------------------------------------

    def save(
        self, *, devices: list[dict], tokens: list[dict],
        challenges: list[dict] | None = None,
    ) -> None:
        payload = {
            "schema": SCHEMA_VERSION,
            "devices": devices,
            "tokens": tokens,
            "challenges": challenges or [],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)

        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".mobile-state-", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            os.fchmod(fd, REQUIRED_MODE)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        if os.name == "posix":
            os.chmod(self.path, REQUIRED_MODE)


__all__ = [
    "SCHEMA_VERSION", "REQUIRED_MODE",
    "MobileStateStore", "MobileStoreError",
    "_to_iso", "_from_iso",
]
