from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import KILL_PHRASE, RESET_PHRASE, app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("BROKER_MODE", "MOCK")
    monkeypatch.setenv("LIVE_TRADING", "false")
    # **رأس مال مثبَّت لهذا الاختبار.**
    #
    # كل الحدود تُشتقّ من `BASELINE_EQUITY_USD`، والتأكيدات أدناه أرقامٌ
    # دقيقة محسوبة على ١٥٠. ولمّا صُحّح رأس المال الحقيقي إلى ١٤٠ سقطت ستة
    # تأكيدات — لا لخلل بل لأنها كانت تقرأ إعداداً يتغيّر بتمويل المالكة.
    #
    # فيُثبَّت هنا: يبقى الاختبار حسابياً دقيقاً، ولا يسقط في كل مرة يتغيّر
    # فيها التمويل. وفحص الانحراف الحقيقي موضعه `check_baseline_against_broker`
    # لا هذا الملف.
    monkeypatch.setenv("BASELINE_EQUITY_USD", "150.00")
    import app.config as config
    import app.db.session as dbs
    import app.main as main

    config.get_settings.cache_clear()
    dbs.ENGINE = dbs.make_engine(f"sqlite:///{tmp_path/'t.db'}")
    dbs.SessionLocal.configure(bind=dbs.ENGINE)
    main._SYSTEM = None
    with TestClient(app) as c:
        yield c
    main._SYSTEM = None
    config.get_settings.cache_clear()


def test_health_reports_mock_broker_and_live_off(client):
    r = client.get("/api/health").json()
    assert r["broker_name"] == "MOCK"
    assert r["broker_is_live"] is False
    assert r["audit_chain_ok"] is True


def test_today_shows_riyadh_12_hour_times(client):
    r = client.get("/api/today").json()
    assert r["live_trading_enabled"] is False
    assert ("ص" in r["now_riyadh"]) or ("م" in r["now_riyadh"])
    # ⚠️ تغيّرت ثلاث قيم في وضع التحقّق يوم 2026-09-01 **بقرار معلَن**، لا سهواً:
    #   الحاجز المطلق 7.50 ⇐ 15.00 · اليومي 1.50 ⇐ 3.00 · الأسبوعي 4.50 ⇐ 7.50
    #
    # السبب أن الوضع اتّسع إلى ثلاثة مراكز، وثلاثةُ وقوف تُضرب معاً تساوي 2.25 —
    # فحدٌّ يوميّ عند 1.50 كان **يُخترق قبل أن يعمل**. والثابت الرابط يُفرَض الآن
    # عند البناء (`IncoherentRiskLimits`)، ويُفحَص في
    # `test_multi_instrument_scan.py::test_the_daily_cap_can_absorb_every_stop_at_once`.
    #
    # والأوضاع الحقيقية **لم تُمَسّ** — وهو ما يفحصه الاختبار التالي لهذا مباشرةً.
    # ⚠️ تغيّرت خمسُ قيمٍ يوم ٢٠٢٦-٠٩-١١ **بقرار المالكة المعلَن** (رفعُ
    # المخاطرة في التجريبي وحده)، لا سهواً. القيم أدناه على مرجع ١٥٠ —
    # وعلى ٣٠٠ تصير: ٧٢ · ٢٤ · ٤٨ · ١٠٫٠٠ · ١٢٫٠٠ (رفعُ ١٥ سبتمبر).
    assert r["limits"]["total"] == "36.00"
    assert r["limits"]["daily"] == "12.00"
    assert r["limits"]["weekly"] == "24.00"
    assert r["limits"]["target_risk_per_trade"] == "5.00"
    assert r["limits"]["max_risk_per_trade"] == "6.00"
    assert r["equity"]["baseline"] == "150.00"
    assert r["risk_mode"] == "VALIDATION"


def test_risk_mode_defaults_to_validation_and_is_not_changeable_from_ui(client):
    r = client.get("/api/settings").json()
    assert r["risk_mode"] == "VALIDATION"
    assert r["risk_mode_changeable_from_ui"] is False
    assert r["baseline_equity_usd"] == "150.00"


def test_all_four_modes_are_published_with_their_limits(client):
    r = client.get("/api/risk").json()
    modes = r["modes"]
    assert set(modes) == {
        "VALIDATION", "LIVE_COMMISSIONING", "CONSERVATIVE_LIVE", "LOCKED_REVIEW"
    }
    assert modes["CONSERVATIVE_LIVE"]["max_risk_pct"] == "1.00"
    assert modes["CONSERVATIVE_LIVE"]["weekly_loss_pct"] == "2.00"
    assert modes["LIVE_COMMISSIONING"]["max_lifetime_entry_orders"] == 1
    assert modes["LIVE_COMMISSIONING"]["requires_per_order_approval"] is True
    assert modes["LIVE_COMMISSIONING"]["enforce_economic_viability"] is False
    assert r["economic_guards_enforced"] is True



def _all_paths(application) -> set[str]:
    """كل مسار في التطبيق، بما في ذلك ما تحت الموجّهات المُضمَّنة."""
    found: set[str] = set()
    pending = list(application.routes)
    while pending:
        route = pending.pop()
        path = getattr(route, "path", None)
        if path is not None:
            found.add(path)
        nested = getattr(route, "routes", None)
        if nested is None:
            inner = getattr(route, "original_router", None)
            nested = getattr(inner, "routes", None)
        if nested:
            pending.extend(nested)
    return found

def test_risk_constitution_is_not_editable_from_the_api(client):
    r = client.get("/api/risk").json()
    assert r["editable_from_ui"] is False
    assert r["constitution_fingerprint"]
    # لا يوجد أي endpoint للكتابة على الحدود
    #
    # يُمشى على الموجّهات المُضمَّنة أيضاً: `include_router` يضع كائناً بلا
    # `.path`، فقراءةُ المستوى الأول وحده كانت ستتجاهل مجالاً كاملاً —
    # وهذا بالضبط ما يجب ألّا يفلت من هذا الفحص.
    assert not any(
        "limits" in path and path != "/api/risk" for path in _all_paths(app)
    )


def test_kill_switch_requires_exact_phrase(client):
    bad = client.post("/api/risk/kill-switch",
                      json={"reason_ar": "سبب كافٍ للمراجعة", "confirm_phrase": "أوقف"})
    assert bad.status_code == 400
    good = client.post("/api/risk/kill-switch",
                       json={"reason_ar": "أوقف مؤقتاً لمراجعة الإعدادات", "confirm_phrase": KILL_PHRASE})
    assert good.status_code == 200 and good.json()["active"] is True


def test_reset_requires_acknowledgement_and_phrase(client):
    client.post("/api/risk/kill-switch",
                json={"reason_ar": "إيقاف للاختبار الآن", "confirm_phrase": KILL_PHRASE})
    r1 = client.post("/api/risk/kill-switch/reset", json={
        "approved_by": "Maather", "reason_ar": "راجعت السبب بالكامل",
        "confirm_phrase": RESET_PHRASE, "acknowledged_review": False,
    })
    assert r1.status_code == 400
    r2 = client.post("/api/risk/kill-switch/reset", json={
        "approved_by": "Maather", "reason_ar": "راجعت السبب بالكامل",
        "confirm_phrase": "خطأ", "acknowledged_review": True,
    })
    assert r2.status_code == 400
    r3 = client.post("/api/risk/kill-switch/reset", json={
        "approved_by": "Maather", "reason_ar": "راجعت السبب بالكامل وأعتمد الاستئناف",
        "confirm_phrase": RESET_PHRASE, "acknowledged_review": True,
    })
    assert r3.status_code == 200 and r3.json()["active"] is False


def test_strategies_endpoint_shows_no_approved_strategy(client):
    r = client.get("/api/strategies").json()
    assert r["active_count"] == 0
    assert r["strategies"][0]["state"] == "RESEARCH"


def test_opportunities_never_render_a_buy_call(client):
    r = client.get("/api/opportunities").json()
    for row in r["allowlist"]:
        assert "status_ar" in row and "rationale_ar" in row
        assert "اشترِ" not in row["status_ar"]
    assert any(d["symbol"] == "XAUUSD" for d in r["denylist"])


def test_audit_endpoint_verifies_chain(client):
    r = client.get("/api/audit").json()
    assert r["chain_ok"] is True
    assert r["checked"] >= 1


def test_settings_endpoint_marks_constitution_read_only(client):
    r = client.get("/api/settings").json()
    assert r["risk_constitution_editable"] is False
    assert r["mode"] == "PAPER/MOCK"


def test_trading_allowed_counts_every_gate_not_two(client):
    """
    كان `trading_allowed` يفحص بوابتين من ست، فيقول «مسموح» بينما الإيقاف
    المحلي مرفوع وقفل التنفيذ مغلق ووحدة الوقف غير مُثبَتة.

    الثابت هنا: **لا يكون `true` وأيّ بوابة مغلقة.** وهو يصمد أياً كانت
    البوابة المغلقة، ولا يحتاج تعديلاً حين تُضاف بوابة سابعة.
    """
    r = client.get("/api/today").json()
    assert "blocked_by" in r, "لا يكفي «ممنوع» بلا تسمية المانع"
    assert r["trading_allowed"] is (len(r["blocked_by"]) == 0)

    # في بيئة الاختبار: وسيط وهمي، والتداول الحقيقي مطفأ، والتنفيذ مقفل.
    assert r["trading_allowed"] is False
    assert r["blocked_by"], "بوابات مغلقة ولم تُسمَّ"


def test_trading_allowed_is_false_whenever_execution_is_impossible(client):
    """
    فحصٌ من الجهة الأخرى: كل قفلٍ يمنع التنفيذ فعلياً يجب أن يظهر أثره هنا.
    لو ظهر `trading_allowed: true` بينما `live_trading_enabled: false`، فالحقل
    يكذب — والمالكة تقرأ منه استعداد النظام.
    """
    r = client.get("/api/today").json()
    if not r["live_trading_enabled"]:
        assert r["trading_allowed"] is False


def test_blocked_by_names_the_failure_not_the_requirement(client):
    """
    أول نسخة أدرجت **الشرط المطلوب** في `blocked_by` بدل **سبب المنع**،
    فقرأت المالكة: «ممنوع بسبب: التشغيل غير موقوف محلياً» — عكس المعنى.

    والاختبار السابق مرّ عليها، لأنه يفحص العلاقة (`allowed` ⟺ القائمة
    فارغة) لا دلالة النصّ. فهذا يثبّت الصياغة: البوابات المغلقة يقيناً في
    بيئة الاختبار تُكتب أسبابها بصيغة الحال لا بنفي الشرط.

    ⚠️ **حُذف من هنا `التداول الحقيقي مُعطَّل` يوم 2026-09-03** — لا تخفيفاً
    للصياغة بل لأن وسيط الاختبار تجريبيّ، وهذه البوابة صارت تُعرَض للحقيقي
    وحده (انظر `test_the_screen_shows_the_gate_that_governs.py`). وصياغتها
    محروسةٌ هناك على وسيطٍ حقيقي، فلم يسقط حارس.
    """
    r = client.get("/api/today").json()
    blocked = r["blocked_by"]

    assert "التشغيل موقوف محلياً" in blocked
    assert "قفل التنفيذ مغلق" in blocked

    # ولا يظهر شرطٌ مُحقَّق في قائمة الموانع.
    for satisfied in ("التشغيل غير موقوف محلياً", "قفل التنفيذ مفتوح",
                      "التداول الحقيقي مُفعَّل", "وحدة الوقف مُثبَتة"):
        assert satisfied not in blocked, f"شرطٌ مُحقَّق أُدرج كمانع: {satisfied}"
