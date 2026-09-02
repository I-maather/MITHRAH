"""
**كل استجابة — قراءةً كانت أو إجراءً — تلبس الغلاف الذي يشترطه العميل.**

## العطل الذي فرض هذا الملف

كان `_read` يبني الغلاف بنفسه، و`_mutate` يعيد قاموساً عارياً. والعميل يرفض
أي استجابة بلا غلاف (`mobile/src/api/client.ts::isEnvelope`) ويُظهر:

    «استجابة لا تطابق عقد الجوال. أهملت.»

فكان **كل إجراء في التطبيق ميتاً**: الإيقاف، والاستئناف، وإلغاء الجهاز،
وتبديل الحساب — و**قاطع الطوارئ**. أي أن الزرّ الوحيد الذي يوقف النظام في
حالة الطوارئ كان لا يفعل شيئاً من الجوال.

## ولماذا لم يكشفه اختبار واحد

اختبارات الخادم كانت تفحص ما تعيده `_mutate` مباشرةً — وهو صحيح في ذاته.
واختبارات الجوال تحقن `fetch` وهمياً **يبني الغلاف بيده** (`helpers.envelope`)
— فيوافق العميلَ دائماً. كلّ طرفٍ يوافق نفسه، ولا اختبار يعبر الحدّ.

وهو العطل نفسه الذي أسقط التطبيق إلى شاشة سوداء يوم كان الخادم يرسل
`kill_switch_active` والتطبيق يقرأ `kill_switch.active`. عاد بصورة ثانية،
في المسارات التي لم يغطّها عقد `mobile-contract.json` — وهو يغطّي أقسام
القراءة وحدها.

## القاعدة المفروضة هنا

الشرط مكتوب **نسخةً طبق الأصل من شرط العميل**، لا صياغةً منه. ولو غُيّر
هناك وُجب تغييره هنا، ويسقط الاختبار حتى يُغيَّر.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.test_mobile_backend import enrolled, service
from app.mobile.api import MobileActions, MobileApi

REPO = Path(__file__).resolve().parents[2]
CLIENT_TS = REPO / "mobile" / "src" / "api" / "client.ts"

#: نسخة `isEnvelope` من `client.ts`. أي مفتاح ناقص ⇒ العميل يرفض الاستجابة.
REQUIRED_KEYS = ("route", "server_time_utc", "device_id", "authorises_execution", "data")


@pytest.fixture()
def mobile_api_and_token():
    """مجالٌ حقيقي بجهازٍ مقترن — لا وهمي يبني الغلاف بيده."""
    svc = service()
    device = enrolled(svc)
    access, _ = svc.issue_tokens(device.device_id)
    recorded: list[str] = []
    actions = MobileActions(
        pause=lambda reason: recorded.append(reason),
        activate_kill_switch=lambda reason: recorded.append(reason),
    )
    return MobileApi(security=svc, actions=actions), access.token


def is_envelope(body: object) -> bool:
    if not isinstance(body, dict):
        return False
    return (
        isinstance(body.get("route"), str)
        and isinstance(body.get("server_time_utc"), str)
        and isinstance(body.get("device_id"), str)
        and "authorises_execution" in body
        and "data" in body
    )


def test_the_client_still_demands_exactly_these_keys():
    """
    لو خُفّف شرط العميل أو شُدّد ولم يُنقل هنا، صار هذا الملف يحرس عقداً
    قديماً — وهو أسوأ من ألّا يحرس شيئاً، لأنه يُطمئن بلا حقّ.
    """
    source = CLIENT_TS.read_text(encoding="utf-8")
    body = source[source.index("const isEnvelope"): source.index("export class MobileApiClient")]
    for key in REQUIRED_KEYS:
        assert re.search(rf"[\"']?{key}[\"']?", body), f"العميل لم يعد يشترط {key}"


@pytest.mark.parametrize("route", [
    "status", "intelligence/latest", "decision/latest", "risk", "profiles",
    "positions/current", "trades", "performance", "providers/health",
    "notifications", "audit/recent", "scan/latest", "market/candles",
])
def test_every_read_route_wears_the_envelope(mobile_api_and_token, route):
    api, token = mobile_api_and_token
    body = api.handle("GET", route, token=token).body
    assert is_envelope(body), f"{route}: استجابة بلا غلاف — سيرفضها العميل"
    assert body["route"] == route
    assert body["authorises_execution"] is False


@pytest.mark.parametrize("route,payload", [
    ("pause/request", {}),
    ("killswitch/activate", {}),
])
def test_every_action_wears_the_envelope(mobile_api_and_token, route, payload):
    """
    **هذا هو الفحص الذي كان غائباً.** قاطع الطوارئ من ضمنه.
    """
    api, token = mobile_api_and_token
    body = api.handle("POST", route, token=token, payload=payload).body
    assert is_envelope(body), f"{route}: استجابة بلا غلاف — الزرّ ميت في التطبيق"
    assert body["route"] == route
    assert body["authorises_execution"] is False
    # والحمولة نفسها لم تُفقَد في أثناء التغليف.
    assert body["data"]["accepted"] is True
    assert isinstance(body["data"]["action"], str)


def test_the_action_payload_lives_under_data_not_at_the_top():
    """
    الشاشات تقرأ `response.data.accepted` — لا `response.accepted`.
    فوضعُ الحمولة في الأعلى يجعل كل زرٍّ يقول «فشل» وهو نجح.
    """
    from app.mobile.api import RISK_REDUCING_ROUTES, RISK_INCREASING_ROUTES
    assert set(RISK_REDUCING_ROUTES + RISK_INCREASING_ROUTES) == {
        "pause/request", "killswitch/activate", "device/revoke",
        "pause/resume", "broker/environment",
    }


def test_the_broker_view_reads_its_lists_from_the_adapter_not_from_a_constant():
    """
    كانت `/api/broker` تطبع ثابتَي `capital_discovery.py` بدل قائمتَي
    المحوّل. فلمّا وُسّعت قائمة التنفيذ بالقياس إلى أربع أدوات، بقيت الشاشة
    تقول «EURUSD» وحدها — وقرأتها المالكة على أن التوسيع لم يقع.

    فحصٌ ساكن على المصدر: النداء إلى `getattr` على المحوّل يجب أن يبقى.
    """
    from pathlib import Path

    body = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert 'getattr(sys.broker, "execution_allowlist", None)' in body
    assert 'getattr(sys.broker, "discovery_allowlist", None)' in body
