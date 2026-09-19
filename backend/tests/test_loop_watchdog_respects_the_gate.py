"""
الحارسُ يُعيد التشغيل حين تموت الحلقة، **ولا يُعيده لأنّ البوابة مقفلة**.

هذه هي القاعدة التي كلّف غيابُها أربعةَ أيام: `healthy: false` كانت تُقرأ
«ميت» وهي تقولها عن حالتين. والاختبارُ الحاسم هنا `LOCKED_BY_GATE`.
"""
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "ops" / "mathrah_loop_watch.py"


@pytest.fixture(scope="module")
def watchdog():
    if not _PATH.exists():
        pytest.skip(f"الحارس غير موجود: {_PATH}")
    spec = importlib.util.spec_from_file_location("mathrah_loop_watch", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _health(state=None, age=30, verdict="READY_TRADING_STILL_LOCKED"):
    body = {"decision_loop": {"age_seconds": age}}
    if state is not None:
        body["state"] = state
        body["startup"] = {"verdict": verdict}
    return body


def test_an_unreachable_api_is_not_healthy(watchdog):
    assert watchdog.loop_is_alive(None)[0] is False


def test_running_is_alive(watchdog):
    assert watchdog.loop_is_alive(_health("RUNNING"))[0] is True


def test_awaiting_the_owner_is_alive_not_a_reason_to_restart(watchdog):
    assert watchdog.loop_is_alive(_health("AWAITING_OWNER"))[0] is True


def test_a_shut_gate_is_alive_too_because_restarting_does_not_open_it(watchdog):
    alive, _ = watchdog.loop_is_alive(
        _health("LOCKED_BY_GATE", verdict="LOCKED_PENDING_RECONCILIATION")
    )
    assert alive is True


def test_only_a_dead_loop_warrants_a_restart_and_names_the_verdict(watchdog):
    alive, reason = watchdog.loop_is_alive(
        _health("DEAD_LOOP", age=302390, verdict="LOCKED_PENDING_RECONCILIATION")
    )
    assert alive is False
    assert "LOCKED_PENDING_RECONCILIATION" in reason


def test_an_older_server_without_the_state_field_falls_back_to_the_heartbeat(watchdog):
    assert watchdog.loop_is_alive(_health(None, age=30))[0] is True
    assert watchdog.loop_is_alive(_health(None, age=302390))[0] is False
    assert watchdog.loop_is_alive(_health(None, age=None))[0] is False
