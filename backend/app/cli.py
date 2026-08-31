"""
واجهة سطر الأوامر.

    python -m app.cli capital-discover --environment demo
    python -m app.cli secrets-status
    python -m app.cli constitution

كل الأوامر هنا **قراءة فقط**. لا يوجد أمر يُرسل صفقة أو يعدّل حساباً.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .brokers.capital.adapter import CapitalComAdapter
from .brokers.capital.endpoints import CapitalEnvironment
from .brokers.capital.errors import CapitalAuthError, CapitalAuthLockout
from .brokers.capital.ratelimit import RateLimiter
from .brokers.capital.safety import ExecutionLock, LiveApiBlocked
from .brokers.capital.session import CapitalSession
from .brokers.capital.transport import GuardedTransport, HttpxTransport
from .clock import format_riyadh, now_utc
from .config import REPO_ROOT, get_settings
from .live_readonly.allowlist import (
    AllowlistViolation,
    LIVE_BASE_URL as LIVE_READONLY_BASE_URL,
    describe_allowlist,
)
from .live_readonly.discovery import DISCOVERY_EPICS as LIVE_DISCOVERY_EPICS
from .live_readonly.discovery import run_live_discovery
from .live_readonly.private_store import (
    PrivateStoreError,
    private_directory,
    require_private_output,
    write_public_text,
)
from .live_readonly.report import (
    PLANNED_CAPITAL_USD,
    assess_equity,
    compute_feasibility,
    render_public_feasibility_markdown,
    write_private_actual_feasibility,
    write_private_discovery_json,
    write_private_discovery_markdown,
)
from .live_readonly.session import LiveAuthError, LiveSession
from .providers import PROVIDER_CREDENTIALS
from .providers.fmp_calendar import FmpEconomicCalendarProvider
from .providers.probe import AVAILABLE_PROBES, probe_fmp_calendar
from .live_readonly.spread_sample import (
    SPREAD_SAMPLE_EPIC,
    SpreadSamplerError,
    render_spread_report,
    run_spread_sampling,
)
from .live_readonly.transport import LiveReadOnlyTransport, LiveTransportError
from .diagnostics.auth_probe import (
    ProbeViolation,
    render_report,
    run_auth_probe,
)
from .discovery.capital_discovery import (
    DISCOVERY_EPICS,
    DiscoveryViolation,
    assert_read_only_session,
    run_discovery,
    write_reports,
)
from .risk.constitution import (
    CONSTITUTION_VERSION,
    INITIAL_CAPITAL_USD,
    MODE_SPECS,
    RiskLimits,
    RiskMode,
    constitution_fingerprint,
)
from .contracts import Broker
from .secretstore.provider import (
    REQUIRED_CAPITAL_SECRETS,
    build_secret_provider,
)
from .secretstore.redaction import install_redacting_filter

DEFAULT_SECRETS_FILE = REPO_ROOT / "secrets" / "capital.env"


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_redacting_filter()


# ---------------------------------------------------------------------------
def cmd_secrets_status(args: argparse.Namespace) -> int:
    """يفحص وجود الأسرار **دون كشف أي قيمة**."""
    provider = build_secret_provider(env_file=args.secrets_file, allow_process_env=False)
    print(f"مزوّد الأسرار: {provider.name}")
    print()
    all_present = True
    for presence in provider.presence(REQUIRED_CAPITAL_SECRETS):
        mark = "✅" if presence.present else "❌"
        source = presence.source if presence.present else "—"
        print(f"  {mark}  {presence.name:<24} المصدر: {source}")
        all_present = all_present and presence.present
    print()
    if all_present:
        print("كل الاعتمادات المطلوبة موجودة. لم تُعرض أي قيمة.")
        return 0
    print("اعتمادات ناقصة. شغّلي: scripts/configure_capital_credentials.sh")
    return 1


def cmd_constitution(args: argparse.Namespace) -> int:
    print(f"دستور المخاطر — الإصدار {CONSTITUTION_VERSION}")
    print(f"رأس المال المرجعي: {INITIAL_CAPITAL_USD} USD")
    print()
    for mode in RiskMode:
        limits = RiskLimits.for_mode(mode, INITIAL_CAPITAL_USD, Broker.CAPITAL_COM)
        print(f"[{mode.value}]  {MODE_SPECS[mode].purpose_ar}")
        print(
            f"    أقصى مخاطرة/صفقة {limits.max_risk_per_trade:.2f} · "
            f"يومي {limits.daily_loss:.2f} · أسبوعي {limits.weekly_loss:.2f} · "
            f"إجمالي {limits.hard_total_loss:.2f} · "
            f"تشغيلي {limits.effective_drawdown_stop():.2f}"
        )
        print(f"    البصمة: {constitution_fingerprint(mode, Broker.CAPITAL_COM)[:16]}…")
        print()
    return 0


def cmd_capital_discover(args: argparse.Namespace) -> int:
    """
    اكتشاف Capital.com — قراءة فقط. يرفض بيئة Live رفضاً قاطعاً.
    """
    if args.environment.lower() != "demo":
        print(
            "⛔ الاكتشاف مسموح على بيئة demo فقط. "
            "هذا الأمر لا يعمل إلا على demo.",
            file=sys.stderr,
        )
        return 2
    # كان هنا وقفٌ عامّ عند رفع القفل الأول. حُذف: الشرط أعلاه خاصّ بالنداء
    # ويرفض كل بيئة غير demo، فلا مسار يبلغ به هذا الأمر عنواناً حقيقياً.

    provider = build_secret_provider(env_file=args.secrets_file, allow_process_env=False)
    missing = provider.missing(REQUIRED_CAPITAL_SECRETS)
    if missing:
        print(
            "اعتمادات ناقصة: " + ", ".join(missing) + "\n"
            "شغّلي scripts/configure_capital_credentials.sh ثم أعيدي المحاولة.",
            file=sys.stderr,
        )
        return 1

    transport = GuardedTransport(
        inner=HttpxTransport(),
        execution_lock=ExecutionLock.locked(),   # مغلق دائماً في هذا الأمر
        rate_limiter=RateLimiter(),
    )
    session = CapitalSession(
        transport=transport, secrets=provider, environment=CapitalEnvironment.DEMO
    )
    adapter = CapitalComAdapter(session=session, execution_lock=ExecutionLock.locked())

    try:
        adapter.connect()
    except CapitalAuthLockout as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 1
    except CapitalAuthError as exc:
        print(
            f"⛔ فشلت المصادقة مع Capital.com Demo: {exc}\n"
            "لن يُعاد المحاولة تلقائياً ولن يُجرَّب عنوان Live.",
            file=sys.stderr,
        )
        return 1
    except LiveApiBlocked as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 2

    try:
        report = run_discovery(adapter, epics=tuple(args.epics), fetch_candles=not args.no_candles)
    finally:
        adapter.disconnect()

    try:
        assert_read_only_session(transport)
    except DiscoveryViolation as exc:
        print(f"⛔ خرق قراءة-فقط: {exc}", file=sys.stderr)
        return 3

    json_path, md_path = write_reports(
        report,
        json_path=args.json_out or (REPO_ROOT / "docs" / "capital_demo_discovery.json"),
        markdown_path=args.markdown_out or (REPO_ROOT / "docs" / "CAPITAL_COM_DEMO_DISCOVERY.md"),
    )
    print(f"وقت التوليد (الرياض): {report.generated_at_riyadh}")
    print(f"البيئة: {report.environment}   الحساب: {report.account_masked}")
    print(f"تقرير JSON     : {json_path}")
    print(f"تقرير Markdown : {md_path}")
    if report.errors:
        print("\nأخطاء مسجّلة:")
        for e in report.errors:
            print(f"  - {e}")
    return 0


def cmd_capital_auth_probe(args: argparse.Namespace) -> int:
    """
    تشخيص مصادقة واحد على Demo. محاولة واحدة كحد أقصى لكل وضع،
    `POST /session` فقط، ولا تراجع إلى Live بحال.
    """
    if args.environment.lower() != "demo":
        print("⛔ التشخيص مسموح على demo فقط.", file=sys.stderr)
        return 2
    # وقفٌ عامّ محذوف — الشرط أعلاه خاصّ بالنداء ويكفي.

    provider = build_secret_provider(env_file=args.secrets_file, allow_process_env=False)
    missing = provider.missing(REQUIRED_CAPITAL_SECRETS)
    if missing:
        print(
            "اعتمادات ناقصة: " + ", ".join(missing) + "\n"
            "شغّلي scripts/configure_capital_credentials.sh ثم أعيدي المحاولة.",
            file=sys.stderr,
        )
        return 1

    transport = GuardedTransport(
        inner=HttpxTransport(),
        execution_lock=ExecutionLock.locked(),
        rate_limiter=RateLimiter(),
    )
    try:
        report = run_auth_probe(
            transport=transport,
            secrets=provider,
            environment=CapitalEnvironment.DEMO,
        )
    except ProbeViolation as exc:
        print(f"⛔ انتهاك في التشخيص: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        # لا تفاصيل خام: قد تحمل رسالة الاستثناء ما لا يجوز عرضه.
        print(f"⛔ تعذّر إكمال التشخيص: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(render_report(report))
    return 0 if report.working_mode is not None else 1


LIVE_ACKNOWLEDGEMENT_AR = """
════════════════════════════════════════════════════════════════════
  اكتشاف الحساب الحقيقي — قراءة فقط
════════════════════════════════════════════════════════════════════

  • هذا هو حساب Capital.com **الحقيقي**، لا حساب تجريبي.
  • مفتاح API نفسه **يملك صلاحية التداول** لدى الوسيط.
  • هذا التطبيق سيسمح بـ**المصادقة والقراءات المُدرَجة في قائمة بيضاء فقط**.
  • **لا إذن** بإرسال أمر، ولا بفتح أو تعديل أو إغلاق مركز،
    ولا بتغيير أي إعداد حساب، ولا بإيداع أو سحب.

  الحماية مفروضة على مستوى HTTP نفسه:
    PUT و PATCH و DELETE مرفوضة دائماً · POST مسموح للمصادقة وحدها ·
    كل مسار خارج القائمة البيضاء مرفوض قبل مغادرة الطلب.

  لن تُعرض أي قيمة سرّية، ولن يُطبع معرّف الحساب كاملاً.
════════════════════════════════════════════════════════════════════
"""


def cmd_capital_live_discover(args: argparse.Namespace) -> int:
    """
    اكتشاف الحساب الحقيقي — قراءة فقط، بقائمة بيضاء على مستوى HTTP.

    ترتيب مقصود: **فحص خصوصية المخرجات يسبق المصادقة**. لا معنى لجلب رصيد
    حقيقي ثم اكتشاف أن لا مكان آمناً لكتابته.
    """
    if not args.acknowledge_live_read_only:
        print(
            "⛔ هذا الأمر يمسّ الحساب الحقيقي ولا يعمل بلا إقرار صريح.\n"
            "   أعيديه هكذا:\n"
            "   python3 -m app.cli capital-live-discover --acknowledge-live-read-only",
            file=sys.stderr,
        )
        return 2

    print(LIVE_ACKNOWLEDGEMENT_AR)

    # --- 1) فحص خصوصية المخرجات — قبل أي شبكة ---------------------------
    try:
        preflight_result = require_private_output(REPO_ROOT)
    except PrivateStoreError as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        print("لم تُجرَ أي مصادقة ولم يُرسَل أي طلب.", file=sys.stderr)
        return 4
    print(preflight_result.summary_ar())
    print()

    provider = build_secret_provider(env_file=args.secrets_file, allow_process_env=False)
    missing = provider.missing(REQUIRED_CAPITAL_SECRETS)
    if missing:
        print(
            "اعتمادات ناقصة: " + ", ".join(missing) + "\n"
            "شغّلي scripts/configure_capital_credentials.sh ثم أعيدي المحاولة.",
            file=sys.stderr,
        )
        return 1

    # --- 2) المصادقة ----------------------------------------------------
    transport = LiveReadOnlyTransport()
    session = LiveSession(transport=transport, secrets=provider)
    try:
        session.authenticate()
    except LiveAuthError as exc:
        print("المصادقة: ❌ فشلت", file=sys.stderr)
        print(f"⛔ {exc}", file=sys.stderr)
        return 1
    except LiveTransportError as exc:
        print("المصادقة: ❌ فشلت", file=sys.stderr)
        print(f"⛔ تعذّر الاتصال: {exc}", file=sys.stderr)
        return 1
    except AllowlistViolation as exc:
        print(f"⛔ منعت القائمة البيضاء الطلب: {exc}", file=sys.stderr)
        return 3

    print("المصادقة: ✅ نجحت")

    # --- 3) الاكتشاف ----------------------------------------------------
    try:
        report = run_live_discovery(
            session, epics=tuple(args.epics), fetch_candles=not args.no_candles
        )
    finally:
        session.discard()

    # --- 4) الكتابة إلى المخزن الخاص وحده --------------------------------
    try:
        json_path = write_private_discovery_json(report, REPO_ROOT)
        md_path = write_private_discovery_markdown(report, REPO_ROOT)
    except PrivateStoreError as exc:
        print(f"⛔ تعذّرت الكتابة الآمنة: {exc}", file=sys.stderr)
        return 4

    # --- 4ب) الجدوى -------------------------------------------------------
    # الرصيد يُصنَّف قبل استعماله. الحساب غير المموَّل **حالة صحيحة**: الاكتشاف
    # يكتمل، والجدوى الفعلية تُصنَّف ACCOUNT_NOT_FUNDED، ولا يُختلَق أي رقم.
    eurusd = report.instrument("EURUSD")
    assessment = assess_equity(report.account.balance if report.account else None)
    actual_path = None
    public_path = None
    if eurusd is not None and eurusd.found:
        actual = (
            compute_feasibility(eurusd, equity=assessment.equity)
            if assessment.usable else None
        )
        planned = compute_feasibility(eurusd, equity=PLANNED_CAPITAL_USD)

        try:
            actual_path = write_private_actual_feasibility(
                report, REPO_ROOT, actual=actual, assessment=assessment
            )
            # التقرير العام: سيناريو 150 دولاراً وشروط الأداة فقط — بلا أي قيمة
            # حساب. يُكتب **دائماً**، مموَّلاً كان الحساب أو لا.
            public_path = write_public_text(
                REPO_ROOT / "docs" / "CAPITAL_COM_150_USD_FEASIBILITY.md",
                render_public_feasibility_markdown(
                    planned=planned, instrument_epic="EURUSD", instrument=eurusd,
                ),
            )
        except PrivateStoreError as exc:
            print(f"⛔ تعذّرت الكتابة الآمنة: {exc}", file=sys.stderr)
            return 4

    # --- 5) مخرَج الطرفية: المسموح فقط ------------------------------------
    # لا رصيد · لا أموال متاحة · لا ربح/خسارة · لا معرّف حساب (ولو مُقنَّعاً).
    currency = report.account.currency if report.account else None
    print(f"عملة الحساب: {currency or 'غير معلومة'}")

    found = sum(1 for i in report.instruments if i.found)
    print(f"اكتشاف الأدوات: {found}/{len(report.instruments)} قُرئت بنجاح")
    for instrument in report.instruments:
        print(f"  {'✅' if instrument.found else '❌'} {instrument.epic}")

    print()
    print("التقارير الخاصة (خارج git):")
    print(f"  {md_path}")
    print(f"  {json_path}")
    if actual_path:
        print(f"  {actual_path}")
    if public_path:
        print(f"\nتقرير عام (بلا أي قيمة حساب): {public_path}")

    # الاكتمال والتمويل بُعدان منفصلان: الاكتشاف قد يكتمل تماماً على حساب
    # غير مموَّل. الأول يحدّد رمز الخروج، والثاني يحدّد GO/NO-GO للجدوى.
    discovery_complete = bool(
        report.account and found == len(report.instruments) and not report.errors
    )
    go = discovery_complete and assessment.usable

    print()
    if go:
        print("الحالة: GO — الاكتشاف مكتمل")
    elif discovery_complete:
        # لا يُطبع الرصيد — التصنيف وحده.
        print(f"الحالة: NO-GO — {assessment.status} (الاكتشاف مكتمل)")
        print("  تحجيم المراكز على الرصيد الفعلي غير متاح.")
        print("  الجدوى بسيناريو 150 دولاراً المخطَّط محسوبة في التقرير العام.")
    else:
        print("الحالة: NO-GO — الاكتشاف ناقص")
    if report.errors:
        print("أسباب:")
        for error in report.errors:
            print(f"  - {error}")
    print(
        "\nهذه نتيجة اكتشاف قراءة فقط. **لا تأذن بالتنفيذ**: "
        "لا استراتيجية معتمدة، وقفل Live العام ما زال مغلقاً."
    )
    # رمز الخروج يعكس **اكتمال الاكتشاف** لا تمويل الحساب: حسابٌ غير مموَّل
    # ليس فشلاً في القراءة.
    return 0 if discovery_complete else 1


SPREAD_ACKNOWLEDGEMENT_AR = """
════════════════════════════════════════════════════════════════════
  قياس سبريد EUR/USD — قراءة فقط على الحساب الحقيقي
════════════════════════════════════════════════════════════════════

  • جلسة مصادقة **واحدة**، ثم لقطات سوق متكررة لـEUR/USD وحده.
  • **لا يُطلب رصيد ولا أموال متاحة ولا تفضيلات ولا مراكز** — القياس
    لا يحتاج بيانات حساب، فلا تُطلب أصلاً.
  • PUT و PATCH و DELETE مرفوضة دائماً · POST للمصادقة وحدها.
  • المخرَج **غير حسّاس**: أسعار وسبريد فقط.

  **لقطة واحدة ليست «السبريد المعتاد».** هذا الأمر يبني توزيعاً.
════════════════════════════════════════════════════════════════════
"""


def cmd_capital_live_spread_sample(args: argparse.Namespace) -> int:
    """
    يقيس توزيع سبريد EUR/USD عبر الزمن — قراءة فقط، بجلسة واحدة.

    لا يكتب شيئاً في المخزن الخاص: مخرَجه لا يحتوي أي قيمة حساب، فلا يحتاج
    فحص الخصوصية الذي يحتاجه الاكتشاف.
    """
    if not args.acknowledge_live_read_only:
        print(
            "⛔ هذا الأمر يمسّ الحساب الحقيقي ولا يعمل بلا إقرار صريح.\n"
            "   أعيديه هكذا:\n"
            "   python3 -m app.cli capital-live-spread-sample "
            "--acknowledge-live-read-only",
            file=sys.stderr,
        )
        return 2

    print(SPREAD_ACKNOWLEDGEMENT_AR)

    provider = build_secret_provider(env_file=args.secrets_file, allow_process_env=False)
    missing = provider.missing(REQUIRED_CAPITAL_SECRETS)
    if missing:
        print(
            "اعتمادات ناقصة: " + ", ".join(missing) + "\n"
            "شغّلي scripts/configure_capital_credentials.sh ثم أعيدي المحاولة.",
            file=sys.stderr,
        )
        return 1

    transport = LiveReadOnlyTransport()
    session = LiveSession(transport=transport, secrets=provider)
    try:
        session.authenticate()
    except LiveAuthError as exc:
        print("المصادقة: ❌ فشلت", file=sys.stderr)
        print(f"⛔ {exc}", file=sys.stderr)
        return 1
    except LiveTransportError as exc:
        print("المصادقة: ❌ فشلت", file=sys.stderr)
        print(f"⛔ تعذّر الاتصال: {exc}", file=sys.stderr)
        return 1
    except AllowlistViolation as exc:
        print(f"⛔ منعت القائمة البيضاء الطلب: {exc}", file=sys.stderr)
        return 3

    print("المصادقة: ✅ نجحت")
    print(
        f"القياس: {SPREAD_SAMPLE_EPIC} · {args.duration_minutes} دقيقة · "
        f"كل {args.interval_seconds} ثانية. اتركي النافذة مفتوحة."
    )

    try:
        run = run_spread_sampling(
            session,
            duration_minutes=args.duration_minutes,
            interval_seconds=args.interval_seconds,
        )
    except SpreadSamplerError as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 2
    except AllowlistViolation as exc:
        print(f"⛔ منعت القائمة البيضاء الطلب: {exc}", file=sys.stderr)
        return 3
    finally:
        session.discard()

    text = render_spread_report(run)
    if args.markdown_out:
        out = Path(args.markdown_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"\nالتقرير: {out}")

    stats = run.statistics
    print()
    print(f"عيّنات مقبولة: {stats.count_accepted} · مرفوضة: {stats.count_rejected}")
    if stats.count_accepted == 0:
        print("⛔ لا عيّنة مقبولة — لا يُستخرج توزيع من لا شيء.")
        return 1

    def p(v):
        return f"{v:.2f}" if v is not None else "—"

    print(
        f"السبريد بالنقاط — الأدنى {p(stats.minimum)} · الوسيط {p(stats.median)} · "
        f"p75 {p(stats.p75)} · p95 {p(stats.p95)} · الأقصى {p(stats.maximum)}"
    )
    flagged = run.flagged_samples
    if flagged:
        print(f"عيّنات في نافذة إغلاق/تجديد: {len(flagged)} — موسومة في التقرير.")
    print(
        "\n**لقطة واحدة ليست السبريد المعتاد**، وهذا التقرير لا يدّعي ربحية "
        "ولا يأذن بالتنفيذ."
    )
    return 0


def cmd_provider_probe(args: argparse.Namespace) -> int:
    """
    يُثبت قدرة الخطة لدى مزوّد — **طلب واحد، قراءة فقط**.

    لا يُشغَّل تلقائياً ولا في أي اختبار. المالكة تشغّله بمفتاحها على جهازها،
    ولا يُطلب المفتاح في أي محادثة.
    """
    if args.probe not in AVAILABLE_PROBES:
        print(
            f"⛔ مسبار غير معروف: {args.probe}. المتاح: {', '.join(AVAILABLE_PROBES)}",
            file=sys.stderr,
        )
        return 2

    provider_secrets = build_secret_provider(
        env_file=args.secrets_file, allow_process_env=False
    )
    missing = provider_secrets.missing(("FMP_API_KEY",))
    if missing:
        print(
            "المفتاح FMP_API_KEY غير مُعدّ.\n"
            "شغّلي scripts/configure_provider_credentials.sh ثم أعيدي المحاولة.\n"
            "**لا يُلصَق مفتاح في المحادثة.**",
            file=sys.stderr,
        )
        return 1

    provider = FmpEconomicCalendarProvider(
        api_key=provider_secrets.get("FMP_API_KEY")
    )
    outcome = probe_fmp_calendar(provider)
    print(outcome.report_ar())
    return 0 if outcome.usable else 1


def cmd_provider_status(args: argparse.Namespace) -> int:
    """يعرض حالة إعداد المزوّدين **بلا كشف أي قيمة**."""
    provider_secrets = build_secret_provider(
        env_file=args.secrets_file, allow_process_env=False
    )
    print("حالة اعتمادات المزوّدين — لا تُعرض أي قيمة:")
    print()
    for name in PROVIDER_CREDENTIALS:
        present = not provider_secrets.missing((name,))
        print(f"  {'✅' if present else '❌'}  {name}")
    print()
    print("  ✅  EcbMacroDataProvider — لا يحتاج مفتاحاً (وصول مفتوح)")
    print()
    print(
        "المفاتيح تبقى في Keychain، ولا تدخل التطبيق، ولا تُرسَل إلى أي طرف، "
        "ولا تُودَع في git."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Maather Autonomous Trader CLI")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--secrets-file",
        default=str(DEFAULT_SECRETS_FILE),
        help="ملف أسرار محلي احتياطي (صلاحية 600). الأفضلية دائماً لـKeychain.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser(
        "capital-discover", help="اكتشاف Capital.com Demo — قراءة فقط"
    )
    discover.add_argument("--environment", default="demo", choices=["demo"])
    discover.add_argument("--epics", nargs="*", default=list(DISCOVERY_EPICS))
    discover.add_argument("--json-out", default=None)
    discover.add_argument("--markdown-out", default=None)
    discover.add_argument("--no-candles", action="store_true")
    discover.set_defaults(func=cmd_capital_discover)

    live = sub.add_parser(
        "capital-live-discover",
        help="اكتشاف الحساب الحقيقي — قراءة فقط، بإقرار صريح",
    )
    live.add_argument(
        "--acknowledge-live-read-only",
        action="store_true",
        help="إقرار صريح بأن هذا الحساب الحقيقي وأن الوضع قراءة فقط",
    )
    live.add_argument("--epics", nargs="*", default=list(LIVE_DISCOVERY_EPICS))
    live.add_argument("--json-out", default=None)
    live.add_argument("--markdown-out", default=None)
    live.add_argument("--no-candles", action="store_true")
    live.set_defaults(func=cmd_capital_live_discover)

    spread = sub.add_parser(
        "capital-live-spread-sample",
        help="قياس توزيع سبريد EUR/USD — قراءة فقط، بجلسة واحدة",
    )
    spread.add_argument(
        "--acknowledge-live-read-only",
        action="store_true",
        help="إقرار صريح بأن هذا الحساب الحقيقي وأن الوضع قراءة فقط",
    )
    spread.add_argument("--duration-minutes", type=int, default=30)
    spread.add_argument("--interval-seconds", type=int, default=60)
    spread.add_argument("--markdown-out", default=None)
    spread.set_defaults(func=cmd_capital_live_spread_sample)

    probe = sub.add_parser(
        "capital-auth-probe",
        help="تشخيص مصادقة Demo: يقارن وضعَي كلمة المرور — محاولة واحدة لكل وضع",
    )
    probe.add_argument("--environment", default="demo", choices=["demo"])
    probe.set_defaults(func=cmd_capital_auth_probe)

    probe_cmd = sub.add_parser(
        "provider-probe", help="إثبات قدرة خطة مزوّد — طلب واحد، قراءة فقط",
    )
    probe_cmd.add_argument("probe", choices=list(AVAILABLE_PROBES))
    probe_cmd.set_defaults(func=cmd_provider_probe)

    provider_status = sub.add_parser(
        "provider-status", help="حالة إعداد المزوّدين بلا كشف أي قيمة",
    )
    provider_status.set_defaults(func=cmd_provider_status)

    status = sub.add_parser("secrets-status", help="فحص وجود الاعتمادات بلا كشفها")
    status.set_defaults(func=cmd_secrets_status)

    const = sub.add_parser("constitution", help="عرض دستور المخاطر وبصماته")
    const.set_defaults(func=cmd_constitution)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
