"""
PROVIDERS — طبقة المزوّدات الإنتاجية.

## ثلاث قواعد تحكم هذه الحزمة كلها

1. **«لا أعرف» ليست «لا يوجد».** كل استدعاء يعيد حالة صريحة من تسع، وقائمة
   فارغة بلا حالة `FRESH` تعني الجهل لا العدم.

2. **لا مزوّد يستطيع أن ينفّذ.** لا وحدة هنا تستورد خدمة تنفيذ ولا موجّه
   أوامر ولا محوّل وسيط — مفروض باختبار AST على كل ملف.

3. **الأسرار لا تُغادر.** المفاتيح تُمرَّر في سلسلة الاستعلام لدى هذه
   المزوّدات، فكل عنوان يخرج من `http.py` منقّى، وكل استثناء يُعاد بنصّ منقّى.

## المزوّدون

| المزوّد | يحتاج مفتاحاً؟ |
|---|---|
| `FmpEconomicCalendarProvider` | `FMP_API_KEY` — والخطة غير مؤكَّدة |
| `FinnhubForexNewsProvider` | `FINNHUB_API_KEY` |
| `FredMacroDataProvider` | `FRED_API_KEY` |
| `EcbMacroDataProvider` | **لا** — وصول مفتوح |
| `OfficialSourceProvider` | لا — يحتاج تغذية مضبوطة |
| `CompositeVerifiedNewsProvider` | يرث من مصادره |
| `CompositeMacroDataProvider` | يرث من مصادره |

Capital.com يبقى `MarketDataProvider` وحده، ولا يظهر في هذه الحزمة.
"""
from .cache import ProviderCache, cache_key, deduplicate
from .classification import Classification, classify_event
from .composite import (
    CompositeMacroDataProvider,
    CompositeVerifiedNewsProvider,
    MacroAssessment,
    MacroBias,
    OfficialRelease,
    OfficialSourceProvider,
    VerifiedNewsRecord,
)
from .ecb_macro import EcbMacroDataProvider
from .finnhub_news import FinnhubForexNewsProvider
from .fmp_calendar import FmpEconomicCalendarProvider
from .fred_macro import FredMacroDataProvider
from .health import ProviderAuditEvent, ProviderHealth, ProviderHealthRegistry
from .http import ProviderTransport, RateLimiter, redact_url
from .provenance import LicenseClass, Provenance, build_provenance
from .results import ProviderResult, ProviderResultState
from .verification import DomainPolicy, VerificationLevel, classify_news

#: أسماء بيئة الاعتمادات. **لا يُطلب أي منها في المحادثة** — تُضبَط محلياً.
PROVIDER_CREDENTIALS: tuple[str, ...] = (
    "FMP_API_KEY",
    "FINNHUB_API_KEY",
    "FRED_API_KEY",
)

__all__ = [
    "PROVIDER_CREDENTIALS",
    "ProviderResult", "ProviderResultState",
    "Provenance", "build_provenance", "LicenseClass",
    "ProviderTransport", "RateLimiter", "redact_url",
    "ProviderCache", "cache_key", "deduplicate",
    "ProviderHealth", "ProviderHealthRegistry", "ProviderAuditEvent",
    "Classification", "classify_event",
    "DomainPolicy", "VerificationLevel", "classify_news",
    "FmpEconomicCalendarProvider",
    "FinnhubForexNewsProvider",
    "FredMacroDataProvider",
    "EcbMacroDataProvider",
    "OfficialSourceProvider", "OfficialRelease",
    "CompositeVerifiedNewsProvider", "VerifiedNewsRecord",
    "CompositeMacroDataProvider", "MacroAssessment", "MacroBias",
]
