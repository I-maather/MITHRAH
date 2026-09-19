"""
`healthy: false` كانت تُقال عن حالتين لا تشتركان في شيء.

هذه الاختبارات تُثبّت التمييز، وأحدُها هو حادثةُ ١٥–١٩ سبتمبر بأرقامها:
حلقةٌ عمرُها ٣٠٢٣٩٠ ثانية وبوابةٌ مقفلة — تُقرأ «الحلقة ميتة» لا «مقفل»،
لأنّ موتَ الحلقة أسوأُ من القفل فيُقال أوّلاً.
"""
from app.main import _machine_state

READY = "READY_TRADING_STILL_LOCKED"
PENDING = "LOCKED_PENDING_RECONCILIATION"


def _state(age, verdict=READY, locked=True) -> str:
    return _machine_state(age_seconds=age, verdict=verdict, trading_locked=locked)[0]


def test_unreadable_heartbeat_is_never_read_as_healthy():
    assert _state(None) == "DEAD_LOOP"


def test_stale_loop_is_dead_not_locked():
    assert _state(301) == "DEAD_LOOP"


def test_the_incident_reads_as_a_dead_loop_first():
    assert _state(302390, verdict=PENDING) == "DEAD_LOOP"


def test_live_loop_with_a_shut_gate_is_locked_not_dead():
    assert _state(26, verdict=PENDING) == "LOCKED_BY_GATE"


def test_ready_but_unopened_is_named_as_awaiting_the_owner():
    assert _state(26, verdict=READY, locked=True) == "AWAITING_OWNER"


def test_open_trading_is_the_only_running_state():
    assert _state(26, verdict=READY, locked=False) == "RUNNING"


def test_every_state_carries_an_arabic_sentence():
    for age, verdict, locked in ((None, READY, True), (26, PENDING, True),
                                 (26, READY, True), (26, READY, False)):
        _, ar = _machine_state(age_seconds=age, verdict=verdict, trading_locked=locked)
        assert ar.strip() and len(ar) > 15, (age, verdict, locked, ar)
