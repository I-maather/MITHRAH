"""
لا مسارَ في `/api` مفتوحٌ إلا بقرارٍ معلَن.

## العيب الذي أُغلق

طبقةُ الجوال بُنيت بحرصٍ نادر: رمزٌ قصير العمر، وتسجيلٌ بعاملين، وقائمةٌ
مغلقةٌ من ثلاثة مسارات **كلّها تُقلّل المخاطرة**، واختبارا عقدٍ يمنعان إضافة
رابعٍ بلا كسرِ الطرفين. والدليل يقول صراحةً: «أسوأ ما يفعله من يسرق رمزك هو
إيقاف التداول».

وكان المجال `/api` في الوقت نفسه **بلا أيّ مصادقة**، منشوراً على الشبكة
الخاصة عبر `tailscale serve`، وفيه ثلاثةٌ **تزيد المخاطرة**:

    POST /api/trading/resume
    POST /api/risk/kill-switch/reset
    POST /api/profiles/confirm-upgrade

فمن على الشبكة الخاصة — أو هاتفٌ مسروقٌ عليها — يستدعيها بسطر `curl` واحد
ويُبطل كلَّ ما حرسته طبقةُ الجوال. بابٌ محصَّن وإلى جانبه نافذةٌ مفتوحة.

## وما يحرسه هذا الملف

أنّ الحارس **على الطبقة لا على المسار**: يُعدَّد كلُّ مسارٍ يعرفه التطبيق،
ويجب أن يكون كلٌّ منها إمّا محروساً بالرمز، أو في قائمة إعفاءٍ مغلقةٍ مكتوبةٍ
هنا بالكامل. فمسارٌ جديد يُضاف بلا قرار **يُسقط هذا الاختبار** — وهو الغرض.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.auth import API_TOKEN_NAME, EXEMPT_EXACT, EXEMPT_PREFIXES, is_exempt
from app.main import app

#: هذا الملف يفحص الحارس نفسه، فيُترَك مجالُه بلا مصادقةٍ من `conftest`.
pytestmark = pytest.mark.raw_api

TOKEN = "test-token-not-a-real-secret-0001"


class _Secrets:
    def __init__(self, token=None):
        self._token = token

    def get(self, name):
        if name == API_TOKEN_NAME and self._token is not None:
            return self._token
        raise KeyError(name)


@pytest.fixture()
def client(monkeypatch):
    from types import SimpleNamespace

    state = SimpleNamespace(secrets=_Secrets(TOKEN))
    monkeypatch.setattr("app.main.system", lambda: state, raising=False)
    monkeypatch.setattr("app.api.auth._configured_token", lambda s: TOKEN)
    return TestClient(app)


def _api_paths() -> list[str]:
    return sorted(
        {
            r.path
            for r in app.routes
            if getattr(r, "path", "").startswith("/api")
        }
    )


# --- ١ · التعداد: لا مسارَ خارج الحسبان ------------------------------------


def test_every_api_route_is_guarded_or_explicitly_exempt():
    """
    **الاختبار الذي يمنع النسيان.** لا يفحص مساراً بعينه؛ يفحص أنّ كلَّ
    مسارٍ موجودٍ اليوم أو غداً مصنَّف.
    """
    unclassified = []
    for path in _api_paths():
        if is_exempt(path):
            continue
        # ما ليس معفىً فهو محروسٌ بالوسيط — والوسيط يلتقط كل ما تحت /api.
        if not path.startswith("/api"):
            unclassified.append(path)
    assert unclassified == []


def test_the_exemption_list_is_small_and_written_here():
    """
    قائمةُ الإعفاء تُكتب هنا بالكامل عمداً: توسيعها يُسقط الاختبار، فلا
    يتسلّل إعفاءٌ في مراجعةٍ عابرة.
    """
    assert EXEMPT_PREFIXES == ("/api/mobile/",)
    # أُضيف `/api/health/ops` في ٢٠٢٦-٠٩-١٥ **بتحديثٍ واعٍ لهذا السطر** —
    # وهو بالضبط ما وُجد هذا الاختبار لأجله: لا يتسلّل إعفاءٌ بصمت.
    # يحمل حياةَ الآلة وحدها (كوميت، مدّةُ تشغيل، عمرُ آخر دورةِ قرار)،
    # ولا يحمل وسيطاً ولا رصيداً ولا مركزاً — يفحص ذلك الاختبارُ التالي.
    assert EXEMPT_EXACT == frozenset({"/api/health/live", "/api/health/ops"})


def test_the_ops_route_carries_no_account_information():
    """
    شرطُ الإعفاء ليس صِغَرَ القائمة بل **خلوّ المسار من معلومة حساب**.
    فلو أُضيف حقلٌ يوماً يذكر رصيداً أو مركزاً أو وسيطاً، يسقط هذا هنا.
    """
    from app.main import health_ops

    payload = health_ops()
    # أُضيفت `state` و`state_ar` و`startup` في ٢٠٢٦-٠٩-١٩ **بتحديثٍ واعٍ
    # لهذا السطر**، للسبب نفسه الذي وُجد لأجله: لا يتسلّل حقلٌ بصمت.
    #
    # وسببُ الإضافة أنّ `healthy: false` وحدها كانت تُقال عن حالتين لا
    # تشتركان في شيء — حلقةٌ ماتت، أو بوابةٌ أُقفلت بقرارٍ مكتوب — فقرأها
    # الحارسُ «ميت» فأعاد التشغيل بلا جدوى أربعةَ أيام.
    #
    # والحقولُ الثلاثة تصف **حالةَ الآلة وحكمَ بوابتها**، لا حساباً: لا
    # رصيد ولا مركز ولا وسيط ولا رمز — تُثبته قائمةُ الممنوعات أدناه.
    assert set(payload) == {
        "ok", "state", "state_ar", "startup",
        "commit", "started_utc", "uptime_seconds", "decision_loop",
    }
    assert set(payload["decision_loop"]) == {
        "last_cycle_utc", "age_seconds", "healthy",
    }
    # **العددُ يُقال والنصُّ لا يُقال.** نصُّ مشكلةِ المطابقة يحمل الرمزَ
    # والكمية («مركز مسجّل لدينا وغير موجود لدى الوسيط: GOLD كمية ‎-0.12»)
    # وذاك معلومةُ حساب. فالمسموح في `startup` ثلاثةٌ لا رابعَ لها، وأيُّ
    # محاولةٍ لإرسال النصوص يوماً تسقط هنا.
    assert set(payload["startup"]) == {
        "verdict", "trading_locked", "problems_count",
    }
    assert isinstance(payload["startup"]["verdict"], str)
    assert isinstance(payload["startup"]["problems_count"], (int, type(None)))
    assert isinstance(payload["startup"]["trading_locked"], (bool, type(None)))
    flat = repr(payload).lower()
    for forbidden in (
        "balance", "equity", "position", "pnl", "broker", "account",
        "risk", "symbol", "eurusd", "gbpusd", "gold", "capital",
    ):
        assert forbidden not in flat, f"مسارُ التشغيل سرّب «{forbidden}»"


def test_the_risk_increasing_routes_are_not_exempt():
    """الثلاثة التي تزيد المخاطرة — لا واحدة منها معفاة."""
    for path in (
        "/api/trading/resume",
        "/api/risk/kill-switch/reset",
        "/api/profiles/confirm-upgrade",
    ):
        assert path in _api_paths(), f"{path} اختفى — أو تغيّر اسمه"
        assert not is_exempt(path)


def test_the_full_health_route_is_not_exempt_only_the_liveness_one():
    """
    `/api/health` فيه حالةُ الوسيط وقاطع الطوارئ والمجدول — معلوماتٌ عن
    الحساب. و`/api/health/live` نبضٌ فارغ.
    """
    assert is_exempt("/api/health/live") is True
    assert is_exempt("/api/health") is False


# --- ٢ · السلوك -------------------------------------------------------------


def test_a_request_without_a_token_is_refused(client):
    r = client.get("/api/today")
    assert r.status_code == 401
    assert "رمز" in r.json()["reason_ar"]


def test_a_request_with_a_wrong_token_is_refused(client):
    r = client.get("/api/today", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_a_mutating_route_is_refused_without_a_token(client):
    """الأهمّ: لا يُستأنف التداول بلا رمز."""
    r = client.post("/api/trading/resume", json={})
    assert r.status_code == 401


def test_the_liveness_probe_needs_no_token(client):
    r = client.get("/api/health/live")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_the_liveness_probe_leaks_nothing(client):
    """نبضُ حياةٍ يحمل حالة الوسيط ليس نبضاً — هو تسريب."""
    body = client.get("/api/health/live").json()
    assert set(body) == {"ok"}


# --- ٣ · الفشل مغلق ---------------------------------------------------------


def test_an_unconfigured_token_closes_the_domain_rather_than_opening_it(monkeypatch):
    """
    مجالٌ مفتوحٌ لأنّ الإعداد ناقص أسوأ الحالتين: يعمل، فلا يلاحظه أحد.
    """
    from types import SimpleNamespace

    monkeypatch.setattr("app.main.system", lambda: SimpleNamespace(secrets=_Secrets(None)), raising=False)
    monkeypatch.setattr("app.api.auth._configured_token", lambda s: None)
    c = TestClient(app)

    r = c.get("/api/today")
    assert r.status_code == 503
    assert r.json()["error"] == "API_TOKEN_NOT_CONFIGURED"

    # وحتى نبضُ الحياة يبقى يعمل — فحصُ الإقلاع لا يحتاج رمزاً.
    assert c.get("/api/health/live").status_code == 200


# --- ٤ · مجال الجوال لم يُمَسّ ------------------------------------------------


def test_the_mobile_domain_keeps_its_own_guard(client):
    """
    مصادقتان متتاليتان تعنيان رمزين على الجوال بلا فائدة. فالمجال معفىً من
    **هذا** الحارس، ومحروسٌ بحارسه: ٤٠١ بلا رمز جهاز.
    """
    r = client.get("/api/mobile/v1/status")
    assert r.status_code == 401
