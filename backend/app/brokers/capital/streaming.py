"""
بث Capital.com عبر WebSocket.

الحقائق الرسمية (تُحقق 2026-08-28):
  wss://api-streaming-capital.backend-capital.com/connect
  الجلسة 10 دقائق ويجب إرسال ping للإبقاء عليها
  حد أقصى 40 أداة في الاشتراك الواحد
  الوجهات: marketData.subscribe / unsubscribe و OHLCMarketData.subscribe / unsubscribe و ping

قاعدة: الاختبارات تستعمل `MockStreamingClient` ولا تفتح أي مقبس.
كل سعر وارد يمرّ ببوابة حداثة قبل أن يصبح صالحاً لأي قرار.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

from ...clock import now_utc
from ...contracts import DataSource, Quote
from ...money import D
from .errors import CapitalMalformedResponse, CapitalTransportError
from .safety import assert_url_allowed
from .session import CapitalSession

logger = logging.getLogger(__name__)

MAX_SUBSCRIPTIONS = 40
STREAM_PING_INTERVAL = timedelta(minutes=5)
STREAM_SESSION_TTL = timedelta(minutes=10)

DESTINATION_SUBSCRIBE = "marketData.subscribe"
DESTINATION_UNSUBSCRIBE = "marketData.unsubscribe"
DESTINATION_OHLC_SUBSCRIBE = "OHLCMarketData.subscribe"
DESTINATION_OHLC_UNSUBSCRIBE = "OHLCMarketData.unsubscribe"
DESTINATION_PING = "ping"


class TooManySubscriptions(CapitalTransportError):
    pass


@dataclass(frozen=True)
class StreamQuote:
    epic: str
    bid: Decimal
    ask: Decimal
    timestamp_utc: datetime
    received_at_utc: datetime

    def age_seconds(self, at: datetime) -> float:
        return (at - self.timestamp_utc).total_seconds()

    def to_quote(self) -> Quote:
        return Quote(
            symbol=self.epic,
            bid=self.bid,
            ask=self.ask,
            last=(self.bid + self.ask) / D(2),
            timestamp_utc=self.timestamp_utc,
            source=DataSource.REALTIME,
            received_at_utc=self.received_at_utc,
        )

    @staticmethod
    def parse(payload: dict, *, received_at: datetime) -> "StreamQuote":
        body = payload.get("payload", payload)
        epic = body.get("epic")
        bid = body.get("bid")
        ask = body.get("ofr", body.get("ask", body.get("offer")))
        if epic is None or bid is None or ask is None:
            raise CapitalMalformedResponse("رسالة بث تفتقد epic أو bid أو ask.")
        raw_ts = body.get("timestamp")
        if raw_ts is None:
            timestamp = received_at
        else:
            timestamp = datetime.fromtimestamp(float(raw_ts) / 1000.0, tz=received_at.tzinfo)
        return StreamQuote(
            epic=str(epic),
            bid=D(bid),
            ask=D(ask),
            timestamp_utc=timestamp,
            received_at_utc=received_at,
        )


class StreamingClient(ABC):
    """عقد البث. يُستبدل في الاختبارات بنسخة بلا شبكة."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def subscribe(self, epics: list[str], *, ohlc: bool = False) -> None: ...

    @abstractmethod
    def unsubscribe(self, epics: list[str], *, ohlc: bool = False) -> None: ...

    @abstractmethod
    def ping(self) -> bool: ...

    @property
    @abstractmethod
    def connected(self) -> bool: ...


@dataclass
class StreamingState:
    """
    حالة البث المشتركة بين النسخة الحقيقية والوهمية:
    الاشتراكات، آخر سعر لكل أداة، وبوابة الحداثة.
    """

    max_age_seconds: int = 60
    subscriptions: set[str] = field(default_factory=set)
    latest: dict[str, StreamQuote] = field(default_factory=dict)
    reconnects: int = 0
    last_ping_utc: Optional[datetime] = None

    def record(self, quote: StreamQuote) -> None:
        self.latest[quote.epic.upper()] = quote

    def fresh_quote(self, epic: str, *, at: Optional[datetime] = None) -> Optional[StreamQuote]:
        """يعيد السعر فقط إن كان حديثاً. سعر قديم = لا سعر."""
        at = at or now_utc()
        quote = self.latest.get(epic.upper())
        if quote is None:
            return None
        if quote.age_seconds(at) > self.max_age_seconds:
            return None
        return quote

    def add_subscriptions(self, epics: list[str]) -> None:
        proposed = self.subscriptions | {e.upper() for e in epics}
        if len(proposed) > MAX_SUBSCRIPTIONS:
            raise TooManySubscriptions(
                f"عدد الاشتراكات {len(proposed)} يتجاوز الحد الرسمي {MAX_SUBSCRIPTIONS}."
            )
        self.subscriptions = proposed


@dataclass
class MockStreamingClient(StreamingClient):
    """
    عميل بث للاختبارات. لا يفتح أي مقبس ولا يلمس الشبكة.
    يسمح بمحاكاة القطع وإعادة الاتصال ووصول أسعار قديمة.
    """

    state: StreamingState = field(default_factory=StreamingState)
    _connected: bool = field(default=False, init=False)
    fail_on_connect: bool = False
    sent: list[dict] = field(default_factory=list)

    def connect(self) -> None:
        if self.fail_on_connect:
            raise CapitalTransportError("تعذّر فتح قناة البث (محاكاة).")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def drop(self) -> None:
        """محاكاة قطع غير متوقع."""
        self._connected = False

    def reconnect(self) -> None:
        self.state.reconnects += 1
        self.connect()
        if self.state.subscriptions:
            self.subscribe(sorted(self.state.subscriptions))

    def subscribe(self, epics: list[str], *, ohlc: bool = False) -> None:
        if not self._connected:
            raise CapitalTransportError("لا يمكن الاشتراك وقناة البث مغلقة.")
        self.state.add_subscriptions(epics)
        self.sent.append(
            {
                "destination": DESTINATION_OHLC_SUBSCRIBE if ohlc else DESTINATION_SUBSCRIBE,
                "epics": [e.upper() for e in epics],
            }
        )

    def unsubscribe(self, epics: list[str], *, ohlc: bool = False) -> None:
        self.state.subscriptions -= {e.upper() for e in epics}
        self.sent.append(
            {
                "destination": DESTINATION_OHLC_UNSUBSCRIBE if ohlc else DESTINATION_UNSUBSCRIBE,
                "epics": [e.upper() for e in epics],
            }
        )

    def ping(self) -> bool:
        if not self._connected:
            return False
        self.state.last_ping_utc = now_utc()
        self.sent.append({"destination": DESTINATION_PING})
        return True

    def feed(self, payload: dict, *, received_at: Optional[datetime] = None) -> StreamQuote:
        """حقن رسالة سعر كما لو وصلت من الوسيط."""
        quote = StreamQuote.parse(payload, received_at=received_at or now_utc())
        self.state.record(quote)
        return quote

    @property
    def connected(self) -> bool:
        return self._connected


@dataclass
class CapitalStreamingClient(StreamingClient):
    """
    العميل الحقيقي. يُستعمل فقط بعد تأكيد المالكة وضد بيئة Demo.
    الاستيراد كسول حتى لا تُحمَّل مكتبة الشبكة في الاختبارات.
    """

    session: CapitalSession
    state: StreamingState = field(default_factory=StreamingState)
    _ws = None

    def _url(self) -> str:
        url = self.session.environment.ws_url
        assert_url_allowed(url.replace("wss://", "https://"))
        return url

    def connect(self) -> None:  # pragma: no cover - يتطلب شبكة حقيقية
        import websockets.sync.client as ws_client

        self.session.ensure_session()
        self._ws = ws_client.connect(self._url())

    def disconnect(self) -> None:  # pragma: no cover
        if self._ws is not None:
            self._ws.close()
            self._ws = None

    def _send(self, destination: str, payload: dict) -> None:  # pragma: no cover
        if self._ws is None:
            raise CapitalTransportError("قناة البث غير مفتوحة.")
        tokens = self.session.ensure_session()
        self._ws.send(
            json.dumps(
                {
                    "destination": destination,
                    "correlationId": str(int(now_utc().timestamp() * 1000)),
                    "cst": tokens.cst,
                    "securityToken": tokens.security_token,
                    "payload": payload,
                }
            )
        )

    def subscribe(self, epics: list[str], *, ohlc: bool = False) -> None:  # pragma: no cover
        self.state.add_subscriptions(epics)
        self._send(
            DESTINATION_OHLC_SUBSCRIBE if ohlc else DESTINATION_SUBSCRIBE, {"epics": epics}
        )

    def unsubscribe(self, epics: list[str], *, ohlc: bool = False) -> None:  # pragma: no cover
        self.state.subscriptions -= {e.upper() for e in epics}
        self._send(
            DESTINATION_OHLC_UNSUBSCRIBE if ohlc else DESTINATION_UNSUBSCRIBE, {"epics": epics}
        )

    def ping(self) -> bool:  # pragma: no cover
        try:
            self._send(DESTINATION_PING, {})
            self.state.last_ping_utc = now_utc()
            return True
        except CapitalTransportError:
            return False

    @property
    def connected(self) -> bool:  # pragma: no cover
        return self._ws is not None
