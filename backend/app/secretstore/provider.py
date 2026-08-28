"""
SecretProvider — مصدر الأسرار الوحيد.

ترتيب الأفضلية:
  1. macOS Keychain (الإنتاج المحلي على جهاز المالكة)
  2. ملف بيئة محلي بصلاحية 600 (تطوير فقط)
  3. الذاكرة (اختبارات فقط)

لا يقرأ هذا الملف أي سرّ إلا عند الطلب، ولا يطبعه، ولا يكتبه.
كل قيمة تُقرأ تُسجَّل فوراً في `redaction.REGISTRY` لتُحجب من كل مخرج.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .redaction import REGISTRY, RedactedError

KEYCHAIN_SERVICE = "maather-autonomous-trader"

CAPITAL_API_KEY = "CAPITAL_API_KEY"
CAPITAL_IDENTIFIER = "CAPITAL_IDENTIFIER"
CAPITAL_API_PASSWORD = "CAPITAL_API_PASSWORD"

REQUIRED_CAPITAL_SECRETS: tuple[str, ...] = (
    CAPITAL_API_KEY,
    CAPITAL_IDENTIFIER,
    CAPITAL_API_PASSWORD,
)

#: إعداد غير سرّي — لا يمرّ عبر SecretProvider.
CAPITAL_ENVIRONMENT = "CAPITAL_ENVIRONMENT"


class SecretNotFound(RedactedError):
    pass


class SecretProviderError(RedactedError):
    pass


@dataclass(frozen=True)
class SecretPresence:
    """
    نتيجة فحص وجود سرّ — **بلا كشف قيمته**.
    هذا هو الشكل الوحيد المسموح لعرض حالة الأسرار في أي واجهة أو تقرير.
    """

    name: str
    present: bool
    source: str

    def as_dict(self) -> dict:
        return {"name": self.name, "present": self.present, "source": self.source}


class SecretProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def _read(self, key: str) -> Optional[str]: ...

    def get(self, key: str) -> str:
        value = self._read(key)
        if not value:
            raise SecretNotFound(
                f"السرّ «{key}» غير موجود في {self.name}. "
                "شغّلي scripts/configure_capital_credentials.sh لضبطه."
            )
        REGISTRY.register(value)
        return value

    def get_optional(self, key: str) -> Optional[str]:
        try:
            return self.get(key)
        except SecretNotFound:
            return None

    def has(self, key: str) -> bool:
        """فحص وجود بلا قراءة القيمة إلى مخرج."""
        try:
            value = self._read(key)
        except Exception:  # noqa: BLE001
            return False
        if value:
            REGISTRY.register(value)
        return bool(value)

    def presence(self, keys: tuple[str, ...] = REQUIRED_CAPITAL_SECRETS) -> list[SecretPresence]:
        return [SecretPresence(name=k, present=self.has(k), source=self.name) for k in keys]

    def missing(self, keys: tuple[str, ...] = REQUIRED_CAPITAL_SECRETS) -> list[str]:
        return [k for k in keys if not self.has(k)]


class KeychainSecretProvider(SecretProvider):
    """
    macOS Keychain عبر أداة `security`.

    القيمة لا تظهر في سطر الأوامر ولا في سجل الصدفة: نقرؤها من stdout مباشرة
    ونمنع أي طباعة. الكتابة تتم من السكربت التفاعلي لا من هنا.
    """

    name = "macos-keychain"

    def __init__(self, service: str = KEYCHAIN_SERVICE) -> None:
        self.service = service

    @staticmethod
    def available() -> bool:
        return shutil.which("security") is not None

    def _read(self, key: str) -> Optional[str]:
        if not self.available():
            return None
        try:
            result = subprocess.run(  # noqa: S603
                ["security", "find-generic-password", "-s", self.service, "-a", key, "-w"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SecretProviderError(f"تعذّر الوصول إلى Keychain: {type(exc).__name__}") from None
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None


class EnvFileSecretProvider(SecretProvider):
    """
    ملف بيئة محلي — **للتطوير فقط**.

    يرفض العمل إذا كانت صلاحيات الملف أوسع من 600، لأن ملفاً قابلاً للقراءة
    من مستخدمين آخرين ليس مكاناً لسرّ.
    """

    name = "env-file"

    def __init__(self, path: Path | str, *, enforce_permissions: bool = True) -> None:
        self.path = Path(path)
        self.enforce_permissions = enforce_permissions
        self._cache: dict[str, str] | None = None

    def _check_permissions(self) -> None:
        if not self.enforce_permissions:
            return
        mode = stat.S_IMODE(self.path.stat().st_mode)
        if mode & 0o077:
            raise SecretProviderError(
                f"ملف الأسرار {self.path} صلاحياته {oct(mode)} — يجب أن تكون 600. "
                f"نفّذي: chmod 600 {self.path}"
            )

    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = {}
            return self._cache
        self._check_permissions()
        data: dict[str, str] = {}
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if value:
                data[key.strip()] = value
        self._cache = data
        return data

    def _read(self, key: str) -> Optional[str]:
        return self._load().get(key)

    def invalidate(self) -> None:
        self._cache = None


class EnvironmentSecretProvider(SecretProvider):
    """متغيرات البيئة — للاختبارات وCI فقط، لا للإنتاج."""

    name = "process-environment"

    def _read(self, key: str) -> Optional[str]:
        return os.environ.get(key) or None


class InMemorySecretProvider(SecretProvider):
    """اختبارات فقط."""

    name = "in-memory"

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def set(self, key: str, value: str) -> None:
        self._values[key] = value

    def _read(self, key: str) -> Optional[str]:
        return self._values.get(key)


class ChainedSecretProvider(SecretProvider):
    """أول مزوّد يملك القيمة يفوز. يُستخدم للترتيب Keychain ← ملف ← بيئة."""

    name = "chained"

    def __init__(self, providers: list[SecretProvider]) -> None:
        if not providers:
            raise ValueError("ChainedSecretProvider يحتاج مزوّداً واحداً على الأقل")
        self.providers = providers
        self.name = "chained(" + ",".join(p.name for p in providers) + ")"

    def _read(self, key: str) -> Optional[str]:
        for provider in self.providers:
            try:
                value = provider._read(key)  # noqa: SLF001
            except SecretProviderError:
                continue
            if value:
                return value
        return None

    def presence(self, keys: tuple[str, ...] = REQUIRED_CAPITAL_SECRETS) -> list[SecretPresence]:
        out: list[SecretPresence] = []
        for key in keys:
            found_in = "—"
            present = False
            for provider in self.providers:
                try:
                    if provider._read(key):  # noqa: SLF001
                        present = True
                        found_in = provider.name
                        break
                except SecretProviderError:
                    continue
            out.append(SecretPresence(name=key, present=present, source=found_in))
        return out


def build_secret_provider(
    *,
    env_file: Path | str | None = None,
    allow_process_env: bool = False,
) -> SecretProvider:
    """
    يبني السلسلة الافتراضية: Keychain (إن وُجد) ← ملف .secrets.env ← البيئة (اختياري).
    """
    providers: list[SecretProvider] = []
    if KeychainSecretProvider.available():
        providers.append(KeychainSecretProvider())
    if env_file is not None:
        providers.append(EnvFileSecretProvider(env_file))
    if allow_process_env:
        providers.append(EnvironmentSecretProvider())
    if not providers:
        providers.append(InMemorySecretProvider())
    return ChainedSecretProvider(providers) if len(providers) > 1 else providers[0]
