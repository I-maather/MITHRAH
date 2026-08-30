"""
`place_order` — المسار المفتوح.

كل ما قبل هذا الملف كان يختبر أن القفل **يمنع**. وهذا يختبر ما يحدث حين
يُفتح: البناء والإرسال والتأكيد والمطابقة. لم يُنفَّذ أيٌّ من هذه الأسطر في
اختبار قطّ، لأن القفل كان مغلقاً في كل مسار.

القاعدة الحاكمة: **استجابة الإرسال ليست إثبات تنفيذ.** `dealReference`
إيصال استلام؛ والدليل الوحيد `GET /confirms/{ref}` بحالة ACCEPTED، ثم
مطابقة ما نُفِّذ بما نويناه.
"""
from __future__ import annotations

import pytest

from app.brokers.base import BrokerRejected
from app.brokers.capital.endpoints import PATH_POSITIONS, confirm_path
from app.brokers.capital.errors import (
    CapitalExecutionUncertain,
    CapitalMarketClosed,
)
from app.brokers.capital.safety import ExecutionLock, ExecutionLocked
from app.brokers.capital.transport import ApiResponse
from app.clock import now_utc
from app.money import D
from app.brokers.capital import adapter as adapter_module
from app.brokers.capital.adapter import CapitalComAdapter
from tests.capital_fixtures import (
    build_adapter,
    build_session,
    build_transport,
    confirm_body,
    eurusd_market_body,
)
from tests.test_capital_execution_safety import an_intent

REF = "ref-abc-123"


def intent(**over):
    """نية بهدف صريح — `limit_price` سعر دخول لا هدف."""
    base = {"take_profit_price": D("1.09546")}
    base.update(over)
    return an_intent(**base)


def _prove_unit(monkeypatch):
    """
    يفتح حارس الوحدة صراحةً.

    وجوده في كل اختبار يمسّ المسار الكامل **مقصود**: لا يُفتح المسار إلا
    بفعلٍ مكتوب، فلو أُزيل الحارس يوماً سقطت هذه الاختبارات وأخبرتنا.
    """
    monkeypatch.setattr(adapter_module, "STOP_DISTANCE_UNIT_PROVEN", True)


def _unlocked() -> ExecutionLock:
    return ExecutionLock.locked().authorise(
        owner_authorization_reference="APPROVAL-TEST-1",
        reason_ar="اختبار المسار المفتوح بموافقة موثقة",
        at=now_utc(),
    )


def _adapter(transport=None, *, market=None):
    """
    القفل نفسه في الطبقتين: المحوّل والناقل المحروس.

    فتحُ إحداهما دون الأخرى يُنتج اختباراً كاذباً — إمّا يمرّ ما يجب أن يُمنع،
    أو يُمنع ما نريد اختباره. والطبقتان مقصودتان في التصميم.
    """
    lock = _unlocked()
    transport = transport or build_transport(markets={"EURUSD": market or eurusd_market_body()})
    session, _guarded, fixture = build_session(transport, lock=lock)
    adapter = CapitalComAdapter(session=session, execution_lock=lock)
    adapter.connect()
    return adapter, fixture


def _with_units(adapter, *, pip_size=D("0.0001"), min_stop=D("10")):
    """يحقن وحدة مُثبَتة كي تُختبَر الأسطر التي بعد الحارس."""
    real = adapter.get_instrument_details
    adapter.get_instrument_details = lambda symbol: real(symbol).model_copy(  # type: ignore[method-assign]
        update={"pip_size": pip_size, "min_stop_distance": min_stop}
    )
    return adapter


def _posts(fixture) -> int:
    return len([c for c in fixture.calls if c["method"] == "POST" and c["path"] == PATH_POSITIONS])


# --- ما يُرفَض قبل أن تغادر أي حزمة -----------------------------------------

def test_locked_adapter_still_blocks_and_sends_nothing():
    adapter, _g, fixture = build_adapter()
    adapter.connect()
    before = len(fixture.calls)
    with pytest.raises(ExecutionLocked):
        adapter.place_order(an_intent())
    assert len(fixture.calls) == before


def test_unproven_stop_unit_refuses_and_sends_nothing():
    """
    الوسيط لا يعيد `pip_size`، و«POINTS» تُقرأ فرقَ سعر للذهب وتستحيل
    للعملات. الوحدة غير مُثبَتة ⇒ لا إرسال. هذه هي حالة رسم التبييت نفسها.
    """
    adapter, fixture = _adapter()
    with pytest.raises(BrokerRejected) as exc:
        adapter.place_order(intent())
    assert "STOP_DISTANCE_UNIT_UNKNOWN" in str(exc.value)
    assert _posts(fixture) == 0


def test_intent_without_a_stop_is_refused_before_any_send(monkeypatch):
    _prove_unit(monkeypatch)
    adapter, fixture = _adapter()
    _with_units(adapter)
    with pytest.raises(BrokerRejected):
        adapter.place_order(intent(stop_price=None))
    assert _posts(fixture) == 0


def test_quantity_below_broker_minimum_is_refused_before_any_send(monkeypatch):
    _prove_unit(monkeypatch)
    adapter, fixture = _adapter()
    _with_units(adapter)
    with pytest.raises(BrokerRejected):
        adapter.place_order(intent(quantity=D("50")))
    assert _posts(fixture) == 0


def test_closed_market_is_refused_before_any_send():
    adapter, fixture = _adapter(market=eurusd_market_body(status="CLOSED"))
    with pytest.raises(CapitalMarketClosed):
        adapter.place_order(intent())
    assert _posts(fixture) == 0


def test_stop_closer_than_broker_minimum_is_refused_and_never_widened(monkeypatch):
    """التوسيع التلقائي يغيّر المخاطرة التي وُوفق عليها — فيُرفَض بدله."""
    _prove_unit(monkeypatch)
    adapter, fixture = _adapter()
    _with_units(adapter, min_stop=D("400"))   # 400 نقطة > 50 المطلوبة
    with pytest.raises(BrokerRejected) as exc:
        adapter.place_order(intent())
    assert "لا تُوسَّع" in str(exc.value)
    assert _posts(fixture) == 0


# --- المسار الكامل ----------------------------------------------------------

def _submitting(monkeypatch, confirm=None, *, deal_status="ACCEPTED"):
    body = confirm if confirm is not None else confirm_body(deal_status=deal_status)
    transport = build_transport(confirms={REF: body})
    transport.register_json("POST", PATH_POSITIONS, {"dealReference": REF})
    _prove_unit(monkeypatch)
    adapter, fixture = _adapter(transport)
    return _with_units(adapter), fixture


def test_fill_is_proven_by_confirmation_not_by_the_submission_response(monkeypatch):
    adapter, fixture = _submitting(monkeypatch)
    order = adapter.place_order(intent())
    assert order.status.value == "FILLED"
    assert order.broker_order_id == "deal-abc-123"
    assert order.filled_quantity == D("100")
    assert _posts(fixture) == 1


def test_rejected_confirmation_returns_rejected_and_zero_filled(monkeypatch):
    adapter, _f = _submitting(monkeypatch, deal_status="REJECTED")
    order = adapter.place_order(intent())
    assert order.status.value == "REJECTED"
    assert order.filled_quantity == D("0")


def test_unresolved_confirmation_is_uncertain_and_the_order_is_never_resent(monkeypatch):
    """«أُرسل ولم يُحسم» أخطر من الرفض — ولا يُعالَج بإعادة الإرسال."""
    transport = build_transport()
    transport.register_json("POST", PATH_POSITIONS, {"dealReference": REF})
    transport.register_json("GET", confirm_path(REF), {}, status=404)
    _prove_unit(monkeypatch)
    adapter, fixture = _adapter(transport)
    _with_units(adapter)
    with pytest.raises(CapitalExecutionUncertain):
        adapter.place_order(intent())
    assert _posts(fixture) == 1, "أُرسل مرة واحدة ولم يُعَد"


def test_submission_without_a_deal_reference_is_malformed_not_success(monkeypatch):
    transport = build_transport()
    transport.register_json("POST", PATH_POSITIONS, {"ok": True})
    _prove_unit(monkeypatch)
    adapter, _f = _adapter(transport)
    _with_units(adapter)
    with pytest.raises(Exception) as exc:
        adapter.place_order(intent())
    assert "dealReference" in str(exc.value)


# --- المطابقة: ما نُفِّذ يجب أن يكون ما نويناه -------------------------------

def test_a_different_size_than_intended_is_refused(monkeypatch):
    body = confirm_body(); body["size"] = 200
    adapter, _f = _submitting(monkeypatch, body)
    with pytest.raises(BrokerRejected) as exc:
        adapter.place_order(intent())
    assert "كمية مختلفة" in str(exc.value)


def test_a_different_direction_than_intended_is_refused(monkeypatch):
    body = confirm_body(); body["direction"] = "SELL"
    adapter, _f = _submitting(monkeypatch, body)
    with pytest.raises(BrokerRejected) as exc:
        adapter.place_order(intent())
    assert "اتجاه مختلف" in str(exc.value)


def test_a_different_instrument_than_intended_is_refused(monkeypatch):
    body = confirm_body(); body["epic"] = "GBPUSD"
    adapter, _f = _submitting(monkeypatch, body)
    with pytest.raises(BrokerRejected) as exc:
        adapter.place_order(intent())
    assert "أداة مختلفة" in str(exc.value)


def test_intent_without_a_take_profit_is_refused(monkeypatch):
    """الهدف حقلٌ مستقلّ — `limit_price` سعر دخول، وخلطهما كان عيباً حقيقياً."""
    _prove_unit(monkeypatch)
    adapter, fixture = _adapter()
    _with_units(adapter)
    with pytest.raises(BrokerRejected) as exc:
        adapter.place_order(intent(take_profit_price=None))
    assert "بلا هدف" in str(exc.value)
    assert _posts(fixture) == 0
