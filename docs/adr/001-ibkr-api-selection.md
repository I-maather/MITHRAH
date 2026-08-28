# ADR-001 — اختيار واجهة IBKR البرمجية

- **الحالة:** مقبول مبدئياً / مشروط بتحقق ميداني
- **التاريخ:** 2026-08-28
- **القرار:** بناء `BrokerAdapter` مجرد أولاً، واعتماد **TWS API عبر IB Gateway** كخيار
  التنفيذ الأول لـPaper وLive، مع إبقاء **Web API (OAuth 2.0)** كمسار بديل مُقيَّم.

---

## 1. السياق

مستخدمة واحدة مقيمة في السعودية، حساب Individual Cash، رأس مال 100 دولار،
أسهم/ETFs أمريكية Long-only فقط، تشغيل محلي على macOS.

الاختيار يحدد: هل يمكن التشغيل غير المراقب؟ هل تُدعم أوامر الحماية؟ ما تكلفة البيانات؟

---

## 2. ما تم التحقق منه فعلاً

| المصدر | التاريخ | ما ورد |
|---|---|---|
| [IBKR API Home](https://www.interactivebrokers.com/campus/ibkr-api-page/getting-started/) | 2026-08-28 | IBKR يعرض: RESTful **Web API**، **Client Portal API**، **TWS API**، **FIX**، **Excel APIs**. |
| نفس المصدر | 2026-08-28 | TWS API: "a TCP Socket Protocol API based on connectivity to the Trader Workstation or **IB Gateway**"، وأن IB Gateway مفضّل لأن "the removal of unused graphical elements from automated trading can allow more resources be dedicated to your unique programs". |
| نفس المصدر | 2026-08-28 | Web API: "Authorization and Authentication for IBKR's Web API is managed using **OAuth 2.0**". |
| [Web API Doc](https://ibkrcampus.com/campus/ibkr-api-page/webapi-doc/) | 2026-08-28 | يذكر **OAuth 2.0 (beta)** و**OAuth 1.0a**؛ جلسة ثنائية الطبقة (قراءة + brokerage session)؛ الإبقاء على الجلسة عبر `/tickle` بحد 1 طلب/ثانية؛ وأن الحساب يجب أن يكون "fully open and funded" ومن نوع **IBKR Pro**. |
| [Commissions Stocks](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php) | 2026-08-28 | IBKR Lite: "**US Residents Only**" ⇒ غير متاح للمالكة. التسعير المتاح Pro (Fixed/Tiered). |
| [Market Data Pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php) | 2026-08-28 | "IBKR no longer offers **delayed** quotation information on U.S. equities to Interactive Brokers LLC clients"؛ حزمة Snapshot: USD 10.00 base waived for activity + USD 0.01 per snapshot؛ إعفاء عند عمولات USD 30.00 شهرياً. |

---

## 3. ما لم يُحسم — ولن يُخترع

| البند | لماذا لم يُحسم |
|---|---|
| متطلبات إعادة المصادقة اليومية و2FA لـTWS/IB Gateway | صفحة "Daily & Weekly Reauthentication" مذكورة في فهرس الوثائق لكن لم نتمكن من قراءة نصها الرسمي مباشرة. |
| دعم Stop/Bracket على **الكميات الكسرية** | صفحات Fractional Trading الرسمية تذكر "market and limit orders" ولا تنص صراحةً على Stop أو Bracket للكسور. |
| الكيان الذي يخدم المقيمين في السعودية | قائمة الدول الرسمية تُدرج السعودية لكنها لا تربطها بكيان محدد. |
| منافذ السوكت الدقيقة وحدود المعدل الفعلية للحساب | تتأكد من إعدادات الحساب نفسه. |

هذه البنود مُسجَّلة كـ `OPEN-IBKR-01..05` في `docs/KNOWN_LIMITATIONS.md`،
و**لا يجوز تفعيل Live قبل حسمها بمصدر رسمي أو باختبار فعلي على حساب Paper**.

---

## 4. المقارنة

| المعيار | TWS API (عبر IB Gateway) | Web API (OAuth 2.0) | Client Portal API | FIX |
|---|---|---|---|---|
| يحتاج تطبيقاً محلياً | **نعم** — TWS أو IB Gateway | لا (يوجد CP Gateway اختياري) | يعتمد على النشر | لا |
| المصادقة | تسجيل دخول داخل التطبيق (+2FA) | OAuth 2.0 (beta) / 1.0a — يتطلب **إنشاء API credentials** | جلسة/كوكيز | جلسة FIX |
| Paper Trading | مدعوم بحساب Paper منفصل | يعتمد على الحساب | يعتمد | غير مناسب |
| نضج المكتبات لـPython | الأعلى (`ibapi` الرسمية + طبقات فوقها) | أحدث وأقل استقراراً (OAuth 2.0 في beta) | متوسط | مرتفع التعقيد |
| مناسب لحساب Individual صغير | نعم | مشروط بـIBKR Pro وحساب ممول | نعم | لا (مؤسسي) |
| التشغيل غير المراقب | مقيّد بإعادة التشغيل/المصادقة اليومية | مقيّد بعمر الجلسة و`/tickle` | مشابه | الأفضل نظرياً |

---

## 5. القرار وأسبابه

**القرار الأساسي: `BrokerAdapter` مجرد.**
هذا هو القرار الأهم في هذه الوثيقة. النظام كله يتكلم مع واجهة من 18 ميثود،
وIBKR تفصيلة تنفيذية خلفها. النتيجة: تغيير الواجهة أو الوسيط لاحقاً = ملء ملف واحد،
دون لمس Risk Engine أو Kill Switch أو Pipeline. وهذا مُثبت عملياً:
كل منطق النظام مُختبَر اليوم عبر `MockBrokerAdapter` دون أي اتصال بـIBKR.

**الخيار الأول للتنفيذ: TWS API عبر IB Gateway.**

الأسباب:
1. **نضج المكتبة.** `ibapi` الرسمية مستقرة منذ سنوات؛ OAuth 2.0 في Web API ما زال **beta**،
   والمال الحقيقي ليس مكاناً لاختبار beta.
2. **لا حاجة لإنشاء API credentials نيابة عن المالكة** — وهو أمر ممنوع عليّ أصلاً.
   IB Gateway يعتمد على تسجيل دخول تقوم به هي بنفسها.
3. **Paper Trading نظيف الفصل** — حساب Paper منفصل بمنفذ منفصل، فيصعب الخلط بين
   البيئتين بالخطأ.
4. تغطية أفضل لأنواع الأوامر وتفاصيل العقود (`contractDetails`) التي يحتاجها
   فحص الأهلية قبل أي صفقة.

**السلبية المقبولة:** يجب تشغيل IB Gateway على جهاز المالكة، ويخضع لإعادة تشغيل/مصادقة دورية.
هذا يعني أن **التشغيل غير المراقب الكامل غير مضمون في V1** — وهو مُصرَّح به في
`KNOWN_LIMITATIONS.md` بدل التظاهر بعكسه.

**متى نعيد النظر:** إذا استقر OAuth 2.0 خارج الـbeta وتأكد دعمه لحساب Individual سعودي
بجلسة تصلح للتشغيل الطويل، فالانتقال إليه = تنفيذ `IBKRWebApiAdapter` جديد فقط.

---

## 6. التشغيل داخل Docker

IB Gateway تطبيق سطح مكتب Java يحتاج واجهة رسومية وتسجيل دخول تفاعلياً.
تشغيله داخل Docker ممكن عبر حلول VNC غير رسمية لكنه **غير موثوق للمال الحقيقي**.

**القرار:** IB Gateway يعمل على المضيف (macOS)، والباك-إند يتصل به عبر `127.0.0.1`.
Docker Compose يُستخدم لـPostgreSQL فقط.

---

## 7. العواقب

- ✅ منطق النظام مُختبَر بالكامل اليوم دون IBKR.
- ✅ لا يوجد مسار برمجي يختار `IBKRLiveAdapter` تلقائياً (`factory.py` + ثلاثة أقفال).
- ⚠️ يبقى محوّل IBKR غير مكتمل حتى يُفتح حساب وتُحسم البنود المفتوحة.
- ⚠️ التشغيل غير المراقب مقيّد بدورة إعادة المصادقة اليومية.
