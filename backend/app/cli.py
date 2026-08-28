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
from .brokers.capital.safety import LIVE_API_ENABLED, ExecutionLock, LiveApiBlocked
from .brokers.capital.session import CapitalSession
from .brokers.capital.transport import GuardedTransport, HttpxTransport
from .clock import format_riyadh, now_utc
from .config import REPO_ROOT, get_settings
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
            "عنوان Live مقفل في الكود (safety.LIVE_API_ENABLED=False).",
            file=sys.stderr,
        )
        return 2
    if LIVE_API_ENABLED:
        print("⛔ حالة غير متوقعة: قفل Live مفتوح في الكود. توقّف.", file=sys.stderr)
        return 2

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
    if LIVE_API_ENABLED:
        print("⛔ قفل Live مفتوح في الكود. توقّف.", file=sys.stderr)
        return 2

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

    probe = sub.add_parser(
        "capital-auth-probe",
        help="تشخيص مصادقة Demo: يقارن وضعَي كلمة المرور — محاولة واحدة لكل وضع",
    )
    probe.add_argument("--environment", default="demo", choices=["demo"])
    probe.set_defaults(func=cmd_capital_auth_probe)

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
