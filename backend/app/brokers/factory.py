"""
Broker factory — القفل الأول على المال الحقيقي.

لا يوجد أي مسار يعيد IBKRLiveAdapter تلقائياً. الوصول إليه يتطلب:
  1. BROKER_MODE=IBKR_LIVE في البيئة، و
  2. LIVE_TRADING=true، و
  3. وجود ملف موافقة محلي موقّع زمنياً.
"""
from __future__ import annotations

from ..config import Settings, get_settings
from .base import BrokerAdapter
from .ibkr import IBKRLiveAdapter, IBKRPaperAdapter
from .mock import MockBrokerAdapter


def build_broker(settings: Settings | None = None) -> BrokerAdapter:
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

    raise ValueError(f"BROKER_MODE غير معروف: {settings.broker_mode}")
