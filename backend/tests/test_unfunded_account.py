"""
اختبارات الحساب غير المموَّل — حالة صحيحة لا انهيار.

الخلل الذي تعالجه هذه الاختبارات: الاكتشاف نجح بالكامل (HTTP 200 على كل
الطلبات) ثم انهار الأمر عند حساب الجدوى لأن الرصيد الفعلي غير موجب، فضاع
الاكتشاف كله بسبب حالة حساب مشروعة تماماً.

**لا شبكة · لا Keychain · لا اعتماد حقيقي.** كل قيمة هنا وهمية ومكتوبة صراحةً.
"""
from __future__ import annotations

import os
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from app.live_readonly.private_store import (
    ACTUAL_FEASIBILITY_MARKDOWN,
    PrivateStoreError,
    private_directory,
    write_private_text,
    write_public_text,
)
from app.live_readonly.report import (
    ACCOUNT_FUNDED,
    ACCOUNT_NOT_FUNDED,
    PLANNED_CAPITAL_USD,
    assess_equity,
    compute_feasibility,
    render_actual_feasibility_markdown,
    render_public_feasibility_markdown,
)
from app.money import D
from app.profiles import ProfileLimits, TradingProfile

from tests.test_private_store import make_repo

POSIX = os.name == "posix"

PUBLIC_REPORT_RELATIVE = Path("docs") / "CAPITAL_COM_150_USD_FEASIBILITY.md"

#: قيم الحساب الوهمية في التجهيزة — تُستعمل للتأكد أنها لا تتسرّب.
FIXTURE_BALANCE = "212.34"
FIXTURE_AVAILABLE = "210.00"
FIXTURE_PROFIT_LOSS = "-2.34"


def routes_with_balance(balance_block):
    """
    مسارات كاملة مع كتلة رصيد مخصّصة. `balance_block` قد تكون `None` كي تغيب
    الكتلة أصلاً — وهي حالة «الرصيد مفقود».
    """
    from tests.test_live_readonly import (
        FAKE_ACCOUNT_ID, LiveResponse, full_routes, rsa_key_b64,
    )

    account = {
        "accountId": FAKE_ACCOUNT_ID, "accountName": "Main", "preferred": True,
        "accountType": "CFD", "currency": "USD", "status": "ENABLED",
    }
    if balance_block is not None:
        account["balance"] = balance_block

    routes = full_routes(rsa_key_b64())
    routes[("GET", "/api/v1/accounts")] = LiveResponse(200, {}, {"accounts": [account]})
    return routes


def discovery_with_balance(balance_block):
    from tests.test_live_readonly import MockLiveTransport, secrets
    from app.live_readonly.discovery import run_live_discovery
    from app.live_readonly.session import LiveSession

    transport = MockLiveTransport(routes_with_balance(balance_block))
    session = LiveSession(transport=transport, secrets=secrets())
    session.authenticate()
    try:
        return run_live_discovery(session), transport
    finally:
        session.discard()


# ---------------------------------------------------------------------------
# 1. تصنيف الرصيد — بلا اختلاق أي قيمة
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, reason",
    [
        (D("0"), "ZERO"),
        (D("0.00"), "ZERO"),
        (0, "ZERO"),
        ("0", "ZERO"),
        (D("-1"), "NEGATIVE"),
        (D("-0.01"), "NEGATIVE"),
        (-250, "NEGATIVE"),
        (None, "MISSING"),
        ("", "MALFORMED"),
        ("abc", "MALFORMED"),
        ("١٢٣ ريال", "MALFORMED"),
        (True, "MALFORMED"),
        ("NaN", "MALFORMED"),
        ("Infinity", "MALFORMED"),
        ("-Infinity", "MALFORMED"),
        (float("nan"), "MALFORMED"),
        (float("inf"), "MALFORMED"),
    ],
)
def test_non_positive_or_invalid_equity_is_classified_not_funded(raw, reason):
    assessment = assess_equity(raw)
    assert assessment.status == ACCOUNT_NOT_FUNDED
    assert assessment.reason_code == reason
    assert assessment.usable is False
    # **لا رقم بديل.** الغياب يبقى غياباً.
    assert assessment.equity is None


@pytest.mark.parametrize("raw", [D("0.01"), D("150"), "212.34", 212.34, 1])
def test_positive_equity_is_funded_and_carries_the_value(raw):
    assessment = assess_equity(raw)
    assert assessment.status == ACCOUNT_FUNDED
    assert assessment.usable is True
    assert assessment.equity is not None and assessment.equity > 0


def test_nan_breaks_a_naive_positive_check_rather_than_failing_safely():
    """
    توثيق للسلوك الفعلي: المقارنة المرتّبة مع `NaN` **ترفع**
    `InvalidOperation`، والمساواة تعيد False بلا رفع. فالفحص الساذج
    `equity <= 0` لا يردّ القيمة بل ينهار بها — عطلٌ آخر بدل الأول.
    لذلك يُفحص `is_finite()` **قبل** أي مقارنة.
    """
    from decimal import InvalidOperation

    nan = Decimal("NaN")
    with pytest.raises(InvalidOperation):
        _ = nan <= 0
    assert (nan == 0) is False

    assert assess_equity(nan).status == ACCOUNT_NOT_FUNDED
    assert nan.is_finite() is False


# ---------------------------------------------------------------------------
# 2. لا استدعاء لـ ProfileLimits بحقوق ملكية غير موجبة
# ---------------------------------------------------------------------------

def test_profile_limits_still_rejects_non_positive_equity():
    """الرفض في محلّه ولم يُضعَّف — الإصلاح في المستدعي لا في الحدّ."""
    for bad in (D("0"), D("-1")):
        with pytest.raises(ValueError):
            ProfileLimits.for_profile(TradingProfile.BALANCED, bad)


@pytest.mark.parametrize("bad", [D("0"), D("-5"), Decimal("NaN"), None])
def test_compute_feasibility_returns_none_instead_of_reaching_profile_limits(
    bad, monkeypatch
):
    """
    خطّ الدفاع الثاني: حتى لو مرّر مستدعٍ قيمة غير صالحة، لا تصل إلى
    `ProfileLimits.for_profile` ولا يُرفَع استثناء.
    """
    from app.live_readonly import report as report_module

    def explode(*_a, **_k):
        raise AssertionError("لا يجوز بلوغ ProfileLimits بحقوق ملكية غير صالحة.")

    monkeypatch.setattr(report_module.ProfileLimits, "for_profile", staticmethod(explode))

    discovery, _ = discovery_with_balance({"balance": 0, "available": 0})
    eurusd = discovery.instrument("EURUSD")
    assert eurusd is not None and eurusd.found
    assert compute_feasibility(eurusd, equity=bad) is None


# ---------------------------------------------------------------------------
# 3. الاكتشاف نفسه ينجح على حساب غير مموَّل
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "balance_block",
    [
        {"balance": 0, "available": 0, "profitLoss": 0},
        {"balance": -12.5, "available": -12.5, "profitLoss": -12.5},
        {"available": 0},                       # الرصيد مفقود
        {"balance": "غير متاح", "available": 0},  # مشوَّه
        None,                                    # كتلة الرصيد كلها غائبة
    ],
)
def test_discovery_completes_on_an_unfunded_account(balance_block):
    discovery, transport = discovery_with_balance(balance_block)

    assert discovery.account is not None
    assert discovery.account.currency == "USD"
    assert all(i.found for i in discovery.instruments)
    assert tuple(discovery.errors) == ()

    assert assess_equity(discovery.account.balance).status == ACCOUNT_NOT_FUNDED

    # ولم يخرج أي طلب عن القائمة البيضاء للقراءة.
    methods = {method for method, _ in transport.sent}
    assert methods <= {"GET", "POST"}
    assert [op for op in transport.sent if op[0] == "POST"] == [
        ("POST", "/api/v1/session")
    ]


# ---------------------------------------------------------------------------
# 4. التقارير — الخاص يصرّح بالحالة، والعام يُولَّد دائماً
# ---------------------------------------------------------------------------

def test_private_actual_report_states_not_funded_without_sizing():
    discovery, _ = discovery_with_balance({"balance": 0, "available": 0})
    assessment = assess_equity(discovery.account.balance)

    text = render_actual_feasibility_markdown(
        discovery, actual=None, assessment=assessment
    )
    assert ACCOUNT_NOT_FUNDED in text
    assert "تحجيم المراكز" in text
    assert "غير متاح" in text
    assert "NO-GO" in text
    assert "ليس عطلاً" in text
    # لا جدول تحجيم مُختلَق
    assert "| الكمية |" not in text


def test_public_planned_report_is_still_generated_when_unfunded():
    discovery, _ = discovery_with_balance({"balance": 0, "available": 0})
    eurusd = discovery.instrument("EURUSD")

    planned = compute_feasibility(eurusd, equity=PLANNED_CAPITAL_USD)
    assert planned is not None, "سيناريو 150 لا يعتمد على رصيد الحساب إطلاقاً."
    assert planned["equity_used"] == "150.00"

    public = render_public_feasibility_markdown(planned=planned)
    assert "150.00" in public
    assert "| الكمية |" in public          # الجدول كامل
    assert ACCOUNT_NOT_FUNDED not in public  # حالة الحساب لا تُذكر في العام
    assert FIXTURE_BALANCE not in public


def test_planned_report_is_identical_whether_or_not_the_account_is_funded():
    """
    سيناريو 150 دولاراً مبنيّ على شروط الأداة وحدها. لو تغيّر بتغيّر الرصيد
    لكان يتسرّب منه شيء عن الحساب.
    """
    funded, _ = discovery_with_balance({"balance": 212.34, "available": 210.00})
    unfunded, _ = discovery_with_balance({"balance": 0, "available": 0})

    a = render_public_feasibility_markdown(
        planned=compute_feasibility(funded.instrument("EURUSD"), equity=PLANNED_CAPITAL_USD)
    )
    b = render_public_feasibility_markdown(
        planned=compute_feasibility(unfunded.instrument("EURUSD"), equity=PLANNED_CAPITAL_USD)
    )
    assert a == b


# ---------------------------------------------------------------------------
# 5. الأمر كاملاً على حساب غير مموَّل
# ---------------------------------------------------------------------------

def run_cli_with_balance(monkeypatch, tmp_path, balance_block):
    import app.cli as cli
    from tests.test_live_readonly import MockLiveTransport, secrets
    from app.live_readonly.session import LiveSession

    repo = make_repo(tmp_path)
    (repo / "docs").mkdir()
    monkeypatch.setattr(cli, "REPO_ROOT", repo)
    monkeypatch.setattr(cli, "build_secret_provider", lambda **_: secrets())

    transport = MockLiveTransport(routes_with_balance(balance_block))
    monkeypatch.setattr(cli, "LiveReadOnlyTransport", lambda *a, **k: transport)
    monkeypatch.setattr(
        cli, "LiveSession",
        lambda **kw: LiveSession(transport=transport, secrets=kw["secrets"]),
    )

    args = cli.build_parser().parse_args(
        ["capital-live-discover", "--acknowledge-live-read-only"]
    )
    return cli.cmd_capital_live_discover(args), repo, transport


@pytest.mark.parametrize(
    "balance_block",
    [
        {"balance": 0, "available": 0, "profitLoss": 0},
        {"balance": -3.5, "available": -3.5},
        {"available": 0},
        {"balance": "NaN", "available": 0},
        None,
    ],
)
def test_cli_does_not_crash_on_an_unfunded_account(
    balance_block, monkeypatch, capsys, tmp_path
):
    code, repo, _ = run_cli_with_balance(monkeypatch, tmp_path, balance_block)
    out = capsys.readouterr()
    combined = out.out + out.err

    # الاكتشاف اكتمل ⇒ رمز الخروج صفر رغم أن الجدوى الفعلية NO-GO.
    assert code == 0, combined
    assert "المصادقة: ✅ نجحت" in combined
    assert "عملة الحساب: USD" in combined
    assert ACCOUNT_NOT_FUNDED in combined
    assert "NO-GO" in combined
    assert "Traceback" not in combined
    assert "حقوق الملكية يجب أن تكون موجبة" not in combined

    # التقارير الثلاثة الخاصة والتقرير العام مكتوبة كلها.
    private = private_directory(repo)
    assert (private / ACTUAL_FEASIBILITY_MARKDOWN).exists()
    assert (repo / PUBLIC_REPORT_RELATIVE).exists()

    public_text = (repo / PUBLIC_REPORT_RELATIVE).read_text(encoding="utf-8")
    assert "150.00" in public_text
    assert "| الكمية |" in public_text


def test_cli_prints_no_account_value_when_unfunded(monkeypatch, capsys, tmp_path):
    """لا رصيد ولا متاح ولا ربح/خسارة ولا معرّف حساب — ولو كانت القيم صفراً."""
    from tests.test_live_readonly import FAKE_ACCOUNT_ID

    code, _, _ = run_cli_with_balance(
        monkeypatch, tmp_path,
        {"balance": -18.75, "available": -18.75, "profitLoss": -18.75},
    )
    out = capsys.readouterr()
    combined = out.out + out.err

    assert code == 0
    for forbidden in ("-18.75", "18.75", FAKE_ACCOUNT_ID, "****6655"):
        assert forbidden not in combined, f"تسرّب إلى الطرفية: {forbidden}"


def test_unfunded_run_sends_only_whitelisted_read_requests(monkeypatch, tmp_path):
    code, _, transport = run_cli_with_balance(
        monkeypatch, tmp_path, {"balance": 0, "available": 0}
    )
    assert code == 0

    from app.live_readonly.allowlist import assert_allowed, LIVE_BASE_URL

    posts = [op for op in transport.sent if op[0] != "GET"]
    assert posts == [("POST", "/api/v1/session")], posts
    for method, path in transport.sent:
        assert_allowed(method, LIVE_BASE_URL + path)   # لا يرفع ⇒ مسموح


# ---------------------------------------------------------------------------
# 6. لا تقارير مبتورة بعد استثناء
# ---------------------------------------------------------------------------

def test_no_partial_private_report_when_rendering_fails(monkeypatch, tmp_path):
    """
    المحتوى القديم يبقى كاملاً، ولا يبقى ملف مؤقت. الكتابة الذرّية تعني:
    القديم كاملاً أو الجديد كاملاً — لا ثالث.
    """
    from app.live_readonly import private_store

    repo = make_repo(tmp_path)
    private_store.ensure_private_directory(repo)
    write_private_text(repo, ACTUAL_FEASIBILITY_MARKDOWN, "المحتوى الأصلي الكامل")

    original = private_store._atomic_write_text

    def fail_midway(path, text, *, mode):
        raise RuntimeError("انقطاع أثناء التوليد")

    monkeypatch.setattr(private_store, "_atomic_write_text", fail_midway)
    with pytest.raises(RuntimeError):
        write_private_text(repo, ACTUAL_FEASIBILITY_MARKDOWN, "محتوى جديد")

    monkeypatch.setattr(private_store, "_atomic_write_text", original)
    target = private_directory(repo) / ACTUAL_FEASIBILITY_MARKDOWN
    assert target.read_text(encoding="utf-8") == "المحتوى الأصلي الكامل"
    assert list(private_directory(repo).glob(".*tmp*")) == []


def test_atomic_write_leaves_no_temporary_file_when_writing_fails(tmp_path):
    from app.live_readonly import private_store

    repo = make_repo(tmp_path)
    private_store.ensure_private_directory(repo)
    target = private_directory(repo) / ACTUAL_FEASIBILITY_MARKDOWN

    class Exploding(str):
        pass

    # نص يفجّر أثناء الكتابة نفسها، بعد فتح الملف المؤقت.
    class Boom:
        def __str__(self):  # pragma: no cover - غير مستعمل
            raise RuntimeError

    with pytest.raises(TypeError):
        private_store._atomic_write_text(target, Boom(), mode=0o600)

    assert not target.exists()
    assert list(private_directory(repo).iterdir()) == []


def test_public_write_is_atomic_and_keeps_the_previous_version(tmp_path):
    from app.live_readonly import private_store

    repo = make_repo(tmp_path)
    target = repo / PUBLIC_REPORT_RELATIVE
    write_public_text(target, "النسخة الأولى")
    assert target.read_text(encoding="utf-8") == "النسخة الأولى"

    write_public_text(target, "النسخة الثانية")
    assert target.read_text(encoding="utf-8") == "النسخة الثانية"
    assert list(target.parent.glob(".*tmp*")) == []


@pytest.mark.skipif(not POSIX, reason="الصلاحيات على POSIX.")
def test_atomic_private_write_keeps_600(tmp_path):
    from app.live_readonly import private_store
    import stat as stat_module

    repo = make_repo(tmp_path)
    private_store.ensure_private_directory(repo)
    path = write_private_text(repo, ACTUAL_FEASIBILITY_MARKDOWN, "محتوى")
    mode = stat_module.S_IMODE(path.lstat().st_mode)
    assert mode & 0o077 == 0
    assert mode == 0o600


# ---------------------------------------------------------------------------
# 7. لا تسرّب إلى الشجرة المتتبَّعة
# ---------------------------------------------------------------------------

def test_unfunded_run_writes_no_account_value_under_docs(monkeypatch, tmp_path):
    code, repo, _ = run_cli_with_balance(
        monkeypatch, tmp_path, {"balance": -7.25, "available": -7.25}
    )
    assert code == 0
    for path in (repo / "docs").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "-7.25" not in text
            assert "7.25" not in text
            assert "****6655" not in text
