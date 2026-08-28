# Data Sources — مصادر البيانات

> قاعدة: كل رقم في نموذج التكلفة له رابط رسمي وتاريخ تحقق.
> رقم بلا مصدر = خطأ برمجي، لا «تقدير معقول».

## 1. مصادر مُحقَّقة

| البند | القيمة | المصدر | تاريخ التحقق |
|---|---|---|---|
| IBKR Pro Fixed — أسهم أمريكية | 0.005/سهم، حد أدنى 1.00، حد أقصى 1% من قيمة الصفقة | [commissions-stocks.php](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php) | 2026-08-28 |
| IBKR Pro Tiered — أسهم أمريكية | 0.0035/سهم (≤300k سهم/شهر)، حد أدنى 0.35، حد أقصى 1% | نفس المصدر | 2026-08-28 |
| IBKR Lite | 0.002/سهم — **US Residents Only** | نفس المصدر | 2026-08-28 |
| SEC Transaction Fee | 0.0000206 × قيمة المبيعات | نفس المصدر | 2026-08-28 |
| FINRA Trading Activity Fee | 0.000195 × الكمية المباعة | نفس المصدر | 2026-08-28 |
| الحد الأدنى للأمر الكسري | 0.01 للصفقة الكسرية | نفس المصدر | 2026-08-28 |
| الاستثمار الأدنى في الكسور | "as little as USD 1" | [fractional-trading.php](https://www.interactivebrokers.com/en/trading/fractional-trading.php) | 2026-08-28 |
| أنواع الأوامر للكسور | "market and limit orders" | نفس المصدر | 2026-08-28 |
| بيانات مؤجلة للأسهم الأمريكية | "IBKR no longer offers delayed quotation information on U.S. equities to Interactive Brokers LLC clients" | [market-data-pricing.php](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php) | 2026-08-28 |
| حزمة US Securities Snapshot | USD 10.00 base waived for activity + USD 0.01 per snapshot؛ إعفاء عند عمولات USD 30.00 | نفس المصدر | 2026-08-28 |
| واجهات IBKR البرمجية | Web API · Client Portal API · TWS API · FIX · Excel | [api getting-started](https://www.interactivebrokers.com/campus/ibkr-api-page/getting-started/) | 2026-08-28 |
| TWS API يحتاج TWS أو IB Gateway | "TCP Socket Protocol API based on connectivity to the Trader Workstation or IB Gateway" | نفس المصدر | 2026-08-28 |
| مصادقة Web API | OAuth 2.0 (beta) و OAuth 1.0a؛ `/tickle` للإبقاء على الجلسة؛ حساب "fully open and funded" من نوع IBKR Pro | [webapi-doc](https://ibkrcampus.com/campus/ibkr-api-page/webapi-doc/) | 2026-08-28 |

## 2. غير مُحقَّق — ولا يُبنى عليه قرار

انظر `docs/KNOWN_LIMITATIONS.md` البنود `OPEN-IBKR-01..05` و`OPEN-MD-01`.

## 3. مصادر ممنوعة كأسعار تنفيذ

- **بحث الويب.** يُستخدم للوثائق والقواعد فقط. لا يوجد أي مسار في الكود يحوّل نتيجة
  بحث ويب إلى سعر تنفيذ أو قرار تداول.
- **بيانات مؤجلة أو تاريخية.** مرفوضة بواسطة `marketdata/service.py` (`NOT_REALTIME`).
- **أسعار بلا طابع زمني أو بلا مصدر معروف.** مرفوضة (`MISSING` / `STALE`).

## 4. التقويم الاقتصادي

لا يوجد مصدر آلي رسمي موصول. البديل المُنفَّذ: **تقويم حظر يدوي** (`BlackoutCalendar`).
اليوم الذي لم تؤكده المالكة يدوياً يُنتج `NO_TRADE: NEWS_CALENDAR_UNCONFIRMED`.
النظام لا يخترع أخباراً ولا يفترض أن «لا أخبار اليوم».

## 5. عطلات السوق

مكتوبة يدوياً لعام 2026 في `clock.py::US_MARKET_HOLIDAYS_2026`.
**تحتاج مراجعة سنوية** — مُدرجة في `docs/OPERATIONS_RUNBOOK.md`.
