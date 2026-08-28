from __future__ import annotations

from dataclasses import replace

from app.audit.log import (
    Actor,
    AuditAction,
    AuditLog,
    InMemoryAuditStore,
    verify_chain,
)


def build_log(n: int = 5) -> AuditLog:
    log = AuditLog(InMemoryAuditStore())
    for i in range(n):
        log.record(
            actor=Actor.PIPELINE, action=AuditAction.NO_TRADE, decision=f"D{i}",
            reason_ar=f"سبب رقم {i}", source="test",
        )
    return log


def test_chain_is_valid_when_untouched():
    result = verify_chain(build_log().events())
    assert result.ok and result.checked == 5


def test_first_event_links_to_genesis():
    events = build_log(1).events()
    assert events[0].previous_hash == "0" * 64
    assert events[0].sequence == 1


def test_no_trade_is_logged_like_a_trade():
    log = AuditLog(InMemoryAuditStore())
    log.record(actor=Actor.PIPELINE, action=AuditAction.NO_TRADE, decision="NO_SETUP",
               reason_ar="لا فرصة", source="strategy")
    assert log.events()[0].action == "NO_TRADE"


def test_tampering_with_content_is_detected():
    events = build_log().events()
    events[2] = replace(events[2], reason_ar="نص مُعدَّل بعد الكتابة")
    result = verify_chain(events)
    assert not result.ok
    assert result.first_bad_sequence == 3
    assert "عُدّل" in result.problem_ar


def test_deleting_a_row_is_detected():
    events = build_log().events()
    del events[2]
    result = verify_chain(events)
    assert not result.ok
    assert "التسلسل" in result.problem_ar


def test_reordering_is_detected():
    events = build_log().events()
    events[1], events[2] = events[2], events[1]
    assert not verify_chain(events).ok


def test_relinking_a_forged_row_still_breaks_the_chain():
    """
    محاولة متقدمة: تعديل صف وإعادة حساب بصمته فقط — تبقى السلسلة مكسورة
    لأن الصف التالي يحمل previous_hash القديم.
    """
    events = build_log().events()
    forged = replace(events[2], reason_ar="مزوّر")
    forged = replace(forged, entry_hash=forged.compute_hash())
    events[2] = forged
    result = verify_chain(events)
    assert not result.ok
    assert result.first_bad_sequence == 4


def test_empty_chain_is_valid():
    assert verify_chain([]).ok
