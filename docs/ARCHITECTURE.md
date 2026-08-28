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
| Clock | `clock.py` | UTC داخلياً، الرياض 12 ساعة للعرض، جلسة نيويورك، DST، العطلات |
| Contracts | `contracts.py` | نماذج Pydantic مجمّدة على كل حدود |
| Costs | `risk/costs.py` | جداول عمولات IBKR الموثقة + الاحتكاك |
| Constitution | `risk/constitution.py` | الحدود + البصمة |
| Sizing | `risk/sizing.py` | بحث ثنائي عن أكبر كمية آمنة |
| Risk Engine | `risk/engine.py` | الحَكَم |
| Kill Switch | `killswitch/engine.py` | 22 مُطلِقاً + سياسة طوارئ لكل واحد |
| Market Data | `marketdata/service.py` | الحداثة والمصدر والسبريد |
| Eligibility | `eligibility/allowlist.py` | قائمة بيضاء صريحة + قائمة رفض صريحة |
| Strategies | `strategies/` | إطار + استراتيجية واحدة (RESEARCH) |
| Brokers | `brokers/` | عقد مجرد + Mock + هياكل IBKR |
| Execution | `execution/orders.py` | idempotency، تأكيد، انزلاق، مطابقة |
| Audit | `audit/` | سلسلة hash + مخزن SQL |
| Pipeline | `pipeline/runner.py` | تركيب كل ما سبق بالترتيب |
| API | `main.py` | FastAPI للقراءة + Kill Switch فقط |

## 5. لماذا `BrokerAdapter` مجرد

كل منطق النظام مُختبَر اليوم عبر `MockBrokerAdapter` دون أي اتصال بـIBKR.
إضافة IBKR أو وسيط ثانٍ لاحقاً = ملء 18 ميثود في ملف واحد.
التفاصيل: `docs/adr/001-ibkr-api-selection.md`.

## 6. دور الذكاء الاصطناعي — بحدود صارمة

**مسموح:** تلخيص السوق، شرح سبب القرار بالعربية، Morning Brief، تصنيف ملاحظات السجل،
اقتراح فرضيات بحثية، اكتشاف تناقضات.

**ممنوع تماماً:** إرسال أمر، تغيير مخاطرة، تجاوز Risk Engine، اختراع سعر أو خبر أو نتيجة،
تعديل سجل التداول، اعتماد استراتيجية، نقل النظام إلى Live.

الضمانة ليست تعليمات نصية — بل أن طبقة الشرح **لا تملك مرجعاً** لـ`ExecutionService`
أو `KillSwitch` أو `RiskEngine`، وأن كل قرار تداول يخرج من دوال deterministic
قابلة لإعادة التشغيل على نفس المدخلات (يوجد اختبار لذلك).

## 7. التقنية

Python 3.12+ · FastAPI · Pydantic v2 · SQLAlchemy 2 · PostgreSQL (SQLite محلياً) · Pytest
Next.js 14 · TypeScript strict · Tailwind · RTL عربي · بلا أرقام أداء وهمية.
