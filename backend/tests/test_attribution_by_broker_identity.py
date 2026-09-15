"""
**نسبةُ المركز إلى قراره — بالهويّة التي أعطاها الوسيط، لا بالرمز والتوقيت.**

## العطل الذي فرض هذا الملف (قياسٌ على Demo، ٢٠٢٦-٠٩-١٥)

    أمرُ الذهب:      broker_deal_id = 00000000-6327-f86c-048f-878b0055311e
    المركزُ الناتج:  broker_deal_id = 00000000-6327-f86f-048f-878b0055311e

معرّفان مختلفان لشيئين مختلفين. و`_attribute` كان يبحث بالأوّل ثم
بـ`deal_reference` — وكلاهما لا يطابق أبداً، فخرج كلُّ مركزٍ
`UNATTRIBUTED` و`UNLINKED`، وبقيت `risk_decision_id` و`strategy_name`
فارغةً، فتعذّرت مراجعةُ جودة القرار التي يشترطها دستور المشروع.

وكانت `position_ids_of` تحسب الهويّات الصحيحة **وتُرميها** بعد التحقّق من
الوقف: نفسُ العيب الحاكم — قيمةٌ تُقاس ولا تُقرأ عند موضع الاستعمال.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, BrokerOrderRow, OrderIntentRow
from app.portfolio.ledger import _attribute

NOW = datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)
ORDER_DEAL = "00000000-6327-f86c-048f-878b0055311e"
POSITION_DEAL = "00000000-6327-f86f-048f-878b0055311e"


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed(session, *, position_ids: str | None):
    session.add(OrderIntentRow(
        idempotency_key="k1", client_order_id="MAT-test", broker="CAPITAL_COM_DEMO",
        broker_environment="demo", account_masked="****2590", epic="GOLD",
        broker_quantity=Decimal("0.12"), notional_exposure=Decimal("516.09"),
        margin_estimate=Decimal("52.00"), all_in_risk=Decimal("5.05"),
        spread_estimate=Decimal("0.30"), stop_kind="NORMAL",
        stop_distance=Decimal("42.12"), gsl_premium=Decimal("0"),
        slippage_reserve=Decimal("0.10"), strategy_name="BREAKOUT_RETEST",
        strategy_version="1.0.0", risk_constitution_version="0.3.0",
        risk_mode="VALIDATION", owner_authorization_reference="",
        market_data_timestamp_utc=NOW, risk_decision_id=None,
        symbol="GOLD", side="SELL", order_type="LMT", quantity=Decimal("0.12"),
        limit_price=Decimal("4300.78"), stop_price=Decimal("4342.90"),
        expected_fill_price=Decimal("4300.78"), max_slippage_abs=Decimal("0.50"),
        exit_plan_ar="وقفٌ وهدفٌ ثابتان.", instrument_snapshot_json="{}",
        created_at_utc=NOW,
    ))
    session.add(BrokerOrderRow(
        broker_order_id=ORDER_DEAL, deal_reference="o_abc", broker_deal_id=ORDER_DEAL,
        position_deal_ids=position_ids, client_order_id="MAT-test", symbol="GOLD",
        side="SELL", order_type="LMT", quantity=Decimal("0.12"),
        filled_quantity=Decimal("0.12"), status="FILLED", updated_at_utc=NOW,
    ))
    session.flush()


def test_the_position_is_linked_by_the_identity_the_broker_gave(session):
    """الهويّةُ المحفوظة تربط المركزَ بأمره وباستراتيجيته."""
    _seed(session, position_ids=f",{POSITION_DEAL},{ORDER_DEAL},")
    a = _attribute(session, deal_id=POSITION_DEAL, deal_reference=f"p_{POSITION_DEAL}")
    assert a.attribution == "LINKED"
    assert a.kind == "STRATEGY"
    assert a.strategy_name == "BREAKOUT_RETEST"
    assert a.client_order_id == "MAT-test"


def test_without_the_saved_identity_it_stays_unattributed(session):
    """
    يُثبّت العطلَ نفسَه: بلا الهويّة المحفوظة لا نسبة — وهو ما كان يقع
    في كلّ صفقة. فإن عاد هذا العمودُ فارغاً يوماً، يُرى الأثرُ هنا.
    """
    _seed(session, position_ids=None)
    a = _attribute(session, deal_id=POSITION_DEAL, deal_reference=f"p_{POSITION_DEAL}")
    assert a.attribution == "UNLINKED"
    assert a.kind == "UNATTRIBUTED"
    assert a.strategy_name == ""


def test_a_near_miss_identity_does_not_match(session):
    """
    المطابقةُ تامّةٌ لا جزئية: الإحاطةُ بالفواصل تمنع أن يطابق معرّفٌ
    معرّفاً آخر يحتويه كسلسلة. نسبةٌ خاطئة أسوأ من `UNATTRIBUTED`.
    """
    _seed(session, position_ids=f",{POSITION_DEAL}X,")
    a = _attribute(session, deal_id=POSITION_DEAL, deal_reference=None)
    assert a.attribution == "UNLINKED"
