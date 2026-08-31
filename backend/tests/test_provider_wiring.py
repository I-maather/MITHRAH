"""
اختبارات وصل المزوّدين — **بوسيطٍ له جلسة**.

## لماذا هذا الملف موجود

وُصل سجلّ المزوّدين، ومرّت المجموعة كاملة، ثم انفجر النظام على الخادم عند
أوّل استعلام:

    AttributeError: 'CapitalSession' object has no attribute 'authenticated'

والسبب أن كل اختبارات المجموعة تبني النظام بوسيطٍ **وهمي**، والوسيط الوهمي
بلا `session`. فالفرع الذي يبني مزوّد بيانات السوق لم يُنفَّذ في اختبارٍ
واحد — كُتب ونُشر ولم يُجرَّب.

فهذه الاختبارات تبني السجلّ بوسيطٍ **له جلسة**، وتغطّي الفرع الذي كسر.
ولا تلمس الشبكة: الجلسة مُقلَّدة بالكامل.
"""
from __future__ import annotations

import pytest

from app.api.state import build_provider_registry
from app.intelligence.providers import ProviderKind
from app.live_readonly.capital_bridge import CapitalReadOnlyBridge
from app.secretstore.provider import InMemorySecretProvider


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, method, url, *, headers=None, params=None, json=None, timeout=30):
        self.sent.append((method, url))

        class R:
            status = 200
            headers: dict = {}
            body: dict = {"prices": []}

            @property
            def ok(self) -> bool:
                return True

        return R()


class FakeCapitalSession:
    """تُحاكي `CapitalSession` في ما يلمسه الجسر وحده."""

    base_url = "https://api-capital.backend-capital.com"

    def __init__(self, *, tokens: object | None = "cst/xst") -> None:
        self.tokens = tokens
        self.transport = FakeTransport()
        self.ensured = 0

    def ensure_session(self) -> None:
        self.ensured += 1
        self.tokens = self.tokens or "cst/xst"

    def auth_headers(self) -> dict:
        return {"X-SECURITY-TOKEN": "***"}


class BrokerWithSession:
    def __init__(self, session) -> None:
        self.session = session


class BrokerWithoutSession:
    """كالوسيط الوهمي: بلا جلسة."""


def secrets(**kv) -> InMemorySecretProvider:
    return InMemorySecretProvider(dict(kv))


# ---------------------------------------------------------------------------
# الجسر
# ---------------------------------------------------------------------------
def test_bridge_reports_authenticated_from_tokens():
    assert CapitalReadOnlyBridge(FakeCapitalSession()).authenticated is True
    assert CapitalReadOnlyBridge(FakeCapitalSession(tokens=None)).authenticated is False


def test_asking_whether_configured_does_not_open_a_session():
    """
    `configured` سؤالٌ عن الحال، وسؤالٌ لا يُغيّر ما يسأل عنه.

    لو أنشأ جلسةً لكان مجرّدُ فتح شاشةٍ في التطبيق يسجّل دخولاً إلى كابيتال.
    """
    session = FakeCapitalSession(tokens=None)
    assert CapitalReadOnlyBridge(session).authenticated is False
    assert session.ensured == 0


def test_bridge_reads_through_the_brokers_guarded_transport():
    session = FakeCapitalSession()
    response = CapitalReadOnlyBridge(session).get("/api/v1/prices/EURUSD")
    assert response.ok
    assert session.ensured == 1
    method, url = session.transport.sent[0]
    assert method == "GET"
    assert url.startswith(session.base_url)


def test_bridge_exposes_no_way_to_write():
    """
    لا يملك ميثوداً يرسل غير GET — لا لأنه مؤدَّب، بل لأنه لا يكتب غيرها.
    """
    bridge = CapitalReadOnlyBridge(FakeCapitalSession())
    for forbidden in ("post", "put", "patch", "delete", "place_order", "send"):
        assert not hasattr(bridge, forbidden), forbidden


# ---------------------------------------------------------------------------
# السجلّ
# ---------------------------------------------------------------------------
def test_market_data_is_wired_when_the_broker_has_a_session():
    """**هذا هو الفرع الذي انفجر على الخادم.**"""
    registry = build_provider_registry(
        secrets(), broker=BrokerWithSession(FakeCapitalSession())
    )
    assert ProviderKind.MARKET_DATA not in registry.missing()
    # ولا ينفجر عند الاستعلام — وهو ما فشل فعلاً.
    assert registry.as_display_dict()["providers"]


def test_market_data_is_missing_when_the_broker_has_no_session():
    registry = build_provider_registry(secrets(), broker=BrokerWithoutSession())
    assert ProviderKind.MARKET_DATA in registry.missing()
    assert registry.as_display_dict()["providers"]


def test_a_missing_key_leaves_the_provider_unconfigured_not_broken():
    """مفتاحٌ غائب ⇒ مزوّدٌ غير مُعدّ يظهر باسمه، لا مزوّدٌ يُخفق عند النداء."""
    registry = build_provider_registry(secrets(), broker=BrokerWithoutSession())
    missing = registry.missing()
    assert ProviderKind.ECONOMIC_CALENDAR in missing
    assert ProviderKind.VERIFIED_NEWS in missing


def test_macro_falls_back_to_ecb_which_needs_no_key():
    """
    البيانات الكلّية لا تبقى ناقصة لغياب مفتاح FRED: ECB عام بلا مفتاح.
    """
    registry = build_provider_registry(secrets(), broker=BrokerWithoutSession())
    assert ProviderKind.MACRO_DATA not in registry.missing()


def test_fred_is_preferred_when_its_key_exists():
    registry = build_provider_registry(
        secrets(FRED_API_KEY="k" * 32), broker=BrokerWithoutSession()
    )
    assert "fred" in registry.macro.name.lower()


@pytest.mark.parametrize("kind", list(ProviderKind))
def test_every_provider_answers_status_without_raising(kind):
    """
    العطل الذي وقع كان في `status()` لا في البناء. فيُفحص كل مزوّد على حدة:
    سؤالُه عن حاله يجب ألّا يرفع استثناءً مهما كانت إعداداته.
    """
    registry = build_provider_registry(
        secrets(FMP_API_KEY="a" * 32, FINNHUB_API_KEY="b" * 40, FRED_API_KEY="c" * 32),
        broker=BrokerWithSession(FakeCapitalSession()),
    )
    matching = [p for p in registry.all() if p.kind is kind]
    assert matching, f"لا مزوّد من نوع {kind}"
    for provider in matching:
        provider.status()


# ---------------------------------------------------------------------------
# مصدر الأسرار — واحدٌ للخدمة وللأدوات
# ---------------------------------------------------------------------------
def test_cli_and_service_read_the_same_secrets_file():
    """
    **حدث فعلاً على الخادم:** الواجهة تقول «المزوّدون مُعدّون، الأهلية true»،
    والمسبار في اللحظة نفسها يقول «FMP_API_KEY غير مُعدّ».

    السبب أن `cli.py` كان يثبّت `secrets/capital.env` بينما الخدمة تقرأ
    `secrets/runtime.env` — وهو ما يكتبه سكربت نقل الأسرار. ملفّان مختلفان
    لسرٍّ واحد، وكلاهما «صادق» في ما يراه.

    والثابت هنا ليس المسار بعينه بل **وحدته**: أداةٌ تقرأ غير ما تقرأ الخدمة
    تُنتج تشخيصاً يقود إلى الاتجاه الخطأ.
    """
    from app.cli import DEFAULT_SECRETS_FILE
    from app.config import get_settings

    assert str(DEFAULT_SECRETS_FILE) == get_settings().secrets_file


def test_secrets_path_is_not_hardcoded_in_the_cli():
    """فحصٌ على المصدر: تثبيتُ المسار هو ما أنتج الاختلاف، فلا يعود."""
    from pathlib import Path

    import app.cli as cli

    line = next(
        raw for raw in Path(cli.__file__).read_text(encoding="utf-8").splitlines()
        if raw.startswith("DEFAULT_SECRETS_FILE")
    )
    assert "capital.env" not in line
    assert "runtime.env" not in line
    assert "get_settings()" in line
