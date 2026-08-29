"""
PROVIDER CACHE — ذاكرة مؤقتة خاصة، ذرّية، مُرقَّمة المخطط.

## أين تعيش

    data/private/provider_cache/

تحت الشجرة الخاصة نفسها التي تحمي تقارير الحساب: متجاهَلة في git، غير
متتبَّعة، أذوناتها 700/600. السبب ليس أن استجابة FRED سرّية — بل أن الذاكرة
المؤقتة تحفظ **ما استُعلم عنه ومتى**، وهو نمط استعمال لا داعي لأن يدخل
مستودعاً.

## `stale-while-revalidate` للعرض وحده

القيمة البائتة تُعرَض في الواجهة موسومة «قديمة»، **ولا تدخل قراراً**. هذا
التمييز مفروض في النوع نفسه: `for_display()` تعيد قيمة بائتة،
و`for_decision()` لا تعيدها أبداً.

## الذرّية

ملف مؤقت ثم `os.replace`. انقطاعٌ أثناء الكتابة يترك ملف JSON مبتوراً يُقرأ
لاحقاً فيُرمى بـ`JSONDecodeError` — أو أسوأ، يُقرأ جزئياً فيبدو صالحاً.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from ..live_readonly.private_store import (
    DIR_MODE,
    FILE_MODE,
    PRIVATE_ROOT_PARTS,
    PrivateStoreError,
)
from .provenance import NORMALIZED_SCHEMA_VERSION, raw_checksum

CACHE_PARTS: tuple[str, ...] = PRIVATE_ROOT_PARTS + ("provider_cache",)

_PERMISSIONS_SUPPORTED = os.name == "posix"


class CacheError(RuntimeError):
    """فشل في الذاكرة المؤقتة. **لا يُسقط الاستدعاء** — يُعامَل كغياب."""


def cache_directory(repo_root: Path) -> Path:
    return repo_root.joinpath(*CACHE_PARTS)


def ensure_cache_directory(repo_root: Path) -> Path:
    directory = cache_directory(repo_root)
    parent = repo_root.joinpath(*PRIVATE_ROOT_PARTS)
    for path in (parent, directory):
        path.mkdir(parents=True, exist_ok=True)
        if _PERMISSIONS_SUPPORTED:
            try:
                path.chmod(DIR_MODE)
            except OSError:
                pass
    return directory


def cache_key(*parts: Any) -> str:
    """
    مفتاح حتمي وآمن للاسم. بصمة لا نص: المفتاح قد يحمل نطاق تواريخ أو رمز
    سلسلة، وتحويله إلى اسم ملف مباشرةً يفتح باب اجتياز المسار.
    """
    return raw_checksum([str(p) for p in parts])[:32]


@dataclass(frozen=True)
class CacheEntry:
    key: str
    schema_version: str
    stored_at_utc: datetime
    ttl_seconds: float
    payload: Any

    def age_seconds(self, now: datetime) -> float:
        return (now - self.stored_at_utc).total_seconds()

    def is_fresh(self, now: datetime) -> bool:
        return self.age_seconds(now) <= self.ttl_seconds

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "schema_version": self.schema_version,
            "stored_at_utc": self.stored_at_utc.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "payload": self.payload,
        }


class ProviderCache:
    """
    ذاكرة مؤقتة على القرص. تفشل **بصمت آمن**: أي خلل يُعامَل كغياب قيمة،
    فيُعاد الاستعلام. ذاكرةٌ مؤقتة تُسقط النظام أسوأ من غياب ذاكرة مؤقتة.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        schema_version: str = NORMALIZED_SCHEMA_VERSION,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repo_root = repo_root
        self.schema_version = schema_version
        self.clock = clock

    def _path(self, key: str) -> Path:
        return cache_directory(self.repo_root) / f"{key}.json"

    def store(self, key: str, payload: Any, *, ttl_seconds: float) -> Optional[Path]:
        entry = CacheEntry(
            key=key,
            schema_version=self.schema_version,
            stored_at_utc=self.clock(),
            ttl_seconds=ttl_seconds,
            payload=payload,
        )
        try:
            ensure_cache_directory(self.repo_root)
            path = self._path(key)
            tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                os.unlink(tmp)
            except OSError:
                pass
            fd = os.open(tmp, flags, FILE_MODE)
            moved = False
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(entry.as_dict(), handle, ensure_ascii=False, default=str)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
                moved = True
            finally:
                if not moved:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
            return path
        except (OSError, PrivateStoreError, TypeError, ValueError):
            return None

    def _load(self, key: str) -> Optional[CacheEntry]:
        try:
            raw = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        # مخطط مختلف ⇒ تُهمَل الإدخالة. خلط مخطَّطين أسوأ من إعادة الاستعلام.
        if raw.get("schema_version") != self.schema_version:
            return None
        try:
            stored = datetime.fromisoformat(str(raw["stored_at_utc"]))
        except (KeyError, ValueError):
            return None
        if stored.tzinfo is None:
            return None
        return CacheEntry(
            key=str(raw.get("key", key)),
            schema_version=str(raw["schema_version"]),
            stored_at_utc=stored,
            ttl_seconds=float(raw.get("ttl_seconds", 0.0)),
            payload=raw.get("payload"),
        )

    def for_decision(self, key: str) -> Optional[Any]:
        """قيمة **طازجة فقط**. البائتة لا تدخل قراراً بحال."""
        entry = self._load(key)
        if entry is None or not entry.is_fresh(self.clock()):
            return None
        return entry.payload

    def for_display(self, key: str) -> Optional[tuple[Any, bool]]:
        """
        `(القيمة، هل هي طازجة)`. البائتة تُعاد **موسومة** كي تعرضها الواجهة
        مع تحذير — stale-while-revalidate للعرض لا للقرار.
        """
        entry = self._load(key)
        if entry is None:
            return None
        return entry.payload, entry.is_fresh(self.clock())

    def invalidate(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except OSError:
            pass


def deduplicate(records: list[Any], *, key: Callable[[Any], str]) -> list[Any]:
    """
    إزالة تكرار مع **الحفاظ على الترتيب**. الترتيب مهم: أول ظهور للخبر هو
    زمنه الحقيقي، وإعادة النشر لاحقاً لا تجعله أحدث.
    """
    seen: set[str] = set()
    out: list[Any] = []
    for record in records:
        identifier = key(record)
        if identifier in seen:
            continue
        seen.add(identifier)
        out.append(record)
    return out


__all__ = [
    "CACHE_PARTS",
    "CacheError",
    "CacheEntry",
    "ProviderCache",
    "cache_directory",
    "ensure_cache_directory",
    "cache_key",
    "deduplicate",
]
