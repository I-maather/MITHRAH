"""
اختبارات تشخيص المصادقة — **باعتمادات وهمية واستجابات مُقلَّدة بالكامل**.

لا شبكة · لا Keychain · لا اعتماد حقيقي · لا رمز جلسة حقيقي.
كل قيمة هنا مكتوبة صراحةً في هذا الملف.
"""
from __future__ import annotations

import base64

import pytest

from app.brokers.capital.endpoints import (
    DEMO_BASE_URL,
    LIVE_BASE_URL,
    PATH_ACCOUNTS,
    PATH_ENCRYPTION_KEY,
    PATH_POSITIONS,
    PATH_SESSION,
    CapitalEnvironment,
)
from app.brokers.capital.ratelimit import RateLimiter
from app.brokers.capital.safety import ExecutionLock
from app.brokers.capital.transport import ApiResponse, FixtureTransport, GuardedTransport
from app.diagnostics.auth_probe import (
    ALLOWED_OPERATIONS,
    MAX_ATTEMPTS_PER_MODE,
    AuthMode,
    ProbeViolation,
    render_report,
    run_auth_probe,
)
from app.secretstore.provider import InMemorySecretProvider
from app.secretstore.redaction import REGISTRY

# اعتمادات وهمية — لا معنى لها خارج هذا الملف.
FAKE_API_KEY = "dummy-api-key-ZZZZ0001"
FAKE_IDENTIFIER = "dummy.person@example.invalid"
FAKE_PASSWORD = "dummy-key-password-ZZZZ0001"

FAKE_CST = "dummy-cst-token-ZZZZ"
FAKE_SECURITY_TOKEN = "dummy-security-token-ZZZZ"


class RawRecorder:
    """
    يلتقط الطلبات **قبل** الحجب، كي تستطيع الاختبارات إثبات أن الحمولة
    المشفّرة أُرسلت فعلاً ومع ذلك لا تظهر في التقرير.
    يعيش داخل الاختبار وحده — لا وجود له في كود التشغيل.
    """

    def __init__(self, inner):
        self.inner = inner
        self.raw_calls: list[dict] = []

    @property
    def name(self) -> str:
        return "raw-recorder"

    @property
    def calls(self) -> list[dict]:
        return self.raw_calls

    def send(self, method, url, *, headers, params=None, json=None, timeout=30.0):
        self.raw_calls.append(
            {"method": method.upper(), "url": url, "headers": dict(headers),
             "json": dict(json or {})}
        )
        return self.inner.send(
            method, url, headers=headers, params=params, json=json, timeout=timeout
        )


@pytest.fixture(autouse=True)
def _clear_registry():
    REGISTRY.clear()
    yield
    REGISTRY.clear()


def secrets() -> InMemorySecretProvider:
    return InMemorySecretProvider({
        "CAPITAL_API_KEY": FAKE_API_KEY,
        "CAPITAL_IDENTIFIER": FAKE_IDENTIFIER,
        "CAPITAL_API_PASSWORD": FAKE_PASSWORD,
    })


def _rsa_public_key_der_b64() -> str:
    """مفتاح RSA حقيقي مُولَّد محلياً للاختبار فقط — ليس مفتاح أي جهة."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    der = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode()


def build(
    *,
    encryption_key: str | None = None,
    encrypted_response: ApiResponse | None = None,
    plaintext_response: ApiResponse | None = None,
    key_status: int = 200,
) -> tuple[GuardedTransport, FixtureTransport]:
    """
    ناقل مُقلَّد: يرد على `GET /session/encryptionKey` ثم على `POST /session`
    بردّ مختلف لكل وضع حسب `encryptedPassword` في الجسم.
    """
    fixture = FixtureTransport()
    key_body = (
        {"encryptionKey": encryption_key, "timeStamp": 1700000000000}
        if encryption_key
        else {}
    )
    fixture.register_json(
        "GET", PATH_ENCRYPTION_KEY, key_body, status=key_status
    )

    def session_handler(ctx: dict) -> ApiResponse:
        body = ctx.get("json") or {}
        if body.get("encryptedPassword") is True:
            return encrypted_response or ApiResponse(
                401, {}, {"errorCode": "error.invalid.details"}
            )
        return plaintext_response or ApiResponse(
            401, {}, {"errorCode": "error.invalid.details"}
        )

    fixture.register("POST", PATH_SESSION, session_handler)
    recorder = RawRecorder(fixture)
    guarded = GuardedTransport(
        inner=recorder, execution_lock=ExecutionLock.locked(), rate_limiter=RateLimiter()
    )
    return guarded, recorder


def ok_session() -> ApiResponse:
    return ApiResponse(
        200,
        {"CST": FAKE_CST, "X-SECURITY-TOKEN": FAKE_SECURITY_TOKEN},
        {"accountType": "CFD", "currencyIsoCode": "USD"},
    )


# ---------------------------------------------------------------------------
# الحدود المفروضة
# ---------------------------------------------------------------------------

def test_live_environment_is_refused_outright():
    guarded, _ = build(encryption_key=_rsa_public_key_der_b64())
    with pytest.raises(ProbeViolation):
        run_auth_probe(
            transport=guarded, secrets=secrets(), environment=CapitalEnvironment.LIVE
        )


def test_probe_never_touches_the_live_url():
    guarded, fixture = build(encryption_key=_rsa_public_key_der_b64())
    run_auth_probe(transport=guarded, secrets=secrets())
    for call in fixture.calls:
        assert LIVE_BASE_URL not in call["url"]
        assert call["url"].startswith(DEMO_BASE_URL)


def test_only_encryption_key_and_session_paths_are_used():
    guarded, _ = build(encryption_key=_rsa_public_key_der_b64())
    report = run_auth_probe(transport=guarded, secrets=secrets())

    for op in report.operations_sent:
        assert op in ALLOWED_OPERATIONS
    paths = {p for _, p in report.operations_sent}
    assert PATH_POSITIONS not in paths
    assert PATH_ACCOUNTS not in paths


def test_at_most_one_session_post_per_mode():
    guarded, _ = build(encryption_key=_rsa_public_key_der_b64())
    report = run_auth_probe(transport=guarded, secrets=secrets())

    posts = [op for op in report.operations_sent if op == ("POST", PATH_SESSION)]
    assert len(posts) <= 2 * MAX_ATTEMPTS_PER_MODE
    assert MAX_ATTEMPTS_PER_MODE == 1


def test_probe_does_not_import_the_broker_adapter():
    """التشخيص لا يملك مساراً إلى أي مركز أو أمر — بالبنية لا بالتعليمات."""
    import ast

    import app.diagnostics.auth_probe as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(a.name for a in node.names)

    assert not any("adapter" in n for n in imported)
    assert not any("execution" in n for n in imported)
    assert "CapitalComAdapter" not in imported


# ---------------------------------------------------------------------------
# الوضعان
# ---------------------------------------------------------------------------

def test_encrypted_mode_succeeding_stops_before_sending_credentials_again():
    guarded, _ = build(
        encryption_key=_rsa_public_key_der_b64(), encrypted_response=ok_session()
    )
    report = run_auth_probe(transport=guarded, secrets=secrets())

    assert report.working_mode is AuthMode.ENCRYPTED
    encrypted = next(a for a in report.attempts if a.mode is AuthMode.ENCRYPTED)
    plaintext = next(a for a in report.attempts if a.mode is AuthMode.PLAINTEXT)
    assert encrypted.attempted is True and encrypted.succeeded is True
    assert plaintext.attempted is False        # لم تُرسل الاعتمادات ثانيةً
    posts = [op for op in report.operations_sent if op == ("POST", PATH_SESSION)]
    assert len(posts) == 1


def test_plaintext_mode_is_tried_only_after_the_encrypted_one_fails():
    guarded, _ = build(
        encryption_key=_rsa_public_key_der_b64(),
        encrypted_response=ApiResponse(401, {}, {"errorCode": "error.invalid.details"}),
        plaintext_response=ok_session(),
    )
    report = run_auth_probe(transport=guarded, secrets=secrets())

    assert report.working_mode is AuthMode.PLAINTEXT
    assert all(a.attempted for a in report.attempts)
    posts = [op for op in report.operations_sent if op == ("POST", PATH_SESSION)]
    assert len(posts) == 2


def test_both_modes_failing_is_reported_with_status_and_code():
    guarded, _ = build(encryption_key=_rsa_public_key_der_b64())
    report = run_auth_probe(transport=guarded, secrets=secrets())

    assert report.working_mode is None
    for a in report.attempts:
        assert a.attempted is True
        assert a.http_status == 401
        assert a.error_code == "error.invalid.details"
        assert a.succeeded is False


def test_missing_encryption_key_skips_the_encrypted_mode_without_attempting():
    guarded, _ = build(encryption_key=None, key_status=401)
    report = run_auth_probe(transport=guarded, secrets=secrets())

    encrypted = next(a for a in report.attempts if a.mode is AuthMode.ENCRYPTED)
    assert encrypted.attempted is False
    assert report.encryption_key_available is False
    # الوضع الثاني يُجرَّب مع ذلك
    plaintext = next(a for a in report.attempts if a.mode is AuthMode.PLAINTEXT)
    assert plaintext.attempted is True


# ---------------------------------------------------------------------------
# عدم التسريب — أهم ما في هذا الملف
# ---------------------------------------------------------------------------

def _all_report_text(report) -> str:
    return render_report(report) + repr(report.as_dict())


@pytest.mark.parametrize(
    "scenario",
    ["both_fail", "encrypted_ok", "plaintext_ok", "no_key"],
)
def test_no_secret_ever_appears_in_the_report(scenario):
    key = _rsa_public_key_der_b64()
    if scenario == "both_fail":
        guarded, _ = build(encryption_key=key)
    elif scenario == "encrypted_ok":
        guarded, _ = build(encryption_key=key, encrypted_response=ok_session())
    elif scenario == "plaintext_ok":
        guarded, _ = build(encryption_key=key, plaintext_response=ok_session())
    else:
        guarded, _ = build(encryption_key=None, key_status=401)

    report = run_auth_probe(transport=guarded, secrets=secrets())
    text = _all_report_text(report)

    for secret in (FAKE_API_KEY, FAKE_IDENTIFIER, FAKE_PASSWORD,
                   FAKE_CST, FAKE_SECURITY_TOKEN):
        assert secret not in text, f"تسرّب في السيناريو {scenario}"


def test_the_encrypted_payload_is_never_exposed():
    key = _rsa_public_key_der_b64()
    guarded, fixture = build(encryption_key=key)
    report = run_auth_probe(transport=guarded, secrets=secrets())

    sent_payloads = [
        c.get("json") for c in fixture.calls if c.get("json") is not None
    ]
    encrypted_values = [
        p.get("password") for p in sent_payloads if p.get("encryptedPassword") is True
    ]
    assert encrypted_values, "المفترض أن الوضع المشفّر أُرسل"

    text = _all_report_text(report)
    for value in encrypted_values:
        assert str(value) not in text


def test_report_has_no_field_that_could_hold_a_secret():
    """البنية نفسها لا تحتوي حقلاً للمعرّف أو كلمة المرور أو الرموز."""
    from app.diagnostics.auth_probe import ProbeAttempt, ProbeReport

    for cls in (ProbeAttempt, ProbeReport):
        fields = set(cls.__dataclass_fields__)
        for forbidden in (
            "identifier", "password", "api_key", "cst", "token",
            "security_token", "payload", "encrypted",
        ):
            assert forbidden not in fields


def test_session_tokens_are_discarded_immediately():
    guarded, _ = build(
        encryption_key=_rsa_public_key_der_b64(), encrypted_response=ok_session()
    )
    report = run_auth_probe(transport=guarded, secrets=secrets())

    assert report.tokens_retained is False
    # ولا يبقى الرمز في سجل الحجب بعد النسيان
    assert FAKE_CST not in REGISTRY.known_values()
    assert FAKE_SECURITY_TOKEN not in REGISTRY.known_values()


def test_arbitrary_server_text_is_never_echoed():
    """نص حر من الخادم لا يُعرض — قد يحمل ما لا نتوقعه."""
    hostile = ApiResponse(
        401, {}, {"errorCode": "leaked " + FAKE_PASSWORD, "message": FAKE_API_KEY}
    )
    guarded, _ = build(
        encryption_key=_rsa_public_key_der_b64(),
        encrypted_response=hostile,
        plaintext_response=hostile,
    )
    report = run_auth_probe(transport=guarded, secrets=secrets())

    for a in report.attempts:
        assert a.error_code is None      # المسافة تُبطل النمط الضيق
    text = _all_report_text(report)
    assert FAKE_PASSWORD not in text
    assert FAKE_API_KEY not in text


def test_error_code_pattern_accepts_only_narrow_tokens():
    from app.diagnostics.auth_probe import _sanitize_error_code

    assert _sanitize_error_code({"errorCode": "error.invalid.details"}) == "error.invalid.details"
    assert _sanitize_error_code({"errorCode": "a" * 200}) is None
    assert _sanitize_error_code({"errorCode": "has space"}) is None
    assert _sanitize_error_code({"errorCode": {"nested": 1}}) is None
    assert _sanitize_error_code({}) is None
    assert _sanitize_error_code("not a dict") is None


# ---------------------------------------------------------------------------
# الإرشاد
# ---------------------------------------------------------------------------

def test_guidance_names_the_working_mode_when_one_succeeds():
    guarded, _ = build(
        encryption_key=_rsa_public_key_der_b64(), plaintext_response=ok_session()
    )
    report = run_auth_probe(transport=guarded, secrets=secrets())
    joined = " ".join(report.guidance_ar)
    assert "الوضع العامل" in joined


def test_double_401_guidance_raises_the_key_environment_first():
    guarded, _ = build(encryption_key=_rsa_public_key_der_b64())
    report = run_auth_probe(transport=guarded, secrets=secrets())
    joined = " ".join(report.guidance_ar)

    assert "فشل الوضعان بـ401" in joined
    assert "بيئة المفتاح" in joined          # الاحتمال الأول
    assert "Google Sign-In" in joined        # الاحتمال الثاني
    assert "لا تعيدي التشغيل أكثر من مرة" in joined


def test_rendered_report_states_what_was_not_shown():
    guarded, _ = build(encryption_key=_rsa_public_key_der_b64())
    report = run_auth_probe(transport=guarded, secrets=secrets())
    text = render_report(report)

    assert "لم يُعرض في هذا التقرير" in text
    assert "رموز جلسة مُخزَّنة: لا" in text
    assert "POST /api/v1/session" in text


def test_cli_rejects_live_environment_at_argument_parsing():
    from app.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["capital-auth-probe", "--environment", "live"])
