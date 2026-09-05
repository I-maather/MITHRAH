from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.audit.log import AuditLog, InMemoryAuditStore
from app.brokers.mock import MockBehaviour, MockBrokerAdapter, make_quote
from app.contracts import AccountKind, Balances, Bar, ClientClassification, DataSource, TradingPermissions
from app.execution.orders import ExecutionService, IdempotencyGuard
from app.killswitch.engine import KillSwitch
from app.money import D
from app.risk.constitution import RiskLimits
from app.risk.costs import IBKR_PRO_TIERED_US_STOCK, CostAssumptions
from app.risk.engine import RiskEngine, SessionRiskState

UTC = timezone.utc

# منتصف جلسة نيويورك يوم ثلاثاء عادي (ليس عطلة): 2026-09-15 15:00 UTC = 11:00 صباحاً NY
MID_SESSION = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return MID_SESSION


@pytest.fixture
def audit() -> AuditLog:
    return AuditLog(InMemoryAuditStore())


@pytest.fixture
def limits() -> RiskLimits:
    return RiskLimits.from_baseline(D("150.00"))


@pytest.fixture
def big_limits() -> RiskLimits:
    return RiskLimits.from_baseline(D("5000.00"))


@pytest.fixture
def assumptions() -> CostAssumptions:
    return CostAssumptions(
        spread_abs=D("0.01"),
        slippage_pct_per_leg=D("0.0005"),
        currency_conversion_pct=D("0"),
    )


@pytest.fixture
def schedule():
    return IBKR_PRO_TIERED_US_STOCK


def make_balances(cash: str, account_id: str = "DU0000000", at: datetime = MID_SESSION) -> Balances:
    return Balances(
        account_id=account_id,
        total_cash=D(cash),
        settled_cash=D(cash),
        unsettled_cash=D("0"),
        committed_cash=D("0"),
        net_liquidation=D(cash),
        as_of_utc=at,
    )


def make_permissions(at: datetime = MID_SESSION, **overrides) -> TradingPermissions:
    base = dict(
        account_id="DU0000000",
        account_kind=AccountKind.CASH,
        classification=ClientClassification.RETAIL,
        us_stocks=True,
        fractional_enabled=True,
        as_of_utc=at,
    )
    base.update(overrides)
    return TradingPermissions(**base)


def make_state(**overrides) -> SessionRiskState:
    base = dict(
        baseline_equity=D("150.00"),
        current_equity=D("150.00"),
        realized_pnl_today=D("0"),
        realized_pnl_week=D("0"),
        unrealized_pnl=D("0"),
        open_positions=0,
        entry_orders_today=0,
        consecutive_losses=0,
    )
    base.update(overrides)
    return SessionRiskState(**base)


def uptrend_bars(symbol: str = "SPY", n: int = 60, start: Decimal = D("600.00")) -> list[Bar]:
    """
    شموع صاعدة اصطناعية تنتهي بارتداد يلامس SMA10 ثم يُغلق فوقه —
    أي بالضبط شرط دخول TREND_PULLBACK.
    """
    bars: list[Bar] = []
    price = start
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    for i in range(n):
        price = price + D("1.50")
        bars.append(
            Bar(
                symbol=symbol,
                start_utc=t0 + timedelta(days=i),
                open=price - D("0.50"),
                high=price + D("1.00"),
                low=price - D("1.00"),
                close=price,
                volume=D("1000000"),
                source=DataSource.HISTORICAL,
            )
        )
    # آخر شمعة: ارتداد يلامس SMA10 (أدنى من المتوسط) ثم إغلاق فوقه
    closes = [b.close for b in bars]
    fast = sum(closes[-10:], Decimal("0")) / Decimal(10)
    last = bars[-1]
    bars[-1] = Bar(
        symbol=symbol,
        start_utc=last.start_utc,
        open=last.open,
        high=last.close + D("0.50"),
        low=fast - D("2.00"),
        close=fast + D("2.00"),
        volume=last.volume,
        source=DataSource.HISTORICAL,
    )
    return bars


@pytest.fixture
def broker(now) -> MockBrokerAdapter:
    b = MockBrokerAdapter(behaviour=MockBehaviour(stop_on_fractional_supported=True))
    b.connect()
    b.balances = make_balances("150.00", at=now)
    b.permissions = make_permissions(at=now)
    b.set_quote(make_quote("SPY", "639.99", "640.00", at=now, source=DataSource.REALTIME))
    return b


@pytest.fixture
def execution(broker, audit) -> ExecutionService:
    return ExecutionService(broker=broker, audit=audit, guard=IdempotencyGuard())


@pytest.fixture
def kill_switch() -> KillSwitch:
    return KillSwitch()


@pytest.fixture
def risk_engine(limits) -> RiskEngine:
    return RiskEngine(limits)


# ---------------------------------------------------------------------------
# عزلُ ملف الإيقاف المحلي عن ملف التشغيل
# ---------------------------------------------------------------------------
#
# `/api/trading/resume` صار يكتب قراره على القرص كي يعيش بعد إعادة التشغيل.
# وبلا عزلٍ يكتب فحصٌ في ملفِ التشغيل نفسه، فيقرأه الفحص التالي ويبدأ «غير
# موقوف» — تسرّبُ حالةٍ بين الفحوص عبر القرص، يعبر العمليات ولا يظهر إلا
# بترتيبٍ معيّن. (سقط عليه فحصان يوم كُتبت الميزة.)

@pytest.fixture(autouse=True)
def _isolate_local_pause(tmp_path, monkeypatch):
    from app.runtime.local_pause import PATH_ENV_VAR

    monkeypatch.setenv(PATH_ENV_VAR, str(tmp_path / "local-pause.json"))
    yield

# ---------------------------------------------------------------------------
# مصادقةُ مجال `/api` في الاختبارات
# ---------------------------------------------------------------------------
#
# حارسُ المجال (`app/api/auth.py`) وسيطٌ يلتقط كلَّ ما تحت `/api`، وهو ما
# نريده: لا مسارَ يُنسى. لكنّ ذلك يعني أنّ كلَّ اختبارٍ يستدعي مساراً كان
# سيحتاج ترويسةً — مئاتُ المواضع، وكلُّها تختبر منطق المسار لا المصادقة.
#
# **والحلّ ليس ثقباً في الحارس.** لا علمَ في شيفرة الإنتاج تقول «هذه
# اختبارات فافتح»؛ فمفتاحٌ كهذا يُشحَن يوماً. بل تُصادِق حزمةُ الاختبارات
# نفسَها: تقدّم رمزاً وتقدّمه، تماماً كما يفعل مستدعٍ حقيقيّ.
#
# ومن أراد فحصَ الحارس نفسه يضع `pytestmark = pytest.mark.raw_api` فيُترَك
# مجالُه بلا مصادقة — وهو ما يفعله `test_no_api_route_is_open.py`.

_TEST_API_TOKEN = "conftest-token-not-a-real-secret"


@pytest.fixture(autouse=True)
def _api_authenticated(request, monkeypatch):
    if request.node.get_closest_marker("raw_api"):
        return
    monkeypatch.setattr(
        "app.api.auth._configured_token", lambda state: _TEST_API_TOKEN, raising=False
    )
    monkeypatch.setattr(
        "app.api.auth._presented", lambda req: _TEST_API_TOKEN, raising=False
    )
