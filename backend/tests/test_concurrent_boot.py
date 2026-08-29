"""
التمهيد المتزامن — العطل الذي أظهرته اللوحة الرئيسية أول مرة.

اللوحة تطلب خمسة مسارات في اللحظة نفسها. وكل طلب يعمل في خيط منفصل عند
uvicorn، فرأى كلٌّ منها النظام غير مبنيّ وبدأ يبنيه:

    sqlite3.OperationalError: table accounts already exists

**العطل لا يظهر بطلب واحد.** فلا يُختبَر بطلب واحد.
"""
from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from app.db.session import init_db, make_engine
from app.mobile.routes import UNEXPECTED_ERROR_AR, MobileRuntime, set_runtime
from app.mobile.security import MobileSecurityService
from app.mobile.store import MobileStateStore


def test_init_db_is_safe_when_threads_start_together(tmp_path):
    """`create_all(checkfirst=True)` يفحص ثم يُنشئ، وبين الاثنين فجوة."""
    engine = make_engine(f"sqlite:///{tmp_path/'race.db'}")
    barrier = threading.Barrier(8)
    errors: list[BaseException] = []

    def worker() -> None:
        barrier.wait()  # الانطلاق معاً — بلا هذا لا يظهر التسابق
        try:
            init_db(engine)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"تسابقت الخيوط على إنشاء الجداول: {errors[:1]}"


def test_system_is_built_exactly_once_under_concurrency():
    """
    البناء ثقيل (يفتح اتصالاً بالوسيط). فتكراره خطأ حتى لو لم يرمِ استثناءً.
    """
    import app.main as main

    calls: list[int] = []
    barrier = threading.Barrier(8)

    def slow_build(*_args, **_kwargs):
        # البناء الحقيقي بطيء (يفتح اتصالاً بالوسيط ويُنشئ الجداول). وبلا
        # هذا التأخير تكون نافذة التسابق أضيق من أن تُلتقَط، فيمرّ الاختبار
        # على كود مكسور — وقد جرّبنا ذلك فمرّ.
        time.sleep(0.05)
        calls.append(1)
        return object()

    original_system, original_build = main._SYSTEM, main.build_system
    main._SYSTEM, main.build_system = None, slow_build
    try:
        results = []

        def worker() -> None:
            barrier.wait()
            results.append(main.system())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(calls) == 1, f"بُني النظام {len(calls)} مرّات لا مرّة واحدة"
        assert len({id(r) for r in results}) == 1, "خيوط مختلفة رأت أنظمة مختلفة"
    finally:
        main._SYSTEM, main.build_system = original_system, original_build


def test_unexpected_exception_becomes_500_without_leaking_its_text(tmp_path):
    """
    كان رأس `routes.py` يَعِد بهذا ولا يفعله: لم يكن يُلتقَط إلا
    `MobileApiError`، فيصعد ما عداه إلى uvicorn.
    """
    from fastapi import FastAPI

    from app.mobile.routes import router, session_router

    def exploding_state() -> dict:
        raise RuntimeError("/Users/maather/secret/path حقل_داخلي")

    store = MobileStateStore(tmp_path / "state.json")
    security = MobileSecurityService(store=store)
    set_runtime(MobileRuntime(security=security, state_source=exploding_state))

    challenge = security.create_enrollment_challenge()
    app = FastAPI()
    app.include_router(session_router)
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    enrolled = client.post(
        "/api/mobile/session/enroll",
        json={
            "challenge_id": challenge.challenge_id,
            "public_identity": "a" * 16,
            "device_name": "Mesa",
        },
    )
    assert enrolled.status_code == 200, enrolled.text
    token = enrolled.json()["access_token"]

    response = client.get(
        "/api/mobile/v1/status", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code == 500
    body = response.text
    assert response.json()["error_ar"] == UNEXPECTED_ERROR_AR
    # لا مسار، ولا اسم حقل داخلي، ولا نوع الاستثناء.
    for leaked in ("/Users/", "حقل_داخلي", "RuntimeError", "Traceback"):
        assert leaked not in body, f"تسرّب «{leaked}» إلى الجوال"
