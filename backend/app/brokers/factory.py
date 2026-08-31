"""
Broker factory — القفل الأول على المال الحقيقي.

لا يوجد أي مسار يعيد محوّلاً حقيقياً تلقائياً.

## أوضاع الوسيط

    MOCK           وسيط وهمي في الذاكرة. لا شبكة، لا حساب، لا مال.
    IBKR_PAPER     IBKR تجريبي.
    IBKR_LIVE      IBKR حقيقي — يتطلب LIVE_TRADING + ملف موافقة.
    CAPITAL_DEMO   Capital.com تجريبي — قراءة فقط، وقفل التنفيذ مغلق.
    CAPITAL_LIVE   Capital.com حقيقي — قراءة فقط أيضاً، ويتطلب فوق ذلك
                   `safety.LIVE_API_ENABLED = True` وهو ثابت مصدري لا يُفتح
                   بمتغيّر بيئة.

## لماذا CAPITAL_LIVE «قراءة فقط» رغم أنه حقيقي

أوضاع كابيتال تبني `GuardedTransport` بقفل تنفيذ **مغلق**، فكل طلب مُعدِّل
(POST على المراكز، PUT، PATCH، DELETE) يُرفض في الناقل قبل مغادرته العملية.
الاتصال بحساب حقيقي لقراءة السعر والرصيد لا يعني القدرة على إرسال أمر:
فتح التنفيذ قرار منفصل، بموافقة موثّقة، ولا يمرّ من هنا.
"""
from __future__ import annotations

from ..config import Settings, get_settings
from ..secretstore.provider import SecretProvider, build_secret_provider
from .base import BrokerAdapter
from .capital.adapter import CapitalComAdapter
from .capital.endpoints import CapitalEnvironment
from .capital.safety import ExecutionLock
from .capital.session import CapitalSession
from .capital.transport import GuardedTransport, HttpxTransport
from .ibkr import IBKRLiveAdapter, IBKRPaperAdapter
from .mock import MockBrokerAdapter

#: أوضاع كابيتال وبيئاتها.
_CAPITAL_ENVIRONMENTS = {
    "CAPITAL_DEMO": CapitalEnvironment.DEMO,
    "CAPITAL_LIVE": CapitalEnvironment.LIVE,
}


def build_capital_adapter(
    environment: CapitalEnvironment,
    *,
    secrets: SecretProvider,
    execution_lock: ExecutionLock | None = None,
) -> CapitalComAdapter:
    """
    يبني محوّل كابيتال بقفل تنفيذ **مغلق افتراضياً**.

    القفل المُمرَّر يُشارك بين الناقل والمحوّل — طبقةٌ واحدة لا طبقتان،
    وإلا صار فتح إحداهما دون الأخرى ممكناً بلا أن يظهر ذلك في أي اختبار.
    """
    lock = execution_lock or ExecutionLock.locked()
    transport = GuardedTransport(inner=HttpxTransport(), execution_lock=lock)
    session = CapitalSession(
        transport=transport, secrets=secrets, environment=environment
    )
    return CapitalComAdapter(session=session, execution_lock=lock)


def build_broker(
    settings: Settings | None = None,
    *,
    secrets: SecretProvider | None = None,
    execution_lock: ExecutionLock | None = None,
) -> BrokerAdapter:
    settings = settings or get_settings()

    if settings.broker_mode == "MOCK":
        return MockBrokerAdapter()

    if settings.broker_mode == "IBKR_PAPER":
        return IBKRPaperAdapter(
            host=settings.ibkr_host, port=settings.ibkr_port,
            client_id=settings.ibkr_client_id, account_id=settings.ibkr_account_id,
        )

    if settings.broker_mode == "IBKR_LIVE":
        settings.assert_live_allowed()
        return IBKRLiveAdapter(
            host=settings.ibkr_host, port=settings.ibkr_port,
            client_id=settings.ibkr_client_id, account_id=settings.ibkr_account_id,
        )

    if settings.broker_mode in _CAPITAL_ENVIRONMENTS:
        # يرفع LiveApiBlocked لو طُلب الحقيقي والقفل المصدري مغلق.
        # الفحص هنا كي يظهر الخطأ عند الإقلاع بسبب واضح، لا عند أول طلب.
        settings.assert_capital_allowed()
        return build_capital_adapter(
            _CAPITAL_ENVIRONMENTS[settings.broker_mode],
            secrets=secrets or build_secret_provider(
                env_file=settings.secrets_file, allow_process_env=False
            ),
            execution_lock=execution_lock,
        )

    raise ValueError(f"BROKER_MODE غير معروف: {settings.broker_mode}")
