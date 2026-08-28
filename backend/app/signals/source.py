"""
مصادر الإشارات — طبقة اختيارية أمام محرك الاستراتيجية.

موقف TradingView في هذا الإصدار (انظر docs/TRADINGVIEW_POSITION.md):
  * TradingView **ليست** محرّك التنفيذ.
  * لا اشتراك مدفوع مطلوب، ولا إرسال أوامر عبرها، ولا Pine Script منفّذ.
  * لا يعتمد عليها وقف الخسارة ولا جني الأرباح ولا الخروج الطارئ.

هذه الوحدة تبني **صندوق وارد للإشارات** فقط: أي إشارة خارجية تدخل الصندوق،
ثم تمرّ إجبارياً عبر محرك الاستراتيجية ثم محرك المخاطر ثم Kill Switch.
لا يوجد مسار من webhook إلى الوسيط مباشرة، وهذا قيد بنيوي:
هذا الملف لا يستورد أي محوّل وسيط ولا خدمة تنفيذ.
"""
from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from ..clock import now_utc
from ..secretstore.redaction import redact

MAX_SIGNAL_AGE = timedelta(minutes=2)


class SignalRejection(str, Enum):
    DISABLED = "SIGNAL_SOURCE_DISABLED"
    BAD_SIGNATURE = "BAD_SIGNATURE"
    STALE = "STALE_ALERT"
    DUPLICATE = "DUPLICATE_ALERT"
    MALFORMED = "MALFORMED_ALERT"
    INSTRUMENT_NOT_ALLOWED = "INSTRUMENT_NOT_ALLOWED"
    CONTAINS_CREDENTIALS = "ALERT_CONTAINS_CREDENTIALS"


@dataclass(frozen=True)
class InboundSignal:
    """
    إشارة خارجية **خام**. ليست قراراً ولا أمراً — مجرد اقتراح يحتاج تحقّقاً.
    """

    source: str
    symbol: str
    payload: dict
    received_at_utc: datetime
    alert_id: str
    alert_time_utc: Optional[datetime] = None

    def digest(self) -> str:
        return hashlib.sha256(
            f"{self.source}|{self.symbol}|{self.alert_id}".encode()
        ).hexdigest()[:32]


@dataclass(frozen=True)
class SignalAdmission:
    accepted: bool
    reason_code: Optional[str]
    reason_ar: str
    signal: Optional[InboundSignal] = None


class SignalSource(ABC):
    """عقد مصدر الإشارات. معطّل افتراضياً في كل التنفيذات."""

    name: str = "abstract"
    enabled: bool = False

    @abstractmethod
    def admit(self, raw: dict, *, now: Optional[datetime] = None) -> SignalAdmission: ...


#: مفاتيح لا يجوز أن تظهر في أي تنبيه خارجي إطلاقاً.
FORBIDDEN_KEYS = frozenset(
    {
        "apikey", "api_key", "password", "cst", "x-security-token", "securitytoken",
        "identifier", "token", "secret", "capital_api_key", "capital_api_password",
    }
)


@dataclass
class SignalInbox:
    """
    صندوق الوارد. يمنع التكرار ويحتفظ بسجل قابل للتدقيق.
    """

    seen: set[str] = field(default_factory=set)
    accepted: list[InboundSignal] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def is_duplicate(self, signal: InboundSignal) -> bool:
        return signal.digest() in self.seen

    def record_accepted(self, signal: InboundSignal) -> None:
        self.seen.add(signal.digest())
        self.accepted.append(signal)

    def record_rejected(self, reason_code: str, reason_ar: str) -> None:
        self.rejected.append((reason_code, reason_ar))


@dataclass
class TradingViewWebhookSource(SignalSource):
    """
    مصدر تنبيهات TradingView عبر webhook.

    **معطّل افتراضياً** (`enabled=False`) ولا يوجد مسار يفعّله تلقائياً.
    حتى عند تفعيله، كل ما يفعله هو إدخال اقتراح إلى الصندوق.
    """

    shared_secret: Optional[str] = None
    allowed_symbols: frozenset[str] = frozenset({"EURUSD"})
    inbox: SignalInbox = field(default_factory=SignalInbox)
    enabled: bool = False
    max_age: timedelta = MAX_SIGNAL_AGE
    name: str = "tradingview-webhook"

    def _verify_signature(self, raw: dict) -> bool:
        if not self.shared_secret:
            return False
        provided = str(raw.get("signature", ""))
        body = str(raw.get("alert_id", "")) + str(raw.get("symbol", ""))
        expected = hmac.new(
            self.shared_secret.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(provided, expected)

    def admit(self, raw: dict, *, now: Optional[datetime] = None) -> SignalAdmission:
        now = now or now_utc()

        if not self.enabled:
            self.inbox.record_rejected(
                SignalRejection.DISABLED.value, "مصدر TradingView معطّل افتراضياً."
            )
            return SignalAdmission(
                False,
                SignalRejection.DISABLED.value,
                "مصدر إشارات TradingView معطّل. تفعيله قرار صريح موثّق، وحتى بعده "
                "لا يرسل شيئاً للوسيط.",
            )

        lowered = {str(k).lower().replace("-", "_") for k in raw}
        if lowered & {k.replace("-", "_") for k in FORBIDDEN_KEYS}:
            self.inbox.record_rejected(
                SignalRejection.CONTAINS_CREDENTIALS.value, "تنبيه يحتوي حقول اعتماد."
            )
            return SignalAdmission(
                False,
                SignalRejection.CONTAINS_CREDENTIALS.value,
                "التنبيه يحتوي حقولاً تشبه الاعتمادات — مرفوض ولن يُسجَّل محتواه.",
            )

        alert_id = str(raw.get("alert_id", "")).strip()
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not alert_id or not symbol:
            self.inbox.record_rejected(SignalRejection.MALFORMED.value, "تنبيه ناقص الحقول.")
            return SignalAdmission(
                False, SignalRejection.MALFORMED.value, "تنبيه ناقص: يلزم alert_id و symbol."
            )

        if not self._verify_signature(raw):
            self.inbox.record_rejected(SignalRejection.BAD_SIGNATURE.value, "توقيع غير صالح.")
            return SignalAdmission(
                False, SignalRejection.BAD_SIGNATURE.value, "توقيع التنبيه غير صالح — مرفوض."
            )

        if symbol not in self.allowed_symbols:
            self.inbox.record_rejected(
                SignalRejection.INSTRUMENT_NOT_ALLOWED.value, f"أداة غير مسموحة: {symbol}"
            )
            return SignalAdmission(
                False,
                SignalRejection.INSTRUMENT_NOT_ALLOWED.value,
                f"الأداة {symbol} خارج القائمة المسموحة لمصدر الإشارات.",
            )

        alert_time = raw.get("time_utc")
        parsed_time: Optional[datetime] = None
        if alert_time:
            try:
                parsed_time = datetime.fromisoformat(str(alert_time).replace("Z", "+00:00"))
            except ValueError:
                self.inbox.record_rejected(SignalRejection.MALFORMED.value, "طابع زمني غير صالح.")
                return SignalAdmission(
                    False, SignalRejection.MALFORMED.value, "طابع زمني غير صالح في التنبيه."
                )
            if parsed_time.tzinfo is None:
                self.inbox.record_rejected(SignalRejection.MALFORMED.value, "طابع زمني بلا منطقة.")
                return SignalAdmission(
                    False, SignalRejection.MALFORMED.value, "طابع زمني بلا منطقة زمنية."
                )
            if (now - parsed_time) > self.max_age:
                self.inbox.record_rejected(SignalRejection.STALE.value, "تنبيه قديم.")
                return SignalAdmission(
                    False,
                    SignalRejection.STALE.value,
                    f"عمر التنبيه يتجاوز {self.max_age.total_seconds():.0f} ثانية — مرفوض.",
                )

        signal = InboundSignal(
            source=self.name,
            symbol=symbol,
            payload=redact(dict(raw)),
            received_at_utc=now,
            alert_id=alert_id,
            alert_time_utc=parsed_time,
        )
        if self.inbox.is_duplicate(signal):
            self.inbox.record_rejected(SignalRejection.DUPLICATE.value, "تنبيه مكرر.")
            return SignalAdmission(
                False, SignalRejection.DUPLICATE.value, "تنبيه مكرر — مرفوض بلا معالجة."
            )

        self.inbox.record_accepted(signal)
        return SignalAdmission(
            True,
            None,
            "قُبل التنبيه في صندوق الوارد. سيمر إجبارياً عبر محرك الاستراتيجية "
            "ثم محرك المخاطر ثم Kill Switch، ولن يصل الوسيط مباشرة.",
            signal,
        )
