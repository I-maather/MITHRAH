# ECB Macro — منطقة اليورو، بلا مفتاح

**الكود:** `backend/app/providers/ecb_macro.py` · **إصدار السجل:** `1.0.0`

بيانات منطقة اليورو من بوابة البنك المركزي الأوروبي. **وصول مفتوح بلا مفتاح**،
و**سياق لا إذن**.

---

## 1. العقد — مُثبَت من `data.ecb.europa.eu/help/api/data`

```
GET https://data-api.ecb.europa.eu/service/data/{flowRef}/{key}?format=jsondata
```

| البند | القيمة |
|---|---|
| `flowRef` | `AGENCY,FLOW,VERSION` — الافتراضي: كل الوكالات، آخر إصدار |
| المعاملات | `startPeriod` · `endPeriod` · `lastNObservations` · `firstNObservations` · `format` · `detail` · `updatedAfter` |
| ما نرسله | `format=jsondata` · `lastNObservations=N` · `detail=full` |
| **المفتاح** | ⛔ **لا مفتاح مطلوب** — `CREDENTIAL_NAME` يساوي `None`، ويوجد اختبار يثبت ذلك |
| المضيف القديم | `sdw-wsrest.ecb.europa.eu` — **مهجور منذ 2021**، ولا يظهر في أي طلب (مُختبَر) |
| الحد المحلي | 30 استدعاءً في الدقيقة — محافظ |
| الرخصة | `PUBLIC_OFFICIAL` |

لا سرّ في العنوان أصلاً، لكن الطلبات تمرّ بالناقل نفسه بتراجعه الأسّي ومحدّد
معدّله — الاتساق أرخص من استثناء.

---

## 2. السجل — ست سلاسل، والأوصاف كما تنشرها البوابة

| الفئة | `flowRef` | المفتاح | العنوان الرسمي |
|---|---|---|---|
| `DEPOSIT_FACILITY_RATE` | `FM` | `D.U2.EUR.4F.KR.DFR.LEV` | Deposit facility - date of changes (raw data) - Level |
| `HICP` | `ICP` | `M.U2.N.000000.4.ANR` | HICP - Overall index, Euro area, Annual rate of change, neither seasonally nor working day adjusted |
| `HICP_CORE` | `ICP` | `M.U2.N.XEF000.4.ANR` | HICP - Overall index excluding energy and food, Euro area, Annual rate of change |
| `UNEMPLOYMENT` | `LFSI` | `M.I9.S.UNEHRT.TOTAL0.15_74.T` | Unemployment rate, Total, Age 15 to 74, Total, Seasonally adjusted |
| `GDP` | `MNA` | `Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY` | Real GDP at market prices, euro area, chain linked volume, annual growth rate |
| `EUR_USD_REFERENCE` | `EXR` | `D.USD.EUR.SP00.A` | US dollar/Euro, ECB reference exchange rate, Average of observations through period |

### التواتر والوحدة والتعديل والمراجعة

| الفئة | التواتر | الوحدة | التعديل الموسمي | التواتر المتوقَّع | المراجعة |
|---|---|---|---|---|---|
| `DEPOSIT_FACILITY_RATE` | Daily | Percent per annum | Not applicable | عند كل تغيير في سعر الفائدة | لا تُراجَع |
| `HICP` | Monthly | Annual percentage change | Neither seasonally nor working day adjusted | شهرياً — تقدير سريع ثم نهائي | يُراجَع بين التقدير السريع والنهائي |
| `HICP_CORE` | Monthly | Annual percentage change | Neither seasonally nor working day adjusted | شهرياً مع الرقم العام | يُراجَع بين التقدير السريع والنهائي |
| `UNEMPLOYMENT` | Monthly | Percent of labour force | Seasonally adjusted | شهرياً بتأخّر نحو شهر | يُراجَع بأثر رجعي |
| `GDP` | Quarterly | Annual percentage change | Calendar and seasonally adjusted | ربع سنوي — تقدير سريع ثم مراجعات | يُراجَع عدة مرات |
| `EUR_USD_REFERENCE` | Daily | USD per EUR | Not applicable | يومياً نحو 16:00 بتوقيت وسط أوروبا | لا تُراجَع |

جهة الإصدار: البنك المركزي الأوروبي وحده لسلسلتي `FM` و`EXR`، وEurostat مع
البنك المركزي لبقية السلاسل.

---

## 3. «لا تُخترَع مفاتيح SDMX» — فشل مغلق

مفتاح SDMX **سلسلةُ أبعادٍ مرتّبة**، وتغيير بُعد واحد يعطي سلسلة **مختلفة
تماماً لا خطأً**:

```
ICP.M.U2.N.000000.4.ANR   ⇒  التضخم السنوي العام
ICP.M.U2.N.000000.4.INX   ⇒  الرقم القياسي نفسه
```

كلاهما **يعمل**، وأحدهما إجابة على سؤال آخر. ولذلك: مفتاح خارج السجل ⇒
`UNAVAILABLE` برمز `UNKNOWN_SERIES_KEY`، **ولا محاولة تخمين**.

---

## 4. قراءة `jsondata` — بالمواضع لا بالأسماء

الملاحظات متداخلة، والفهرسة **بالموضع**:

```
dataSets[0].series["0:0:0:…"].observations["3"] = [value, …]
                                          ↑
                       فهرس في structure.dimensions.observation[0].values
```

`parse_sdmx_json()` يبني قائمة الفترات من `structure.dimensions.observation[0]
.values[i].id` ثم يفهرس بها. قراءة `observations` بترتيب القاموس بدل هذا
الجدول تُنتج **تواريخ مبعثرة تبدو صحيحة** — وهو أسوأ من خطأ ظاهر.

| فحص في المُطبِّع | عند الفشل |
|---|---|
| الجسم قاموس، وفيه `dataSets` قائمة غير فارغة و`structure` قاموس | `None` ⇒ `MALFORMED` |
| `structure.dimensions.observation` قائمة غير فارغة | `None` |
| قائمة الفترات غير فارغة | `None` |
| `dataSets[0].series` قاموس غير فارغ، وأول سلسلة فيها `observations` | `None` |
| الفهرس عدد صحيح ضمن مدى الفترات، والحمولة قائمة غير فارغة | تُتخطّى الملاحظة |
| القيمة ليست `None` وقابلة للتفسير كـ`Decimal` | تُتخطّى الملاحظة |

الفترات تُفسَّر بثلاثة أشكال: `2026-08-28` · `2026-08` · `2026-Q2` (الربع
يُحوَّل إلى أول شهر فيه).

النتيجة تُرتَّب زمنياً ثم تُعكَس، فـ**الأحدث أولاً**.

---

## 5. التحقق هنا وجودي لا وصفي

ECB لا تُعيد بيانات وصفية بثراء FRED، فالإثبات العملي هو أن السلسلة **حيّة**:

```
validate_series(key) ⇒ observations(key, last_n=1, require_validation=False)
                      ⇒ FRESH ومعها ملاحظة  ⇒  يُضاف المفتاح إلى المُتحقَّق منها
```

وقبل ذلك، كل مفتاح `validated=False` و`observations()` ترفض بـ
`SERIES_NOT_VALIDATED`.

---

## 6. الحالات

| الوضع | الحالة | الرمز |
|---|---|---|
| مفتاح خارج السجل | `UNAVAILABLE` | `UNKNOWN_SERIES_KEY` |
| لم يُتحقَّق منه حيّاً | `UNAVAILABLE` | `SERIES_NOT_VALIDATED` |
| بنية SDMX غير متوقَّعة | `MALFORMED` | `MALFORMED` |
| ملاحظات صالحة | `FRESH` | — |
| لا ملاحظة صالحة | `PARTIAL` | — |
| لم تُعِد السلسلة شيئاً عند التحقق | حالة الفشل أو `MALFORMED` | `NO_OBSERVATIONS` |

`configured` تعيد `True` **دائماً وبنيوياً** — لا مفتاح يمكن أن ينقص.

---

## 7. الحدّ

يغذّي `CompositeMacroDataProvider` بثلاث سلاسل من الجانب الأوروبي:
`FM.D.U2.EUR.4F.KR.DFR.LEV` · `ICP.M.U2.N.XEF000.4.ANR` ·
`LFSI.M.I9.S.UNEHRT.TOTAL0.15_74.T`.

التقييم الناتج **سياق لا إذن**. ونقص أي سلسلة يُبقي الميل `UNKNOWN` بدل أن
يُستنتَج من الباقي.
