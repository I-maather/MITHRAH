"""
توجيه حساب التكلفة حسب الوسيط.

النظام محايد تجاه الوسيط: Risk Engine لا يعرف IBKR ولا Capital.com،
بل يطلب «نموذج تكلفة هذا الوسيط» ويستعمل النتيجة.

نموذج IBKR يبقى كما هو دون أي تعديل، ويُستعمل للأسهم في مرحلة مستقبلية.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

from ..contracts import Broker, InstrumentDetails, StopKind
from ..money import D
from .capital_costs import (
    PROVISIONAL_EURUSD,
    CapitalComCostModel,
    CfdCostAssumptions,
    InstrumentEconomics,
    ValueProvenance,
)
from .costs import (
    IBKR_PRO_TIERED_US_STOCK,
    CommissionSchedule,
    CostAssumptions,
)


class UnsupportedBroker(RuntimeError):
    pass


@dataclass(frozen=True)
class BrokerCostBundle:
    """كل ما يحتاجه Risk Engine لتقييم تكلفة صفقة عند وسيط معيّن."""

    broker: Broker
    capital_model: Optional[CapitalComCostModel] = None
    ibkr_schedule: Optional[CommissionSchedule] = None
    ibkr_assumptions: Optional[CostAssumptions] = None

    @property
    def is_cfd(self) -> bool:
        return self.broker is Broker.CAPITAL_COM


def economics_from_instrument(
    details: InstrumentDetails, *, provenance: ValueProvenance = ValueProvenance.BROKER_DISCOVERY
) -> InstrumentEconomics:
    """
    يبني خصائص اقتصادية من تفاصيل أداة جاءت فعلاً من الوسيط.
    أي حقل جوهري ناقص يُرفض بدل استبداله بافتراض صامت.
    """
    if details.pip_size is None:
        raise UnsupportedBroker(
            f"حجم النقطة غير معروف للأداة {details.symbol} — لا يمكن حساب التكلفة."
        )
    if details.margin_factor is None:
        raise UnsupportedBroker(
            f"معامل الهامش غير معروف للأداة {details.symbol} — لا يمكن حساب الهامش."
        )
    return InstrumentEconomics(
        epic=details.epic or details.symbol,
        pip_size=details.pip_size,
        lot_size=details.lot_size or D("1"),
        min_deal_size=details.min_quantity,
        size_increment=details.quantity_increment or D("1"),
        margin_factor=details.margin_factor,
        margin_factor_unit=details.margin_factor_unit or "PERCENTAGE",
        min_stop_distance=details.min_stop_distance,
        min_guaranteed_stop_distance=details.min_guaranteed_stop_distance,
        guaranteed_stop_available=details.guaranteed_stop_available,
        quote_currency=details.quote_currency or details.currency,
        overnight_fee_rate_daily=details.overnight_fee,
        provenance=provenance,
    )


def build_cost_bundle(
    broker: Broker,
    *,
    details: Optional[InstrumentDetails] = None,
    capital_assumptions: Optional[CfdCostAssumptions] = None,
    ibkr_schedule: Optional[CommissionSchedule] = None,
    ibkr_assumptions: Optional[CostAssumptions] = None,
) -> BrokerCostBundle:
    if broker is Broker.CAPITAL_COM:
        if details is not None:
            economics = economics_from_instrument(details)
        else:
            economics = PROVISIONAL_EURUSD
        return BrokerCostBundle(
            broker=broker,
            capital_model=CapitalComCostModel(economics, capital_assumptions),
        )
    if broker in (Broker.IBKR, Broker.MOCK):
        return BrokerCostBundle(
            broker=broker,
            ibkr_schedule=ibkr_schedule or IBKR_PRO_TIERED_US_STOCK,
            ibkr_assumptions=ibkr_assumptions or CostAssumptions.default(),
        )
    raise UnsupportedBroker(f"لا يوجد نموذج تكلفة للوسيط {broker}.")


#: سجل قابل للتوسعة — إضافة وسيط ثالث لاحقاً = سطر واحد هنا + نموذجه.
COST_MODEL_BUILDERS: dict[Broker, Callable[..., BrokerCostBundle]] = {
    Broker.CAPITAL_COM: lambda **kw: build_cost_bundle(Broker.CAPITAL_COM, **kw),
    Broker.IBKR: lambda **kw: build_cost_bundle(Broker.IBKR, **kw),
    Broker.MOCK: lambda **kw: build_cost_bundle(Broker.MOCK, **kw),
}


def supported_brokers() -> tuple[Broker, ...]:
    return tuple(COST_MODEL_BUILDERS)
