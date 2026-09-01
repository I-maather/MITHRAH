"""
عقد واحد يلتزم به الطرفان — الحارس على العطب الذي أنتج الشاشة السوداء.

## ما حدث

كُتب مصدر الحالة في الخادم بشكلٍ، وكُتب التطبيق على شكلٍ آخر. وكلٌّ كان
سليماً داخلياً ومُختبَراً وحده:

    التطبيق يقرأ  s.kill_switch.active     (كائن)
    والخادم يرسل  kill_switch_active       (قيمة مفردة)

فقراءة حقل داخل شيء غير موجود ⇒ انهيار التصيير ⇒ **شاشة سوداء بلا رسالة**.
ولم يظهر طوال الوقت لأن كل الطلبات كانت تفشل قبل الوصول إلى عرض البيانات.

## الحارس

`docs/mobile-contract.json` هو الشكل المرجعي، مُستخرَج من أنواع العميل.
ويُفحَص من الطرفين:

    هذا الملف                          ⇐ الخادم يُنتج كل مفتاح بالنوع الصحيح
    mobile/__tests__/contract.test.ts   ⇐ بيانات العميل ما زالت تطابقه

فتغييرُ أحد الطرفين وحده يُسقط اختباراً. وهذا ما كان ناقصاً.

**والمفتاح الناقص أخطر من القيمة الخاطئة**: القيمة الخاطئة تُعرض خطأً،
والمفتاح الناقص يُنهي التطبيق.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.api.state import build_system
from app.mobile.state import build_mobile_state

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "docs" / "mobile-contract.json"

#: أقسامٌ لا يبنيها `build_mobile_state`: `audit` يأتي من سجل التدقيق في
#: `MobileApi._read` مباشرةً، لا من حالة النظام.
NOT_FROM_STATE = {"audit"}


def _load_contract() -> dict[str, Any]:
    assert CONTRACT_PATH.exists(), f"ملف العقد غير موجود: {CONTRACT_PATH}"
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


#: مسارات **لا يجوز أن تصل `null`** — لأن التطبيق يفكّها بلا حارس.
#:
#: عقد العميل يقبل `null` في أغلب الحقول عمداً (والواجهة تعرض «غير متاح»)،
#: فالقائمة هنا مقلوبة: تُسمّى الحقول التي يُفكّ داخلها مباشرة. مثالها
#: `status.kill_switch` — يُقرأ في اللوحة `s.kill_switch.active`، فإرساله
#: `null` يُنهي الشاشة كلها. أي أن هذه القائمة هي الفرق بين حقل فارغ
#: وشاشة سوداء.
NON_NULLABLE_PATHS = frozenset(_load_contract()["__non_nullable_paths__"])

#: مفاتيح وصفية في ملف العقد، ليست أقساماً.
_META_KEYS = ("__comment_ar__", "__non_nullable_paths__")


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    data = _load_contract()
    for key in _META_KEYS:
        data.pop(key, None)
    return data


@pytest.fixture(scope="module")
def state() -> dict[str, Any]:
    return build_mobile_state(build_system())


def _type_name(value: Any) -> str:
    if value is None:
        return "nullable"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _generalise(path: str) -> str:
    """`providers.providers[3].kind` ⇐ `providers.providers[].kind`."""
    return re.sub(r"\[\d+\]", "[]", path)


def _check(expected: Any, actual: Any, path: str, problems: list[str]) -> None:
    if actual is None:
        if _generalise(path) in NON_NULLABLE_PATHS:
            problems.append(
                f"{path}: وصل null — والتطبيق يفكّ هذا الحقل بلا حارس"
            )
        return
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            problems.append(f"{path}: يُنتظر كائن ووصل {_type_name(actual)}")
            return
        for key, sub in expected.items():
            if key not in actual:
                # **هذا هو العطب الذي يُنهي التطبيق.**
                problems.append(f"{path}.{key}: مفتاح ناقص")
                continue
            _check(sub, actual[key], f"{path}.{key}", problems)
        for extra in set(actual) - set(expected):
            problems.append(f"{path}.{extra}: مفتاح زائد ليس في العقد")
        return

    if isinstance(expected, list):
        if not isinstance(actual, list):
            problems.append(f"{path}: يُنتظر قائمة ووصل {_type_name(actual)}")
            return
        # القائمة الفارغة مقبولة: العقد يصف شكل العنصر لا وجوده.
        for index, item in enumerate(actual):
            _check(expected[0], item, f"{path}[{index}]", problems)
        return

    # `nullable` في العقد تعني أن المثال كان `null` فلا نوع مُعلَناً منه.
    if expected == "nullable":
        return
    actual_type = _type_name(actual)
    if actual_type != expected:
        problems.append(f"{path}: يُنتظر {expected} ووصل {actual_type}")


SECTIONS = [
    "status", "intelligence", "decision", "risk",
    "profiles", "position", "performance", "providers",
]


@pytest.mark.parametrize("section", SECTIONS)
def test_server_section_matches_the_client_contract(section, contract, state):
    problems: list[str] = []
    _check(contract[section], state[section], section, problems)
    assert not problems, "خالف الخادمُ عقدَ التطبيق:\n  " + "\n  ".join(problems)


def test_list_sections_carry_the_contracted_element_shape(contract, state):
    """`trades` و`notifications` قائمتان — يُفحَص شكل عناصرهما إن وُجدت."""
    problems: list[str] = []
    _check(contract["trades"]["trades"], state["trades"], "trades", problems)
    _check(
        contract["notifications"]["notifications"],
        state["notifications"],
        "notifications",
        problems,
    )
    assert not problems, "\n  ".join(problems)


def test_every_contract_section_is_produced(contract, state):
    """
    قسمٌ في العقد بلا مقابل في الخادم = شاشة تُطلَب ولا تجد بيانات.
    """
    missing = set(contract) - set(state) - NOT_FROM_STATE
    assert not missing, f"أقسام في العقد لا ينتجها الخادم: {sorted(missing)}"


def test_contract_covers_every_declared_read_route():
    """
    العقد يجب أن يغطّي **كل مسار قراءة مُعلَن** — وإلا بقي مسار بلا شكل
    متّفق عليه، وهو بالضبط ما حدث.
    """
    from app.mobile.api import READ_ROUTES

    contract = _load_contract()
    for key in _META_KEYS:
        contract.pop(key, None)
    route_to_section = {
        "status": "status",
        "intelligence/latest": "intelligence",
        "decision/latest": "decision",
        "risk": "risk",
        "profiles": "profiles",
        "positions/current": "position",
        "trades": "trades",
        "performance": "performance",
        "providers/health": "providers",
        "notifications": "notifications",
        "audit/recent": "audit",
        "scan/latest": "scan",
        "market/candles": "candles",
    }
    assert set(route_to_section) == set(READ_ROUTES), (
        "تغيّرت مسارات القراءة ولم يُحدَّث الربط بالعقد."
    )
    uncovered = [s for s in route_to_section.values() if s not in contract]
    assert not uncovered, f"مسارات بلا شكل في العقد: {uncovered}"
