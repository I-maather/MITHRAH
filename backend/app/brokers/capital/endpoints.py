"""
Capital.com Public API — العناوين والمسارات، وتصنيفها إلى قراءة/تعديل.

المصدر الرسمي: https://open-api.capital.com/ (تُحقق 2026-08-28)

قاعدة صارمة: كل مسار يجب أن يكون مصنّفاً هنا. مسار غير مصنّف يُعامل
على أنه **مُعدِّل** ويُرفض. الافتراض الآمن هو المنع لا السماح.
"""
from __future__ import annotations

from enum import Enum
from urllib.parse import urlparse

DEMO_BASE_URL = "https://demo-api-capital.backend-capital.com"
LIVE_BASE_URL = "https://api-capital.backend-capital.com"

DEMO_WS_URL = "wss://api-streaming-capital.backend-capital.com/connect"
LIVE_WS_URL = "wss://api-streaming-capital.backend-capital.com/connect"

API_PREFIX = "/api/v1"


class CapitalEnvironment(str, Enum):
    DEMO = "demo"
    LIVE = "live"

    @property
    def base_url(self) -> str:
        return DEMO_BASE_URL if self is CapitalEnvironment.DEMO else LIVE_BASE_URL

    @property
    def ws_url(self) -> str:
        return DEMO_WS_URL if self is CapitalEnvironment.DEMO else LIVE_WS_URL


# ---------------------------------------------------------------------------
# المسارات
# ---------------------------------------------------------------------------

PATH_TIME = f"{API_PREFIX}/time"
PATH_PING = f"{API_PREFIX}/ping"
PATH_ENCRYPTION_KEY = f"{API_PREFIX}/session/encryptionKey"
PATH_SESSION = f"{API_PREFIX}/session"
PATH_ACCOUNTS = f"{API_PREFIX}/accounts"
PATH_ACCOUNT_PREFERENCES = f"{API_PREFIX}/accounts/preferences"
PATH_ACCOUNT_TOPUP = f"{API_PREFIX}/accounts/topUp"
PATH_HISTORY_ACTIVITY = f"{API_PREFIX}/history/activity"
PATH_HISTORY_TRANSACTIONS = f"{API_PREFIX}/history/transactions"
PATH_MARKETS = f"{API_PREFIX}/markets"
PATH_MARKET_NAVIGATION = f"{API_PREFIX}/marketnavigation"
PATH_PRICES = f"{API_PREFIX}/prices"
PATH_POSITIONS = f"{API_PREFIX}/positions"
#: دفترُ المعاملات — الصفقات المغلقة ونتائجها المحقّقة.
#: يُنادى بـ`?lastPeriod=<ثوانٍ>`؛ وصيغة `from/to` تعمل بشرط `YYYY-MM-DDTHH:MM:SS` بلا لاحقة منطقة.
PATH_TRANSACTIONS = f"{API_PREFIX}/history/transactions"
PATH_WORKING_ORDERS = f"{API_PREFIX}/workingorders"
PATH_CONFIRMS = f"{API_PREFIX}/confirms"


def market_path(epic: str) -> str:
    return f"{PATH_MARKETS}/{epic}"


def prices_path(epic: str) -> str:
    return f"{PATH_PRICES}/{epic}"


def position_path(deal_id: str) -> str:
    return f"{PATH_POSITIONS}/{deal_id}"


def working_order_path(deal_id: str) -> str:
    return f"{PATH_WORKING_ORDERS}/{deal_id}"


def confirm_path(deal_reference: str) -> str:
    return f"{PATH_CONFIRMS}/{deal_reference}"


# ---------------------------------------------------------------------------
# التصنيف
# ---------------------------------------------------------------------------

#: (method, path-prefix) لكل عملية قراءة مسموحة.
READ_ONLY_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", PATH_TIME),
        ("GET", PATH_PING),
        ("GET", PATH_ENCRYPTION_KEY),
        ("GET", PATH_SESSION),
        ("GET", PATH_ACCOUNTS),
        ("GET", PATH_ACCOUNT_PREFERENCES),
        ("GET", PATH_HISTORY_ACTIVITY),
        ("GET", PATH_HISTORY_TRANSACTIONS),
        ("GET", PATH_MARKETS),
        ("GET", PATH_MARKET_NAVIGATION),
        ("GET", PATH_PRICES),
        ("GET", PATH_POSITIONS),
        ("GET", PATH_WORKING_ORDERS),
        ("GET", PATH_CONFIRMS),
    }
)

#: عمليات تُنشئ أو تعدّل أو تحذف شيئاً عند الوسيط.
MUTATING_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", PATH_POSITIONS),
        ("PUT", PATH_POSITIONS),
        ("DELETE", PATH_POSITIONS),
        ("POST", PATH_WORKING_ORDERS),
        ("PUT", PATH_WORKING_ORDERS),
        ("DELETE", PATH_WORKING_ORDERS),
        ("PUT", PATH_ACCOUNT_PREFERENCES),
        ("POST", PATH_ACCOUNT_TOPUP),
        ("PUT", PATH_SESSION),
    }
)

#: POST /session ينشئ جلسة لا صفقة — مسموح، لكنه ليس قراءة محضة.
SESSION_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", PATH_SESSION),
        ("DELETE", PATH_SESSION),
    }
)


def normalise(method: str, path: str) -> tuple[str, str]:
    method_up = method.upper().strip()
    clean = path.split("?", 1)[0].rstrip("/")
    return method_up, clean


def _matches(operations: frozenset[tuple[str, str]], method: str, path: str) -> bool:
    method_up, clean = normalise(method, path)
    for op_method, op_path in operations:
        if op_method != method_up:
            continue
        if clean == op_path or clean.startswith(op_path + "/"):
            return True
    return False


def is_read_only(method: str, path: str) -> bool:
    return _matches(READ_ONLY_OPERATIONS, method, path)


def is_mutating(method: str, path: str) -> bool:
    """
    يعيد True لكل ما ليس قراءة صريحة أو عملية جلسة معروفة.
    مسار غير معروف ⇒ يُعتبر مُعدِّلاً (fail closed).
    """
    if _matches(MUTATING_OPERATIONS, method, path):
        return True
    if is_read_only(method, path):
        return False
    if _matches(SESSION_OPERATIONS, method, path):
        return False
    return True


def is_live_url(url: str) -> bool:
    """يعتبر أي مضيف غير مضيف الـDemo مضيفاً حقيقياً — fail closed."""
    if not url:
        return False
    parsed = urlparse(url if "//" in url else f"https://{url}")
    host = (parsed.netloc or parsed.path).lower()
    if not host:
        return False
    demo_host = urlparse(DEMO_BASE_URL).netloc.lower()
    streaming_host = urlparse(DEMO_WS_URL.replace("wss://", "https://")).netloc.lower()
    return host not in {demo_host, streaming_host}
