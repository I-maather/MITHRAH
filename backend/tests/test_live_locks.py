"""
أقفال التداول الحقيقي. هذه أهم اختبارات في المشروع من ناحية المال.
"""
from __future__ import annotations

import pytest

from app.brokers.factory import build_broker
from app.brokers.ibkr import IBKRLiveAdapter, IBKRPaperAdapter
from app.brokers.mock import MockBrokerAdapter
from app.config import Settings


def settings(**kw) -> Settings:
    base = dict(LIVE_TRADING=False, BROKER_MODE="MOCK", LIVE_APPROVAL_FILE="/nonexistent/approval.json")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_default_is_mock_and_live_is_off():
    s = settings()
    assert s.live_trading is False
    assert s.broker_mode == "MOCK"
    assert isinstance(build_broker(s), MockBrokerAdapter)


def test_paper_adapter_is_not_live():
    s = settings(BROKER_MODE="IBKR_PAPER")
    broker = build_broker(s)
    assert isinstance(broker, IBKRPaperAdapter)
    assert broker.is_live is False


def test_live_mode_without_live_flag_is_refused():
    with pytest.raises(RuntimeError, match="LIVE_TRADING=true"):
        build_broker(settings(BROKER_MODE="IBKR_LIVE"))


def test_live_mode_without_approval_file_is_refused():
    with pytest.raises(RuntimeError, match="ملف موافقة"):
        build_broker(settings(BROKER_MODE="IBKR_LIVE", LIVE_TRADING=True))


def test_live_mode_with_both_locks_returns_live_adapter(tmp_path):
    approval = tmp_path / "live_approval.json"
    approval.write_text('{"approved_by":"Maather","at":"2026-08-28T12:00:00Z"}', encoding="utf-8")
    broker = build_broker(
        settings(BROKER_MODE="IBKR_LIVE", LIVE_TRADING=True, LIVE_APPROVAL_FILE=str(approval))
    )
    assert isinstance(broker, IBKRLiveAdapter)
    assert broker.is_live is True


def test_ibkr_adapters_refuse_to_invent_data():
    """المحوّل غير المكتمل يرفع خطأً واضحاً بدل إرجاع أرقام وهمية."""
    broker = IBKRPaperAdapter(host="127.0.0.1", port=4002, client_id=1)
    assert broker.health_check() is False
    for method, args in (
        ("connect", ()), ("get_accounts", ()), ("get_balances", ("X",)),
        ("get_market_data", ("SPY",)), ("get_positions", ("X",)),
        ("get_trading_permissions", ("X",)),
    ):
        with pytest.raises(NotImplementedError):
            getattr(broker, method)(*args)


def test_pipeline_refuses_live_submission_without_explicit_flag():
    """
    حتى لو كان المحوّل حقيقياً، الـpipeline لا يرسل ما لم يُمرَّر
    allow_live_submission=True صراحةً.
    """
    from app.pipeline.runner import Pipeline

    p = Pipeline(
        broker=IBKRLiveAdapter(host="h", port=1, client_id=1), risk_engine=None,
        kill_switch=None, audit=None, execution=None, strategies=[],
        schedule=None, assumptions=None, blackouts=None,
    )
    assert p.allow_live_submission is False
