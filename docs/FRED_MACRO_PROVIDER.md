# FRED Macro — سلاسل أمريكية رسمية بسجل مُرقَّم

**الكود:** `backend/app/providers/fred_macro.py` · **إصدار السجل:** `1.0.0`

بيانات كلية أمريكية من بنك سانت لويس الفيدرالي. **سياق فقط — لا تأذن بصفقة.**

---

## 1. العقد — مُثبَت من `fred.stlouisfed.org/docs/api/fred/`

```
GET https://api.stlouisfed.org/fred/series?series_id=X&api_key=K&file_type=json
GET https://api.stlouisfed.org/fred/series/observations?series_id=X&api_key=K&file_type=json
```

| البند | القيمة |
|---|---|
| المعاملان الإلزاميان | `api_key` · `file_type=json` |
| شكل الخطأ (موثَّق حرفياً) | `{"error_code": 400, "error_message": "Bad Request. ..."}` |
| مفتاح البيانات الوصفية | `seriess` (قائمة) |
| مفتاح الملاحظات | `observations` (قائمة) |
| الحد المحلي المطبَّق | 60 استدعاءً في الدقيقة — **محافظ**، الرقم الرسمي غير منشور و429 موثَّق |
| الرخصة | `PUBLIC_OFFICIAL` — تخزين كامل مسموح |

المفتاح يمرّ في سلسلة الاستعلام ⇒ كل عنوان يخرج منقّى عبر `redact_url()`.

---

## 2. القيمة الغائبة `"."` — ولا تُقرأ صفراً أبداً

FRED يستعمل السلسلة `"."` للملاحظة الغائبة. قراءتها صفراً تعني «التضخم صفر»
بدل «لا قيمة منشورة» — وهو فرق يقلب أي استنتاج.

```
raw_value in (None, "", ".")  ⇒  تُتخطّى الملاحظة، ولا يُدرَج سجل
```

القيم تُقرأ بـ`Decimal` عبر `money.D`، وأي قيمة غير قابلة للتفسير عدداً تُتخطّى
كذلك — لا تُخمَّن ولا تُقرَّب.

---

## 3. السجل — تسع سلاسل، والعناوين منقولة من صفحات FRED الرسمية

| الفئة | الرمز | العنوان الرسمي | التواتر | الوحدة | التعديل الموسمي |
|---|---|---|---|---|---|
| `POLICY_RATE` | `DFEDTARU` | Federal Funds Target Range – Upper Limit | Daily, 7-Day | Percent | Not Seasonally Adjusted |
| `INFLATION` | `CPIAUCSL` | Consumer Price Index for All Urban Consumers: All Items in U.S. City Average | Monthly | Index 1982-1984=100 | Seasonally Adjusted |
| `CORE_INFLATION` | `CPILFESL` | Consumer Price Index for All Urban Consumers: All Items Less Food and Energy in U.S. City Average | Monthly | Index 1982-1984=100 | Seasonally Adjusted |
| `UNEMPLOYMENT` | `UNRATE` | Unemployment Rate | Monthly | Percent | Seasonally Adjusted |
| `PAYROLLS` | `PAYEMS` | All Employees, Total Nonfarm | Monthly | Thousands of Persons | Seasonally Adjusted |
| `GDP` | `GDPC1` | Real Gross Domestic Product | Quarterly | Billions of Chained 2017 Dollars | Seasonally Adjusted Annual Rate |
| `PCE_INFLATION` | `PCEPILFE` | Personal Consumption Expenditures Excluding Food and Energy (Chain-Type Price Index) | Monthly | Index 2017=100 | Seasonally Adjusted |
| `YIELD_2Y` | `DGS2` | Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity, Quoted on an Investment Basis | Daily | Percent | Not Seasonally Adjusted |
| `YIELD_10Y` | `DGS10` | Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis | Daily | Percent | Not Seasonally Adjusted |

### جهة الإصدار والتواتر المتوقَّع والتحويل وسياسة المراجعة

| الرمز | جهة الإصدار | التواتر المتوقَّع | التحويل | المراجعة |
|---|---|---|---|---|
| `DFEDTARU` | Board of Governors of the Federal Reserve System | عند كل اجتماع FOMC وعند أي تغيير | المستوى كما هو | `LATEST` |
| `CPIAUCSL` | U.S. Bureau of Labor Statistics | شهرياً، منتصف الشهر التالي | تغيّر سنوي (`pc1`) | `AS_OF_VINTAGE` |
| `CPILFESL` | U.S. Bureau of Labor Statistics | شهرياً مع الرقم العام | تغيّر سنوي (`pc1`) | `AS_OF_VINTAGE` |
| `UNRATE` | U.S. Bureau of Labor Statistics | شهرياً، أول جمعة | المستوى كما هو | `AS_OF_VINTAGE` |
| `PAYEMS` | U.S. Bureau of Labor Statistics | شهرياً، أول جمعة مع NFP | التغيّر الشهري بالآلاف | `AS_OF_VINTAGE` |
| `GDPC1` | U.S. Bureau of Economic Analysis | ربع سنوي، ثلاث تقديرات لكل ربع | نمو سنوي (`pc1`) | `AS_OF_VINTAGE` |
| `PCEPILFE` | U.S. Bureau of Economic Analysis | شهرياً — مقياس التضخم المفضّل لدى الفيدرالي | تغيّر سنوي (`pc1`) | `AS_OF_VINTAGE` |
| `DGS2` | Board of Governors of the Federal Reserve System | يومياً في أيام العمل | المستوى كما هو | `LATEST` |
| `DGS10` | Board of Governors of the Federal Reserve System | يومياً في أيام العمل | المستوى كما هو | `LATEST` |

---

## 4. لماذا سياسة مراجعة لكل سلسلة

السلاسل الاقتصادية تُراجَع **بأثر رجعي**. تجاهل ذلك يجعل Backtest يرى أرقاماً
**لم تكن معروفة** في وقتها — وهو تسريب مستقبل صريح يجعل النتائج أفضل مما يمكن
تحقيقه.

| السياسة | المعنى | متى تُستعمل |
|---|---|---|
| `LATEST` | آخر قيمة منشورة | سلاسل لا تُراجَع فعلياً (سعر السياسة، عوائد الخزانة) |
| `AS_OF_VINTAGE` | القيمة **كما كانت معروفة** في التاريخ المطلوب | كل ما تُراجعه BLS وBEA |

---

## 5. `validated=False` — التحقق من مستند ليس تحقّقاً من الواجهة

كل رمز في السجل تُحقِّق من صفحته الرسمية، **ومع ذلك يبقى `validated=False`**
حتى تُطابَق بياناته الوصفية **حيّاً** عبر `/fred/series` بمفتاح المالكة. سلسلة
قد يُعاد تعريفها أو تُوقَف.

```
رمز غير مُتحقَّق منه حيّاً  ⇒  observations() ترفض بـSERIES_NOT_VALIDATED
```

### ما يُقارَن في `validate_series()`

`title` · `frequency` · `units` · `seasonal_adjustment` — الأربعة معاً.

**الاختلاف لا يُصحَّح تلقائياً.** سلسلة غيّرت عنوانها أو وحدتها قد تكون سلسلة
أخرى تماماً، وقبول التغيير صامتاً يعني حساب تضخم على مؤشر مختلف. النتيجة
`MALFORMED` برمز `METADATA_MISMATCH`، والسجل يذكر **السجل المحلي والواجهة معاً**
لكل حقل مختلف.

---

## 6. الحالات

| الوضع | الحالة | الرمز |
|---|---|---|
| الرمز ليس في السجل | `UNAVAILABLE` | `UNKNOWN_SERIES` — **لا يُخترع رمز** |
| المفتاح غير مُعدّ | `UNAVAILABLE` | `NOT_CONFIGURED` |
| لم يُتحقَّق حيّاً بعد | `UNAVAILABLE` | `SERIES_NOT_VALIDATED` |
| جسم يحمل `error_code` | `MALFORMED` | قيمة `error_code` نفسها |
| لا `seriess` / لا `observations` | `MALFORMED` | `MALFORMED` |
| بيانات وصفية مختلفة | `MALFORMED` | `METADATA_MISMATCH` |
| ملاحظات صالحة | `FRESH` | — |
| لا ملاحظة صالحة واحدة | `PARTIAL` | — |

`observations()` تطلب `sort_order=desc` و`limit` (24 افتراضاً)، فأحدث ملاحظة
أولاً.

---

## 7. الواجهة القائمة `series()`

المفقود يعود `UNKNOWN` بموثوقية `UNRELIABLE` — **لا صفراً ولا تقديراً**.
والموجود يعود بموثوقية `OFFICIAL` مع عنوان السلسلة الرسمي وتاريخ الملاحظة.

كل سجل يحمل `Provenance` كاملاً: الجهة المُصدِرة · رابط صفحة السلسلة ·
`USD` · الفئة · بصمة القيمة الخام · `PUBLIC_OFFICIAL`.

---

## 8. الحدّ

هذا المزوّد يغذّي `CompositeMacroDataProvider` مع ECB. والتقييم الناتج **سياق
لا إذن**: `MacroAssessment.authorises_trade` ثابتة `False`، والميل يبقى
`UNKNOWN` ما دامت البيانات ناقصة — **لا يُستنتَج ميل من فراغ**.
