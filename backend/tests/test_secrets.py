"""
الأسرار — الوجود بلا كشف، والحجب في كل مخرج.

هذا الملف يفشل عمداً لو تسرّب سرّ إلى سجل، أو استثناء، أو تقرير،
أو Audit Log، أو لقطة اختبار، أو قاعدة بيانات.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
from pathlib import Path

import pytest

from app.audit.log import Actor, AuditAction, AuditLog, InMemoryAuditStore
from app.secretstore.provider import (
    CAPITAL_API_KEY,
    CAPITAL_API_PASSWORD,
    CAPITAL_IDENTIFIER,
    REQUIRED_CAPITAL_SECRETS,
    ChainedSecretProvider,
    EnvFileSecretProvider,
    InMemorySecretProvider,
    KeychainSecretProvider,
    SecretNotFound,
    SecretProviderError,
    build_secret_provider,
)
from app.secretstore.redaction import (
    MASK,
    REGISTRY,
    RedactedError,
    RedactingFilter,
    install_redacting_filter,
    redact,
    redact_headers,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

SECRET_VALUE = "super-secret-capital-key-999999"


@pytest.fixture(autouse=True)
def clean_registry():
    REGISTRY.clear()
    yield
    REGISTRY.clear()


# --- المزوّدون ---------------------------------------------------------------

def test_in_memory_provider_returns_and_registers_secret():
    provider = InMemorySecretProvider({CAPITAL_API_KEY: SECRET_VALUE})
    assert provider.get(CAPITAL_API_KEY) == SECRET_VALUE
    assert SECRET_VALUE in REGISTRY.known_values()


def test_missing_secret_raises_without_revealing_the_key_name_value():
    provider = InMemorySecretProvider({})
    with pytest.raises(SecretNotFound) as exc:
        provider.get(CAPITAL_API_KEY)
    assert "configure_capital_credentials" in str(exc.value)


def test_presence_check_never_returns_the_value():
    provider = InMemorySecretProvider({CAPITAL_API_KEY: SECRET_VALUE})
    presences = provider.presence(REQUIRED_CAPITAL_SECRETS)
    serialised = json.dumps([p.as_dict() for p in presences], ensure_ascii=False)
    assert SECRET_VALUE not in serialised
    assert any(p.present for p in presences)
    assert provider.missing() == [CAPITAL_IDENTIFIER, CAPITAL_API_PASSWORD]


def test_env_file_provider_requires_600_permissions(tmp_path):
    path = tmp_path / "capital.env"
    path.write_text(f"{CAPITAL_API_KEY}={SECRET_VALUE}\n", encoding="utf-8")
    os.chmod(path, 0o644)
    provider = EnvFileSecretProvider(path)
    with pytest.raises(SecretProviderError, match="600"):
        provider.get(CAPITAL_API_KEY)


def test_env_file_provider_reads_when_permissions_are_correct(tmp_path):
    path = tmp_path / "capital.env"
    path.write_text(f"{CAPITAL_API_KEY}={SECRET_VALUE}\n# comment\n\n", encoding="utf-8")
    os.chmod(path, 0o600)
    assert EnvFileSecretProvider(path).get(CAPITAL_API_KEY) == SECRET_VALUE


def test_chained_provider_prefers_the_first_source(tmp_path):
    path = tmp_path / "capital.env"
    path.write_text(f"{CAPITAL_API_KEY}=from-file-000000\n", encoding="utf-8")
    os.chmod(path, 0o600)
    chained = ChainedSecretProvider(
        [InMemorySecretProvider({CAPITAL_API_KEY: SECRET_VALUE}), EnvFileSecretProvider(path)]
    )
    assert chained.get(CAPITAL_API_KEY) == SECRET_VALUE


def test_build_secret_provider_never_reads_process_env_by_default(monkeypatch, tmp_path):
    """
    **الاختبار يقيس ما يقوله اسمه.**

    كان يفترض ضمناً أن لا مصدرَ آخر يحمل السرّ، فيمرّ على خادمٍ بلا Keychain
    ويسقط على ماكٍ فيه الاعتمادات الحقيقية — وهو حينها يقيس الجهاز لا الشيفرة.

    فيُطفأ Keychain صراحةً: تبقى البيئة وحدها مصدراً محتملاً، ورفضُها هو
    بالضبط ما يَعِد به الاسم.
    """
    monkeypatch.setenv(CAPITAL_API_KEY, SECRET_VALUE)
    monkeypatch.setattr(KeychainSecretProvider, "available", staticmethod(lambda: False))

    provider = build_secret_provider(env_file=tmp_path / "none.env", allow_process_env=False)
    assert provider.has(CAPITAL_API_KEY) is False

    # وحين يُؤذَن لها صراحةً تُقرأ — وإلا لم يكن الرفض قراراً بل عجزاً.
    permitted = build_secret_provider(env_file=tmp_path / "none.env", allow_process_env=True)
    assert permitted.get(CAPITAL_API_KEY) == SECRET_VALUE


def test_keychain_provider_reports_availability_without_crashing():
    assert isinstance(KeychainSecretProvider.available(), bool)


# --- الحجب -------------------------------------------------------------------

def test_registered_secret_is_redacted_from_text():
    REGISTRY.register(SECRET_VALUE)
    assert SECRET_VALUE not in redact(f"key is {SECRET_VALUE} here")
    assert MASK in redact(f"key is {SECRET_VALUE} here")


def test_sensitive_header_names_are_redacted_by_name():
    headers = redact_headers({"CST": "abc", "X-SECURITY-TOKEN": "def", "X-CAP-API-KEY": "ghi"})
    assert set(headers.values()) == {MASK}


def test_nested_structures_are_redacted():
    REGISTRY.register(SECRET_VALUE)
    payload = {"outer": {"password": "x", "note": f"contains {SECRET_VALUE}"}, "list": [SECRET_VALUE]}
    result = redact(payload)
    assert result["outer"]["password"] == MASK
    assert SECRET_VALUE not in json.dumps(result, ensure_ascii=False)


def test_email_like_identifier_is_redacted_even_if_unregistered():
    assert "owner@example.test" not in redact("login owner@example.test failed")


def test_exceptions_cannot_carry_a_secret():
    REGISTRY.register(SECRET_VALUE)
    error = RedactedError(f"failed with {SECRET_VALUE}")
    assert SECRET_VALUE not in str(error)


def test_logging_filter_redacts_message_and_args(caplog):
    REGISTRY.register(SECRET_VALUE)
    logger = logging.getLogger("test.redaction")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="test.redaction"):
        logger.info("token=%s", SECRET_VALUE)
    assert SECRET_VALUE not in caplog.text


def test_install_redacting_filter_is_idempotent():
    logger = logging.getLogger("test.install")
    install_redacting_filter(logger)
    install_redacting_filter(logger)
    assert sum(isinstance(f, RedactingFilter) for f in logger.filters) == 1


def test_audit_log_payloads_are_redacted():
    REGISTRY.register(SECRET_VALUE)
    log = AuditLog(InMemoryAuditStore())
    event = log.record(
        actor=Actor.SYSTEM,
        action=AuditAction.SYSTEM_START,
        decision="OK",
        reason_ar="بدء",
        source="test",
        after=redact({"api_key": SECRET_VALUE, "note": f"value {SECRET_VALUE}"}),
    )
    serialised = json.dumps(event.after, ensure_ascii=False)
    assert SECRET_VALUE not in serialised


def test_session_tokens_are_never_persisted_to_the_database():
    """
    الجداول لا تحتوي أي عمود يمكن أن يخزّن CST أو X-SECURITY-TOKEN.
    """
    from app.db.models import Base

    forbidden = {"cst", "security_token", "x_security_token", "api_key", "password", "token"}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            assert column.name.lower() not in forbidden, f"{table.name}.{column.name}"


def test_discovery_report_contains_no_secret():
    from tests.capital_fixtures import FAKE_API_KEY, FAKE_CST, build_adapter
    from app.discovery.capital_discovery import run_discovery

    adapter, _g, _f = build_adapter()
    adapter.connect()
    report = run_discovery(adapter, epics=("EURUSD",), fetch_candles=False)
    serialised = json.dumps(report.to_json(), ensure_ascii=False, default=str)
    assert FAKE_API_KEY not in serialised
    assert FAKE_CST not in serialised
    assert "1234567890123456" not in serialised, "معرّف الحساب الكامل يجب ألا يظهر"
    assert report.to_json()["secrets_included"] is False


def test_adapter_state_report_masks_the_account():
    from tests.capital_fixtures import build_adapter

    adapter, _g, _f = build_adapter()
    adapter.connect()
    adapter.select_account()
    state = adapter.state_for_report()
    assert state["selected_account_masked"] == "****3456"
    assert "1234567890123456" not in json.dumps(state)


# --- Git ---------------------------------------------------------------------

def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout


def test_secret_paths_are_ignored_by_git():
    for candidate in (".env", "secrets/capital.env", "secrets/live_approval.json", "data/x.db"):
        output = _git("check-ignore", "-v", candidate)
        assert output.strip(), f"{candidate} ليس مستثنى في .gitignore"


def test_no_tracked_file_contains_a_credential_assignment():
    tracked = _git("ls-files").splitlines()
    suspicious: list[str] = []
    for name in tracked:
        path = REPO_ROOT / name
        if not path.is_file() or path.suffix in {".png", ".jpg", ".gz", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for key in ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_API_PASSWORD"):
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped.startswith(f"{key}="):
                    continue
                value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                # القيم المسموحة: فارغة أو نائبة صريحة
                if value and not value.startswith("your-") and not value.startswith("<"):
                    suspicious.append(f"{name}: {key}")
    assert not suspicious, f"قيم اعتماد في ملفات متتبَّعة: {suspicious}"


def test_env_example_documents_secrets_without_assigning_them():
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LIVE_TRADING=false" in example
    assert "RISK_MODE=VALIDATION" in example
    assert "CAPITAL_ENVIRONMENT=demo" in example
    for key in ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_API_PASSWORD"):
        assert key in example, "يجب توثيق اسم السرّ"
        for line in example.splitlines():
            stripped = line.strip()
            assert not stripped.startswith(f"{key}="), f"{key} مُسنَد في .env.example"


def test_secrets_directory_is_ignored_but_documented():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "secrets/" in gitignore
    assert ".env" in gitignore


def test_credential_script_refuses_command_line_values():
    script = (REPO_ROOT / "scripts" / "configure_capital_credentials.sh").read_text(encoding="utf-8")
    assert "لا يقبل قيماً في سطر الأوامر" in script
    assert "read -r -s" in script
    assert "set +o history" in script
    assert "chmod 600" in script
