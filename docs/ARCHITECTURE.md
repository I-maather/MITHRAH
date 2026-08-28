# Architecture — هيكلية النظام

## 1. المبدأ الحاكم

قاعدة المخاطر التي يمكن للنموذج اللغوي أن «ينساها» ليست قاعدة.
لذلك كل قاعدة في هذا النظام **قيد برمجي** له اختبار، والذكاء الاصطناعي لا يلمس القرار.

## 2. تسلسل الصلاحيات

```
1. المالكة (Maather)          ← القرار النهائي، وحدها تفعّل Live وتعيد تشغيل Kill Switch
2. Kill Switch                ← أعلى صلاحية برمجية، مستقل عن كل شيء
3. Risk Engine                ← نقض على كل فرصة؛ لا مسار لإنشاء أمر إلا من قراره
4. Eligibility / Market Data  ← بوابات منع
5. Strategy                   ← تقترح فقط
6. طبقة الشرح بالذكاء الاصطناعي ← تصف وتشرح، ولا تقرر شيئاً
```

## 3. الخط اليومي

```
┌─ 0. Kill Switch gate ─────────── مفعّل؟ ⇒ HALTED، انتهى.
├─ 1. Broker health + Balances + Permissions ⇒ انقطاع ⇒ Kill Switch
├─ 2. Market status (نيويورك، DST تلقائي)
├─ 3. Macro veto ──────────────── يمنع فقط، لا يفرض صفقة
├─ 4. News blackout ──────────── يوم غير مؤكد ⇒ NO_TRADE (لا نخترع أخباراً)
├─ 5. Instrument eligibility ─── قائمة بيضاء، عملة، جلسة، صلاحيات، بيانات، دعم الستوب
├─ 6. Strategy (APPROVED فقط) ── deterministic، بلا LLM
├─ 7. Risk Engine ────────────── الحدود + الحجم بعد الرسوم + السقف المطلق
├─ 8. Order Intent + Preview ─── idempotency key، لا إرسال بلا معاينة
├─ 9. Submission ─────────────── الاستجابة الأولى ليست تنفيذاً
├─ 10. Confirmation ──────────── حالة + كمية + سعر من الوسيط
├─ 11. Reconciliation ────────── اختلاف ⇒ Kill Switch
└─ 12. Audit ─────────────────── كل خطوة، والنتيجة، وقرارات NO_TRADE
```

كل مرحلة تستطيع إيقاف الخط. لا مرحلة تستطيع تخطي التي قبلها.

## 4. الوحدات

| الوحدة | الملف | المسؤولية |
|---|---|---|
| Money | `money.py` | Decimal فقط، تقريب التكاليف لأعلى والعوائد لأسفل |
| Clock | `clock.py` | UTC داخلياً، الرياض 12 ساعة للعرض، الجلسات، DST، العطلات |
| Contracts | `contracts.py` | نماذج Pydantic مجمّدة على كل حدود |
| Constitution | `risk/constitution.py` | الحدود + 4 أوضاع + بصمة (وضع × وسيط) |
| Costs — IBKR | `risk/costs.py` | جداول عمولات IBKR — **لم تُلمس**، تُستدعى فقط عند `broker=IBKR` |
| Costs — CFD | `risk/capital_costs.py` | تعرّض/هامش/خسارة منفصلة + `ValueProvenance` |
| Cost Router | `risk/cost_router.py` | يختار النموذج حسب الوسيط؛ المحرك لا يعرف اسم وسيط |
| Sizing | `risk/sizing.py` | بحث ثنائي عن أكبر كمية آمنة (مسار الأسهم) |
| Risk Engine | `risk/engine.py` | الحَكَم — `_run_gates()` مشتركة، `evaluate()` أسهم، `evaluate_cfd()` عقود فروقات |
| Secrets | `secretstore/` | Keychain · ملف `600` · حجب في السجلات والاستثناءات والتقارير |
| Capital.com | `brokers/capital/` | endpoints · safety · ratelimit · transport · session · models · adapter · streaming |
| IBKR | `brokers/ibkr.py` | هياكل محفوظة كما هي — غير مستخدَمة |
| Kill Switch | `killswitch/engine.py` | 22 مُطلِقاً + سياسة طوارئ لكل واحد |
| Market Data | `marketdata/service.py` | الحداثة والمصدر والسبريد |
| Eligibility | `eligibility/allowlist.py` | قائمة بيضاء صريحة + قائمة رفض صريحة |
| Strategies | `strategies/` | إطار · `backtest.py` · `shadow.py` · `gates.py` |
| Discovery | `discovery/capital_discovery.py` | اكتشاف Demo قراءةً فقط + تحقق لاحق من كل عملية أُرسلت |
| Signals | `signals/source.py` | TradingView webhook — معطَّل افتراضياً، HMAC، رفض الاعتمادات |
| Notifications | `notifications/` | ذاكرة وملف محلي فقط — بلا أي استيراد شبكي |
| Scheduling | `scheduling/` | يرفض تسجيل مهمة `MUTATING` من الأساس |
| Execution | `execution/orders.py` | idempotency، تأكيد، انزلاق، مطابقة |
| Recovery | `db/recovery.py` | `execution_attempts` قبل الإرسال · الإقلاع لا يسمح بدخول جديد أبداً |
| Migrations | `alembic/` | 0001 خط الأساس · 0002 هجرة Capital.com (إضافية فقط) |
| Audit | `audit/` | سلسلة hash + مخزن SQL |
| Pipeline | `pipeline/runner.py` | تركيب كل ما سبق بالترتيب |
| API | `main.py` | FastAPI للقراءة + Kill Switch + إيقاف/رفع إيقاف محلي فقط |

## 5. الحياد تجاه الوسيط — وكيف صمد أمام تبديل الوسيط

كل منطق النظام مُختبَر عبر `MockBrokerAdapter` دون أي اتصال بأي وسيط.
تبديل الوسيط التشغيلي من IBKR إلى Capital.com **لم يتطلب إعادة كتابة**:

```
Risk Engine ─┬─ _run_gates()      ← بوابات مشتركة، لا تعرف اسم وسيط
             ├─ evaluate()        ← مسار الأسهم: يحلّ الكمية عكسياً من ميزانية المخاطرة
             └─ evaluate_cfd()    ← مسار CFD: الكمية مفروضة من الوسيط، والسؤال
                                     هل الخسارة الكلية ضمن الحد

Cost Router ─┬─ Broker.IBKR        → risk/costs.py         (لم يُلمس)
             └─ Broker.CAPITAL_COM → risk/capital_costs.py (جديد)

Constitution ─ حدود وقوائم أدوات وسياسة كمية **لكل وسيط على حدة**،
               فقيود CFD لا تُضعف سياسة الأسهم ولا العكس.
```

`ibkr.py` و`costs.py` و`sizing.py` بقيت كما هي بلا تعديل — محفوظة لمرحلة
الأسهم العالمية والسوق السعودي ورأس المال الأكبر (`docs/IBKR_FUTURE_PHASE.md`).

## 5.1 طبقة Capital.com — أربعة أقفال مستقلة

```
1. LIVE_API_ENABLED = False     ← ثابت في المصدر، لا يقرأ متغير بيئة عمداً
2. ExecutionLock مغلق           ← from_environment() يعيد مغلقاً دائماً
3. فحص الناقل is_mutating()      ← يمنع الطلب قبل مغادرته العملية
4. LIVE_TRADING + RISK_MODE + ملف موافقة
```

**Fail closed:** مسار غير مصنَّف ⇒ يُعتبر مُعدِّلاً. مضيف غير Demo ⇒ يُعتبر Live.

الميثودات المُعدِّلة **مبنيّة بالكامل ومقفلة**: `build_position_payload()` يبني
الجسم بالشكل الرسمي ولا يرسله، و`place_order()` يستدعي القفل ثم يرفع استثناءً.

**200 OK ليست تنفيذاً.** الدليل الوحيد `GET /confirms/{dealReference}` ثم
`GET /positions`. المهلة بعد الإرسال حالة `UNKNOWN` لا فشل، ولا إعادة إرسال أبداً؛
المحاولة تُسجَّل في `execution_attempts` **قبل** الإرسال.

## 5.2 الأسرار

`SecretProvider` مجرد ← Keychain ← ملف `600` ← بيئة، بترتيب مُسلسل.
الرموز `CST` و`X-SECURITY-TOKEN` **في الذاكرة فقط**، `__repr__` لها يعيد قناعاً،
ولا يوجد في قاعدة البيانات عمود يمكن أن يحملهما (مُختبَر).
`RedactingFilter` مثبَّت على السجلات، و`RedactedError` يحجب رسالته الخاصة،
وتقارير الاكتشاف تمرّ عبر `redact()` قبل الكتابة.

## 6. دور الذكاء الاصطناعي — بحدود صارمة

**مسموح:** تلخيص السوق، شرح سبب القرار بالعربية، Morning Brief، تصنيف ملاحظات السجل،
اقتراح فرضيات بحثية، اكتشاف تناقضات.

**ممنوع تماماً:** إرسال أمر، تغيير مخاطرة، تجاوز Risk Engine، اختراع سعر أو خبر أو نتيجة،
تعديل سجل التداول، اعتماد استراتيجية، نقل النظام إلى Live.

الضمانة ليست تعليمات نصية — بل أن طبقة الشرح **لا تملك مرجعاً** لـ`ExecutionService`
أو `KillSwitch` أو `RiskEngine`، وأن كل قرار تداول يخرج من دوال deterministic
قابلة لإعادة التشغيل على نفس المدخلات (يوجد اختبار لذلك).

## 7. التقنية

Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic · PostgreSQL (SQLite محلياً) · Pytest
Next.js 14 · TypeScript strict · Tailwind · RTL عربي · بلا أرقام أداء وهمية.

الإصدار **0.2.0** · 446 اختباراً · 24 جدولاً · لا اتصال شبكي في أي اختبار.
