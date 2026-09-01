"""
مراكز الحساب التجريبي — **قراءة**، وإغلاقٌ بموافقة صريحة.

    # قراءة فقط، بلا موافقة، بلا خطر:
    python -m app.diagnostics.demo_positions

    # إغلاق مركزٍ بعينه:
    python -m app.diagnostics.demo_positions --close <dealId> \\
        --approve "أوافق على إغلاق هذا المركز"

## لماذا وُجد هذا الملف

في 2026-09-01 أرسل `demo_round_trip` أمراً، وأكّده الوسيط بمعرّف صفقة، ثم
**لم يظهر المركز في القائمة** فور القراءة. فرفع التحقّق `CapitalExecutionUncertain`
— وهو الصواب — لكن `finally` في السكربت لم يكن يعرف المعرّف بعد، فلم يُحاول
الإغلاق. أي أن مركزاً قد يكون مفتوحاً بلا أن يغلقه أحد.

**والدرس ليس «خفّف التحقّق»، بل «افصل القراءة عن الحكم»:** حالةٌ غامضة
تستدعي عيناً بشرية وأداةً تقرأ الحقيقة من الوسيط — لا محاولةً ثانية.

## ما لا يفعله

لا يفتح مركزاً، ولا يلمس الحساب الحقيقي، ولا يغيّر إعداداً، ولا يطبع سرّاً.
"""
from __future__ import annotations

import argparse
import sys

APPROVAL_PHRASE = "أوافق على إغلاق هذا المركز"

OK, BAD, WARN, DIM, END = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser(description="قراءة مراكز Demo، وإغلاقٌ بموافقة")
    ap.add_argument("--close", default="", help="معرّف الصفقة المراد إغلاقها")
    ap.add_argument("--approve", default="")
    a = ap.parse_args()

    from app.brokers.capital.endpoints import CapitalEnvironment
    from app.brokers.capital.safety import ExecutionLock
    from app.brokers.factory import build_capital_adapter
    from app.clock import now_utc
    from app.config import get_settings
    from app.secretstore.provider import build_secret_provider

    settings = get_settings()
    secrets = build_secret_provider(env_file=settings.secrets_file, allow_process_env=False)

    # القفل يُفتح **فقط** إن طُلب إغلاق وبموافقة. والقراءة لا تحتاجه.
    lock = ExecutionLock.locked()
    if a.close:
        if a.approve.strip() != APPROVAL_PHRASE:
            print(
                f"{BAD}⛔ الإغلاق يحتاج موافقة صريحة.{END}\n"
                f'   أضيفي:  --approve "{APPROVAL_PHRASE}"',
                file=sys.stderr,
            )
            return 2
        lock = lock.authorise(
            owner_authorization_reference="D15/2026-09-01",
            reason_ar="إغلاق مركزٍ تجريبي بقيَ مفتوحاً بعد حالة تنفيذٍ غامضة.",
            at=now_utc(),
        )

    adapter = build_capital_adapter(CapitalEnvironment.DEMO, secrets=secrets, execution_lock=lock)
    adapter.connect()
    if adapter.is_live:
        print(f"{BAD}⛔ المحوّل يقول إنه حقيقي. توقّف.{END}", file=sys.stderr)
        return 3
    print(f"\n{OK}✅{END} {adapter.name}")

    positions = list(adapter.list_positions())
    if not positions:
        print(f"\n{OK}✅ لا مراكز مفتوحة على الحساب التجريبي.{END}")
        print(f"{DIM}   الأمر السابق لم يترك مركزاً — الحالة الغامضة انتهت إلى لا شيء.{END}\n")
        return 0

    print(f"\n\033[1m▸ {len(positions)} مركزاً مفتوحاً\033[0m\n")
    for p in positions:
        guard = (
            f"{OK}وقف {p.stop_level}{END}" if p.stop_level is not None
            else f"{BAD}**بلا وقف عند الوسيط**{END}"
        )
        print(f"  {p.deal_id}")
        print(f"    {p.epic} · {p.direction} · كمية {p.size} · دخول {p.level}")
        print(f"    {guard} · هدف {p.profit_level} · ربح/خسارة {p.upl}\n")

    if not a.close:
        print(f"{WARN}○ قراءة فقط. للإغلاق أعيدي الأمر مع --close <dealId> والموافقة.{END}\n")
        return 0

    target = next((p for p in positions if str(p.deal_id) == str(a.close)), None)
    if target is None:
        print(f"{BAD}⛔ لا مركز بالمعرّف {a.close} — راجعي القائمة أعلاه.{END}", file=sys.stderr)
        return 1

    print(f"{DIM}   إغلاق {target.deal_id} …{END}")
    closed = adapter.close_position(str(target.deal_id))
    print(f"{OK}✅{END} أُغلق · الحالة {closed.status.value} · السعر {closed.average_fill_price}")

    remaining = {str(p.deal_id) for p in adapter.list_positions()}
    if str(target.deal_id) in remaining:
        print(f"{BAD}⛔ ما زال في القائمة بعد إغلاقٍ «ناجح». أغلقيه من موقع كابيتال.{END}",
              file=sys.stderr)
        return 1
    print(f"{OK}✅{END} اختفى من القائمة.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
