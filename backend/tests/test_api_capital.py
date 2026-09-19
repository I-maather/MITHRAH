"""واجهة API الخاصة بـCapital.com — عرض بلا أسرار، وإيقاف محلي لا يفتح شيئاً."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import KILL_PHRASE, RESUME_PHRASE, app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("BROKER_MODE", "MOCK")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("RISK_MODE", "VALIDATION")
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


# --- حالة الوسيط -------------------------------------------------------------

def test_broker_endpoint_reports_the_locks_truthfully(client):
    """
    الثابت المحروس ليس **قيمة** القفل بل **صدق التبليغ عنها**.

    كان الاختبار يشترط `live_api_enabled_in_source is False`. ولمّا رُفع القفل
    بموافقة مكتوبة كان سيسقط، فيُغرى أحدٌ بحذفه. والخطر الحقيقي ليس أن يكون
    القفل مرفوعاً — بل أن تعرض الواجهة أنه مغلق وهو مرفوع. فالشرط الآن:
    ما تقوله الواجهة = ما في المصدر.
    """
    from app.brokers.capital.safety import LIVE_API_ENABLED

    body = client.get("/api/broker").json()
    assert body["live_api_enabled_in_source"] is LIVE_API_ENABLED
    assert body["is_demo"] is True
    # الوسيط الوهمي بلا جلسة، فلا عنوان له — و`None` هنا صدقٌ لا نقص.
    # القاعدة: إن وُجد عنوان فهو عنوان بيئة يقرّ بها الوسيط نفسه.
    if body["base_url"] is not None:
        assert body["base_url"].startswith("https://")
        assert body["environment"] in body["base_url"] or body["is_demo"]
    # يبقى شرطاً قاطعاً بلا استثناء: قفل التنفيذ مغلق.
    assert body["execution_lock"]["unlocked"] is False
    assert body["risk_constitution_version"] == "0.6.0"


def test_broker_endpoint_never_returns_a_credential_value(client):
    body = client.get("/api/broker").json()
    serialised = json.dumps(body, ensure_ascii=False)
    for key in ("CAPITAL_API_KEY", "CAPITAL_IDENTIFIER", "CAPITAL_API_PASSWORD"):
        # الاسم مسموح، القيمة ممنوعة — والحالة boolean فقط.
        assert key in serialised
    for entry in body["credentials"]:
        assert set(entry) == {"name", "present", "source"}
        assert isinstance(entry["present"], bool)


def test_broker_endpoint_explains_how_to_pause_the_api_key(client):
    body = client.get("/api/broker").json()
    joined = " ".join(body["api_key_pause_instructions_ar"])
    assert "Capital.com" in joined
    assert "API" in joined
    assert "أقوى من أي زر" in joined


def test_allowlists_are_published_from_the_adapter_not_from_a_constant(client):
    """
    ⚠️ **تغيير مُعلَن (2026-09-02).** كان الفحص يثبّت القائمتين نصّاً، وكان
    ذلك يوافق ثابتَي `capital_discovery.py` اللذين تطبعهما الواجهة. فلمّا
    وُسّعت قائمة التنفيذ **بالقياس** إلى أربع أدوات، بقيت الواجهة تقول
    «EURUSD» وحدها ومرّ الفحص — لأنه كان يحرس الثابت لا الحقيقة.

    فالمطلوب الآن أن المنشور = ما يعمل به المحوّل فعلاً. وهذا **أضيق** من
    السابق لا أوسع: قائمةٌ تُطبع من ثابتٍ تمرّ مهما كان المحوّل عليه.
    """
    from app.main import system

    from app.discovery.capital_discovery import DISCOVERY_EPICS, EXECUTION_EPICS

    body = client.get("/api/broker").json()
    broker = system().broker
    # المحوّل الوهمي لا يحمل القائمتين — والسقوط حينها إلى الثابت **مقصود
    # ومعلَن**: وسيطٌ لا يعلن قوائمه لا تُخترع له.
    expected_exec = sorted(getattr(broker, "execution_allowlist", None) or EXECUTION_EPICS)
    expected_disc = sorted(getattr(broker, "discovery_allowlist", None) or DISCOVERY_EPICS)
    assert body["execution_allowlist"] == expected_exec
    assert body["discovery_allowlist"] == expected_disc
    # ولا يتجاوز التنفيذُ الاكتشافَ بحال.
    assert set(body["execution_allowlist"]) <= set(body["discovery_allowlist"])


# --- الإيقاف المحلي ----------------------------------------------------------

def test_trading_starts_locally_paused(client):
    assert client.get("/api/broker").json()["local_trading_paused"] is True


def test_pause_is_always_allowed_and_needs_no_phrase(client):
    response = client.post("/api/trading/pause", json={"reason_ar": "إيقاف احترازي"})
    assert response.status_code == 200
    assert response.json()["local_trading_paused"] is True


def test_resume_requires_the_exact_phrase(client):
    bad = client.post(
        "/api/trading/resume",
        json={"reason_ar": "راجعت كل شيء بالكامل", "confirm_phrase": "ارفع"},
    )
    assert bad.status_code == 400


def test_resume_lifts_only_the_local_pause_never_live_trading(client):
    response = client.post(
        "/api/trading/resume",
        json={"reason_ar": "راجعت كل شيء بالكامل", "confirm_phrase": RESUME_PHRASE},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["local_trading_paused"] is False
    assert body["live_trading_enabled"] is False
    assert "ما زال مقفلاً" in body["note_ar"]


def test_resume_is_refused_while_kill_switch_is_active(client):
    client.post(
        "/api/risk/kill-switch",
        json={"reason_ar": "إيقاف للاختبار الآن", "confirm_phrase": KILL_PHRASE},
    )
    response = client.post(
        "/api/trading/resume",
        json={"reason_ar": "راجعت كل شيء بالكامل", "confirm_phrase": RESUME_PHRASE},
    )
    assert response.status_code == 400
    assert "Kill Switch" in response.json()["detail"]


# --- بطاقة معاينة CFD ---------------------------------------------------------

def test_cfd_preview_separates_exposure_margin_and_risk(client):
    body = client.get("/api/cfd-preview?stop_pips=25&take_profit_pips=50").json()
    display = body["display"]
    assert display["notional_exposure"] != display["margin_required"]
    assert display["margin_required"] != display["all_in_risk_at_stop"]
    assert float(display["notional_exposure"]) > float(display["margin_required"])
    assert float(display["margin_required"]) > float(display["all_in_risk_at_stop"])


def test_cfd_preview_shows_every_required_field(client):
    display = client.get("/api/cfd-preview").json()["display"]
    for key in (
        "epic", "size_broker_units", "notional_exposure", "margin_required",
        "all_in_risk_at_stop", "pip_value", "stop_distance_pips", "stop_kind",
        "spread_cost", "guaranteed_stop_premium", "slippage_reserve",
        "overnight_cost", "net_reward", "net_reward_risk_ratio", "breakeven_move_pips",
    ):
        assert key in display, key


def test_cfd_preview_is_marked_provisional_before_discovery(client):
    body = client.get("/api/cfd-preview").json()
    assert body["provisional"] is True
    assert "لا يُبنى عليها قرار تنفيذ" in body["provisional_note_ar"]


def test_cfd_preview_never_claims_an_order_was_submitted(client):
    body = client.get("/api/cfd-preview").json()
    assert body["submitted"] is False
    assert body["execution_locked"] is True


def test_cfd_preview_reports_cap_compliance(client):
    """
    **يقيس أن السقف يربط، لا أن الرقم كذا.**

    كان الفحص يثبّت وقفَين بعينهما (٢٥ داخل · ٧٥ خارج)، فكُسر حين رُفع
    السقفُ الصلب يوم ١١ سبتمبر وصارت ٧٥ داخله. والمعنى المقصود ليس «٧٥
    خارج» بل **«يوجد وقفٌ يخرج، والخروج لا يعود دخولاً»** — فيُفحص ذلك
    مباشرةً، ولا يحتاج تعديلاً عند كلّ تغيير حدّ.
    """
    steps = [10, 25, 75, 150, 300, 600, 1200, 2400]
    flags = [
        client.get(f"/api/cfd-preview?stop_pips={s}").json()["caps"]["within_absolute"]
        for s in steps
    ]
    assert flags[0] is True, "أصغرُ وقفٍ يجب أن يكون داخل السقف."
    assert False in flags, f"لا وقفَ يخرج عن السقف في {steps} — السقفُ لا يربط."
    first_out = flags.index(False)
    assert all(f is False for f in flags[first_out:]), (
        f"الخروجُ عاد دخولاً: {list(zip(steps, flags))} — الخسارةُ لا تنقص بوقفٍ أوسع."
    )


def test_cfd_preview_refuses_a_zero_stop(client):
    assert client.get("/api/cfd-preview?stop_pips=0").status_code == 400


def test_guaranteed_stop_unavailable_on_provisional_values(client):
    """الوقف المضمون لا يُفترض توفره قبل الاكتشاف."""
    assert client.get("/api/cfd-preview?guaranteed=true").status_code == 400


def test_broker_endpoint_never_hardcodes_the_environment():
    """
    **هذا الاختبار يحرس ضدّ شاشة تكذب.**

    كانت `is_demo` و`base_url` قيمتين ثابتتين في المسار، و`environment`
    تعبيراً يُنتج "demo" دائماً. فلمّا صار الوسيط حقيقياً ظلّت الاستجابة
    تقول «تجريبي» و`adapter_name` يقول `CAPITAL_COM_LIVE` — تناقضٌ داخل
    استجابة واحدة، ولا اختبار يمسكه.

    الفحص على المصدر لا على القيمة: الحقول الثلاثة يجب أن تُشتقّ من الوسيط،
    ولا يجوز أن يظهر ثابتٌ مكانها.
    """
    from pathlib import Path

    import app.main as main_module

    src = Path(main_module.__file__).read_text(encoding="utf-8")
    block = src[src.index("def broker_state("):]
    block = block[: block.index("\n@")] if "\n@" in block else block
    # تُسقَط التعليقات: التعليق الذي يشرح خطأً قديماً يقتبسه، فيُمسك بنفسه.
    block = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )

    for banned in ('"is_demo": True', '"is_demo": False',
                   '"base_url": DEMO_BASE_URL', '"base_url": LIVE_BASE_URL',
                   'risk_mode and "demo"'):
        assert banned not in block, f"قيمة مثبَّتة عادت: {banned}"

    assert '"is_demo": not getattr(sys.broker' in block
    assert '_broker_environment(sys.broker)' in block


def test_broker_endpoint_agrees_with_itself(client):
    """
    التناقض الذي حدث فعلاً: `is_demo=true` مع `adapter_name=CAPITAL_COM_LIVE`.
    الحقلان يصفان الشيء نفسه، فاختلافهما عطلٌ لا تفصيلة عرض.
    """
    body = client.get("/api/broker").json()
    name = (body.get("adapter_name") or "").upper()
    if "LIVE" in name:
        assert body["is_demo"] is False
    elif "DEMO" in name:
        assert body["is_demo"] is True
