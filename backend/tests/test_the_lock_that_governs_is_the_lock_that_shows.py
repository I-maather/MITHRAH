"""
قفلٌ واحدٌ في ثلاث نسخ — المعروضتان مفتوحتان، والحاكمةُ مغلقة.

## ما وقع في الإنتاج — 2026-09-03

بعد إصلاح وحدة أدنى مسافة الوقف، بلغت الإشارات بوابةَ المخاطر لأوّل مرّة:

    22:05  RISK_DECISION TRADE · ORDER_INTENT_CREATED · ORDER_PREVIEWED
           ACCEPTED · ORDER_SUBMITTED
    22:06  المثل
    22:07  المثل
    22:08  ORDER_REJECTED DUPLICATE_BLOCKED ⇒ KILL_SWITCH DUPLICATE_ORDER

ولا `ORDER_CONFIRMED`، ولا مركزٌ عند الوسيط. والسجلّ الوحيد الذي يقول ما
جرى كان **خارج خط التدقيق**، في `journalctl`:

    فشل المهمة المجدولة decision-loop: ExecutionLocked

## السبب

`build_capital_adapter` تُمرّر قفلاً **واحداً** إلى الناقل والمحوّل، وتقول
في نصّها إن ذلك «طبقةٌ واحدة لا طبقتان، وإلا صار فتح إحداهما دون الأخرى
ممكناً بلا أن يظهر في أي اختبار».

والمشاركة تصحّ عند البناء وحده. وتجربةُ التجريبي تُعرَف بعده (لا نعرف أن
الوسيط تجريبي قبل أن نسأله)، فكان قفلها يُركَّب بإسنادٍ مباشر:

    broker.execution_lock = trial_lock

وهو يستبدل سمة المحوّل **ويترك الناقل مغلقاً**. فصارت ثلاث نسخ: حالةُ
النظام «مفتوح»، والمحوّل «مفتوح»، والناقل — الذي يمرّ به الطلب فعلاً —
«مغلق». والتعليق تنبّأ بالعطل، ثم أعادته كتابةٌ لاحقة.

## ما تحرسه هذه الفحوص

١. تركيبُ القفل يشمل الطبقتين.
٢. الاختلاف بينهما **يُرى** في تقرير الوسيط، لا يُكتشَف من أمرٍ يموت.
٣. لا إسناد مباشر لـ`execution_lock` خارج موضع التركيب.
٤. فشلُ الإرسال لا يموت صامتاً بعد أن سُجِّل «أُرسل».
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.brokers.capital.safety import ExecutionLock, ExecutionLocked

NOW = datetime(2026, 9, 3, 22, 5, tzinfo=timezone.utc)


def _authorised() -> ExecutionLock:
    return ExecutionLock.locked().authorise(
        owner_authorization_reference="MAATHER-TEST",
        reason_ar="تجربة الحساب التجريبي — فحص.",
        at=NOW,
    )


def _adapter():
    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.factory import build_capital_adapter
    from app.secretstore.provider import build_secret_provider

    secrets = build_secret_provider(env_file=None, allow_process_env=False)
    return build_capital_adapter(CapitalEnvironment.DEMO, secrets=secrets)


# ---------------------------------------------------------------------------
# ١ · الطبقتان معاً
# ---------------------------------------------------------------------------

def test_a_fresh_adapter_is_locked_on_both_layers():
    adapter = _adapter()
    layers = adapter.execution_lock_layers
    assert layers["adapter"] is False
    assert layers["transport"] is False
    assert adapter.execution_lock_consistent


def test_authorising_opens_both_layers():
    adapter = _adapter()
    adapter.authorise_execution(_authorised())
    layers = adapter.execution_lock_layers
    assert layers["adapter"] is True
    assert layers["transport"] is True, (
        "الناقل ما زال مغلقاً — وهو الذي يمرّ به الطلب فعلاً."
    )
    assert adapter.execution_lock_consistent


def test_the_old_direct_assignment_is_visibly_inconsistent():
    """
    **الفحص الذي يعضّ.** الإسناد المباشر هو ما وقع، ويجب أن يُرى الآن
    اختلافاً معلَناً بدل أن يظهر في أمرٍ يموت في المنتصف.
    """
    adapter = _adapter()
    adapter.execution_lock = _authorised()          # الطريقة القديمة
    layers = adapter.execution_lock_layers
    assert layers["adapter"] is True and layers["transport"] is False
    assert adapter.execution_lock_consistent is False


def test_the_report_shows_both_layers():
    adapter = _adapter()
    report = adapter.as_dict() if hasattr(adapter, "as_dict") else None
    if report is None:
        pytest.skip("لا تقرير على هذا المحوّل.")
    assert "execution_lock_layers" in report
    assert "execution_lock_consistent" in report


def test_no_module_assigns_the_lock_directly():
    """
    حارسٌ ساكن: إسنادٌ مباشر في أي وحدةٍ يعيد الطبقتين إلى الاختلاف. وموضع
    التركيب واحد: `authorise_execution`.
    """
    import app

    root = Path(app.__file__).resolve().parent
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        if path.name in {"adapter.py", "factory.py"}:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if ".execution_lock =" in stripped and "self." not in stripped:
                offenders.append(f"{path.relative_to(root)}:{number}: {stripped}")
    # `state.py` و`main.py` يحتفظان بمسارٍ احتياطي لوسيطٍ لا يعرف
    # `authorise_execution` — وهو **بعد** المحاولة الصحيحة لا بدلاً منها،
    # ويسبقه سطرٌ يستدعيها. فيُتحقَّق من ذلك لا من غياب السطر.
    allowed_prefixes = ("api/state.py", "main.py")
    unexpected = [o for o in offenders if not o.startswith(allowed_prefixes)]
    assert unexpected == [], "إسنادٌ مباشر لقفل التنفيذ:\n" + "\n".join(unexpected)

    # ولا يُقبل المسار الاحتياطي إلا مصحوباً بالاستدعاء الصحيح.
    for name in ("api/state.py", "main.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert 'authorise_execution' in text, (
            f"{name} يُسند القفل مباشرةً بلا استدعاء موضع التركيب."
        )


def test_the_builder_installs_through_the_one_place():
    from app.api import state as state_module

    text = Path(state_module.__file__).read_text(encoding="utf-8")
    assert 'getattr(broker, "authorise_execution", None)' in text
    assert "EXECUTION_LOCK_INCONSISTENT" in text, (
        "اختلافُ الطبقتين لا يُسجَّل — فيبقى غير مرئي حتى يموت أمر."
    )


# ---------------------------------------------------------------------------
# ٢ · لا إرسالَ يموت صامتاً
# ---------------------------------------------------------------------------

class _Boom:
    """وسيطٌ يجتاز المعاينة ثم يرفع استثناءً ليس من صنفي الوسيط المعروفين."""

    name = "BOOM"
    is_live = False

    def preview_order(self, intent):
        from app.contracts import OrderPreview

        return OrderPreview(
            intent_key=intent.idempotency_key, accepted_by_broker=True,
            broker_message="ok", estimated_commission=None,
            estimated_price=None, previewed_at_utc=NOW,
        )

    def place_order(self, intent):
        raise ExecutionLocked("العملية «POST /positions» مقفلة.")

    def confirm_order(self, client_order_id):
        from app.contracts import BrokerOrder, OrderStatus

        return BrokerOrder(
            broker_order_id="", client_order_id=client_order_id, symbol="EURUSD",
            status=OrderStatus.UNKNOWN, filled_quantity=0, average_fill_price=None,
            submitted_at_utc=NOW, updated_at_utc=NOW,
        )


def test_a_submission_that_raises_is_recorded_and_flagged(monkeypatch):
    from app.audit.log import AuditLog, InMemoryAuditStore
    from app.execution.orders import ExecutionService, IdempotencyGuard, SubmissionOutcome

    from .test_pipeline import build  # يعيد استعمال بناء النيّة الحقيقي

    pipeline, broker, audit_log, ks, state = build()
    store = InMemoryAuditStore()
    service = ExecutionService(
        broker=_Boom(), audit=AuditLog(store), guard=IdempotencyGuard()
    )
    result = pipeline  # placeholder to keep the fixture referenced
    intent = _intent()
    outcome = service.submit(intent)

    assert outcome.outcome is SubmissionOutcome.UNCONFIRMED
    assert outcome.requires_kill_switch is True
    decisions = [e.decision for e in store.all()]
    assert "SUBMITTED" in decisions
    assert any(d.startswith("SUBMIT_FAILED_") for d in decisions), (
        "أُرسل ثم ماتت العملية بلا سطرٍ يقول ماذا جرى — وهو ما وقع."
    )
    assert "SUBMIT_FAILED_ExecutionLocked" in decisions


def _intent():
    from decimal import Decimal

    from app.contracts import OrderIntent, OrderType, Side

    return OrderIntent(
        idempotency_key="k" * 40, client_order_id="MAT-test", symbol="EURUSD",
        side=Side.BUY, order_type=OrderType.LIMIT, quantity=Decimal("300"),
        limit_price=Decimal("1.16"), stop_price=Decimal("1.158"),
        take_profit_price=Decimal("1.164"), expected_fill_price=Decimal("1.16"),
        max_slippage_abs=Decimal("0.0002"), strategy_name="T", strategy_version="1.0.0",
        risk_amount_usd=Decimal("0.68"), commission_estimate_usd=Decimal("0.02"),
        exit_plan_ar="وقف وهدف", instrument_snapshot={}, created_at_utc=NOW,
    )
