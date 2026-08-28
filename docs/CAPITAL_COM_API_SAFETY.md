# Capital.com API Safety — أقفال الأمان

**المرجع الرسمي:** <https://open-api.capital.com/> (تُحقق 2026-08-28)

```
Demo : https://demo-api-capital.backend-capital.com/
Live : https://api-capital.backend-capital.com/     ⛔ مقفل في الكود
WS   : wss://api-streaming-capital.backend-capital.com/connect
```

---

## 1. أربعة أقفال مستقلة

كل قفل كافٍ وحده لمنع أي أمر. لا يوجد مسار يفتحها كلها تلقائياً.

| # | القفل | المكان | كيف يُفتح |
|---|---|---|---|
| 1 | `LIVE_API_ENABLED = False` | `brokers/capital/safety.py` | **تعديل كود + مراجعة + commit.** لا يقرأ متغير بيئة عمداً. |
| 2 | `ExecutionLock` مغلق | نفس الملف | `authorise()` بمرجع موافقة مالكة + سبب ≥10 أحرف |
| 3 | فحص الناقل `is_mutating()` | `transport.py` | يمنع الطلب قبل مغادرة العملية |
| 4 | `LIVE_TRADING` + `RISK_MODE` + ملف موافقة | `config.py` | ثلاثتها معاً |

**Fail closed:** مسار غير مصنَّف في `endpoints.py` يُعتبر **مُعدِّلاً** ويُرفض.
مضيف غير مضيف Demo يُعتبر **حقيقياً** ويُرفض.

---

## 2. تصنيف المسارات

**قراءة مسموحة:** `/time` · `/ping` · `/session/encryptionKey` · `GET /session` ·
`/accounts` · `/accounts/preferences` · `/history/activity` · `/history/transactions` ·
`/markets` · `/marketnavigation` · `/prices/{epic}` · `GET /positions` ·
`GET /workingorders` · `/confirms/{dealReference}`

**مُعدِّلة ومقفلة:** `POST|PUT|DELETE /positions` · `POST|PUT|DELETE /workingorders` ·
`PUT /accounts/preferences` · `POST /accounts/topUp` · `PUT /session`

**جلسة (مسموحة، ليست تداولاً):** `POST /session` · `DELETE /session`

---

## 3. الجلسة والرموز

| البند | القيمة الرسمية | كيف يتعامل النظام |
|---|---|---|
| المصادقة | `X-CAP-API-KEY` + `{identifier, password, encryptedPassword}` | `session.py` |
| الرموز | `CST` و `X-SECURITY-TOKEN` في ترويسات الاستجابة | **في الذاكرة فقط** |
| الصلاحية | 10 دقائق من آخر استخدام | تجديد تلقائي بهامش دقيقتين |
| الإبقاء | `GET /ping` | مع تحديث وقت الاستخدام |
| التشفير | RSA/PKCS1 على `base64(password\|timestamp)` | يُستعمل إن توفّر مفتاح |
| الفشل المتكرر | — | إقفال ذاتي بعد **3 محاولات**، ولا محاولة رابعة |

`__repr__` للرموز يعيد `***REDACTED***` — لا تظهر حتى في تتبّع استثناء.

---

## 4. حدود الطلبات

| الحد الرسمي | التطبيق |
|---|---|
| 10 طلبات/ثانية عام | دلو رموز |
| 1 طلب/ثانية لـ`POST /session` | دلو منفصل |
| 1 طلب/0.1 ثانية للأوامر | دلو منفصل (غير مستخدم — الأوامر مقفلة) |
| 1000 طلب/ساعة للأوامر في Demo | موثّق |
| 40 أداة كحد أقصى للاشتراك | مفروض في `streaming.py` |

الساعة والنوم قابلان للحقن، فتُختبر الحدود بلا انتظار حقيقي.

---

## 5. القاعدة الذهبية: استجابة 200 ليست تنفيذاً

```
POST /positions  →  200 OK + dealReference
                    ⚠️ لا يعني أن مركزاً فُتح
                         ↓
GET /confirms/{dealReference}  →  dealStatus == "ACCEPTED"
                    ✅ هذا هو الدليل الوحيد
                         ↓
GET /positions  →  المركز موجود فعلاً بالكمية والسعر المتوقعين
                    ✅ المطابقة تُغلق الحلقة
```

**المهلة بعد الإرسال ليست فشلاً — هي حالة `UNKNOWN`.**
المسار الإجباري: قراءة التأكيد ← قراءة المراكز ← تدخل بشري إن بقي الغموض.
**لا إعادة إرسال. أبداً.** المحاولة تُسجَّل في `execution_attempts` **قبل** الإرسال،
فحتى موت العملية لحظة الإرسال لا يُنتج أمراً ثانياً.

---

## 6. أمر الاكتشاف

```bash
python -m app.cli capital-discover --environment demo
```

- `--environment live` مرفوض عند تحليل الوسائط نفسه.
- قفل تنفيذ مغلق مُمرَّر صراحةً.
- بعد الانتهاء، `assert_read_only_session()` يفحص **كل عملية أُرسلت فعلاً**؛
  أي عملية غير قراءة تُفشل التقرير كله بـ`DiscoveryViolation`.
- التقريران يمران عبر `redact()` قبل الكتابة.

---

## 7. ما لا يستطيع النظام فعله تحت هذه المهمة

إيداع أو سحب · إدخال اعتمادات عبر المتصفح · طلب لصق سرّ في المحادثة ·
عرض قيمة سرّ · استعمال Live API · فتح أو تعديل أو إغلاق مركز (Demo أو Live) ·
إنشاء أوامر معلّقة · تغيير الرافعة أو التحوّط · شحن حساب تجريبي ·
التداول عبر الموقع أو TradingView · تفعيل تداول آلي مستمر · إرسال بريد أو رسائل دعم ·
نشر المستودع أو دفعه إلى remote.
