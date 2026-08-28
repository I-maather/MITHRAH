# Capital.com Credential Setup — إعداد الاعتمادات

> **لن يُطلب منكِ أبداً لصق أي قيمة في المحادثة.**
> الإعداد يتم على جهازك، بيدك، عبر سكربت محلي لا يتصل بالإنترنت.

---

## 1. ما ستحتاجينه — ثلاثة عناصر

| الاسم في النظام | ما هو | من أين |
|---|---|---|
| `CAPITAL_API_KEY` | مفتاح API | Capital.com ← Settings ← API |
| `CAPITAL_IDENTIFIER` | معرّف الدخول (بريدك المسجَّل) | حسابك |
| `CAPITAL_API_PASSWORD` | **كلمة المرور المخصّصة للمفتاح** | تُنشأ عند إنشاء المفتاح |

⚠️ العنصر الثالث هو **كلمة مرور المفتاح**، وليس كلمة مرور حسابك.
النظام لا يطلب كلمة مرور حسابك ولا يخزّنها، لأن واجهة Capital.com الرسمية
تقبل كلمة مرور المفتاح.

إعداد غير سرّي واحد يبقى في `.env`: `CAPITAL_ENVIRONMENT=demo`.

---

## 2. الأمر

```bash
cd ~/Desktop/Trading/Maather-Autonomous-Trader
./scripts/configure_capital_credentials.sh
```

سيسألك عن العناصر الثلاثة واحداً واحداً:

- الكتابة **مخفية** — لن يظهر شيء على الشاشة.
- يطلب إدخال كل قيمة **مرتين** للتأكد من عدم وجود خطأ مطبعي.
- إن كانت القيمة موجودة مسبقاً، يسأل صراحةً قبل استبدالها.

---

## 3. أين تُحفظ

| الوجهة | متى |
|---|---|
| **macOS Keychain** (`service=maather-autonomous-trader`) | الافتراضي على جهازك |
| `secrets/capital.env` بصلاحية `600` | فقط إن تعذّر Keychain |

كلاهما مستثنى من Git. المجلد `secrets/` كله مُدرج في `.gitignore`،
واختبار آلي يفشل لو تسرّب أي منهما إلى الملفات المتتبَّعة.

---

## 4. ضمانات السكربت

| الضمانة | كيف |
|---|---|
| لا يقبل سرّاً في سطر الأوامر | يرفض أي وسيط غير `--check`/`--remove`/`--help` — لئلا يظهر في `ps` |
| لا يدخل سجل الصدفة | `set +o history` في بدايته |
| لا يطبع أي قيمة | لا `echo` لأي سرّ، ولا حتى مقنّعاً |
| صلاحيات آمنة | `umask 077` + `chmod 600` |
| استبدال متعمّد فقط | يسأل `yes` صراحةً |
| فحص بلا كشف | `--check` يعرض ✅/❌ فقط |

---

## 5. التحقق — بلا كشف أي قيمة

```bash
./scripts/configure_capital_credentials.sh --check

cd backend && python3 -m app.cli secrets-status
```

المخرج:

```
مزوّد الأسرار: chained(macos-keychain,env-file)

  ✅  CAPITAL_API_KEY          المصدر: macos-keychain
  ✅  CAPITAL_IDENTIFIER       المصدر: macos-keychain
  ✅  CAPITAL_API_PASSWORD     المصدر: macos-keychain

كل الاعتمادات المطلوبة موجودة. لم تُعرض أي قيمة.
```

نفس الحالة تظهر في صفحة **الوسيط** في الواجهة: وجود فقط، بلا قيمة.

---

## 6. الحذف

```bash
./scripts/configure_capital_credentials.sh --remove
```

يحذف ما هو مخزَّن **محلياً**. لا يُلغي المفتاح لدى Capital.com —
لإيقافه فعلياً احذفيه أو أوقفيه من صفحة API في حسابك.

---

## 7. أين لا تظهر الأسرار — مضمون باختبارات

| الموضع | الاختبار |
|---|---|
| السجلات | `test_logging_filter_redacts_message_and_args` |
| الاستثناءات | `test_exceptions_cannot_carry_a_secret` |
| ترويسات HTTP في التسجيل | `test_sensitive_header_names_are_redacted_by_name` |
| Audit Log | `test_audit_log_payloads_are_redacted` |
| تقرير الاكتشاف | `test_discovery_report_contains_no_secret` |
| الواجهة | `test_broker_endpoint_never_returns_a_credential_value` |
| قاعدة البيانات | `test_session_tokens_are_never_persisted_to_the_database` |
| Git | `test_secret_paths_are_ignored_by_git` · `test_no_tracked_file_contains_a_credential_assignment` |

`CST` و`X-SECURITY-TOKEN` يعيشان **في الذاكرة فقط**، ولا يوجد في قاعدة البيانات
أي عمود يمكن أن يحملهما (مُختبَر). `logout()` ينساهما من سجل الحجب فوراً.

---

## 8. بعد الانتهاء

أخبري كلود بجملة واحدة أن الإعداد اكتمل — **بلا إرسال أي قيمة**.
عندها فقط يبدأ الاتصال بـDemo، وهو **قراءة فقط**:
لا إرسال أوامر، ولا تعديل تفضيلات، ولا شحن رصيد، ولا لمس عنوان Live.
