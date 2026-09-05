"""
بوابةُ الإقلاع — الفحص الذي كان مكتوباً ولا يُستدعى.

## العيب

`db/recovery.run_startup_recovery` كُتب في 0.2 واختُبر وحدوياً: يقرأ قاطع
الطوارئ الدائم، ويبحث عن محاولات تنفيذ غير محسومة، ويطابق مراكزنا بمراكز
الوسيط، ويقفل عند أي شكّ. ثم **لم يُستدعَ من أيّ مكان في الخادم**. بحثٌ في
المستودع كلّه لا يجد له نداءً واحداً خارج اختباراته.

وهو نفس عيب طبقة الجوال قبل 0.5.6 بوجهٍ أخطر: هناك كانت الشاشة تقول «لا
جهاز مسجّل» وهي صادقة؛ هنا كان النظام يُقلع بلا أن يسأل الوسيط عمّا يحمله،
ثم يقرّر. اختبارُ الوحدة يثبت أن القطعة صحيحة، ولا يثبت أنها **مركَّبة**.

## القاعدة

الإقلاع لا يفتح شيئاً. يقفل، ثم يحاول إثبات أنه يستحق أن يُسمح له بالدخول —
لا العكس. وحتى حين تنجح كلُّ الفحوص يبقى فتحُ التداول قراراً بشرياً موثّقاً.
"""
from __future__ import annotations

import logging
from typing import Optional

from ..clock import now_utc
from ..contracts import Position
from ..db.recovery import StartupReport, StartupVerdict, run_startup_recovery
from ..db.session import get_session
from ..portfolio.book import read_portfolio
from ..portfolio.ledger import as_positions, mark_restart, open_rows

_LOG = logging.getLogger(__name__)

#: سببُ الحجب حين لم تجتز بوابةُ الإقلاع بعد.
STARTUP_RECONCILIATION_PENDING = "STARTUP_RECONCILIATION_PENDING"


def _book_positions(session) -> list[Position]:
    """
    مراكزُ الدفتر بشكل `Position` كي يقارنها المطابِق.

    تُقرأ من الدفتر لا من `positions`: ذاك جدولٌ لم يُكتَب فيه شيءٌ قط، وقراءتُه
    تعني أن المطابقة تقارن الوسيط بالفراغ فتقول «مركز غير معروف لدينا» عن كل
    مركز — ضجيجٌ يُدرِّب على تجاهل التقرير.
    """
    at = now_utc()
    return [
        Position(
            account_id=row.account_id or "",
            symbol=row.symbol,
            quantity=row.quantity,
            average_cost=row.entry_price if row.entry_price is not None else 0,
            as_of_utc=at,
        )
        for row in open_rows(session)
    ]


def run(state) -> Optional[StartupReport]:
    """
    يُنفَّذ مرّةً عند إقلاع الخادم. يضع التقرير في `state.startup`.

    **لا يُسقط الإقلاع أبداً.** خادمٌ لا يُقلع يُخفي عطله؛ وخادمٌ يُقلع مقفولاً
    يُظهره. فأيُّ استثناءٍ هنا يصير حكمَ قفلٍ صريحاً لا انهياراً صامتاً.
    """
    try:
        with get_session() as session:
            # قبل أوّل قراءة: يُطفأ علمُ «رُئي بعد الإقلاع» لكل مركزٍ مفتوح،
            # فيُعرَف بعد أوّل مزامنةٍ ما لم يعد موجوداً حقاً.
            reset = mark_restart(session)

            def _fetch():
                account_id = getattr(state.broker, "account_id", "") or ""
                snapshot = read_portfolio(state.broker, account_id=account_id, at=now_utc())
                if not snapshot.ok:
                    # **العجزُ يُرفَع استثناءً لا يُعاد قائمةً فارغة.** قائمةٌ
                    # فارغة تُقرأ «لا مراكز لدى الوسيط»، فيقول المطابِق إنّ كل
                    # مركزٍ في دفترنا مفقود — وهو أسوأ من الاعتراف بالعجز.
                    raise RuntimeError(snapshot.error_ar or snapshot.reason_code)
                at = snapshot.as_of_utc
                return [
                    Position(
                        account_id=snapshot.account_id or "",
                        symbol=p.symbol,
                        quantity=p.quantity,
                        average_cost=p.entry_price if p.entry_price is not None else 0,
                        as_of_utc=at,
                    )
                    for p in snapshot.open_positions
                ]

            report = run_startup_recovery(
                session,
                fetch_broker_positions=_fetch,
                local_positions=_book_positions(session),
            )
            book = as_positions(open_rows(session))
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("startup recovery failed: %s", type(exc).__name__)
        report = StartupReport(
            verdict=StartupVerdict.LOCKED_PENDING_RECONCILIATION,
            trading_locked=True,
            kill_switch_active=False,
            risk_mode="UNKNOWN",
            reconciliation_problems=[f"تعذّر تنفيذ فحص الإقلاع: {type(exc).__name__}."],
            notes_ar=["لا دخولَ جديد قبل أن يمرّ الفحص. المراقبة والإدارة تستمرّان."],
        )
        state.startup = report
        return report

    report.notes_ar.append(
        f"الدفتر يحمل {len(book)} مركزاً مفتوحاً عند الإقلاع "
        f"({reset} أُعيد ضبطُ علم الرؤية لها)."
    )
    unlinked = [p["deal_id"] for p in book if p["attribution"] != "LINKED"]
    if unlinked:
        report.notes_ar.append(
            f"{len(unlinked)} مركزاً بلا نسبةٍ إلى قرار: {', '.join(unlinked[:5])}."
        )
    # **بوابةٌ بلا أثرٍ بوابةٌ لا تُدقَّق.** كان الحكم يعيش في الذاكرة وحدها،
    # فلم يكن في السجلّ ما يشهد أنّ الفحص جرى أصلاً — ولا كيف انتهى.
    _LOG.info(
        "startup gate: verdict=%s locked=%s reset=%d book=%d unlinked=%d problems=%d",
        getattr(report.verdict, "name", report.verdict),
        report.trading_locked,
        reset,
        len(book),
        len(unlinked),
        len(report.reconciliation_problems or []),
    )
    for problem in report.reconciliation_problems or []:
        _LOG.warning("startup gate problem: %s", problem)

    state.startup = report
    return report


def blocks_new_entries(state) -> Optional[str]:
    """
    يعيد سببَ الحجب بالعربية، أو `None` إن اجتازت البوابة.

    **الغياب حجب.** تقريرٌ مفقود يعني أن الفحص لم يجرِ، ولا يُقرَأ ذلك نجاحاً.
    """
    report = getattr(state, "startup", None)
    if report is None:
        return "لم يجرِ فحصُ الإقلاع بعد — لا دخول قبل أن يجري."
    if report.verdict == StartupVerdict.READY_TRADING_STILL_LOCKED:
        return None
    if report.verdict == StartupVerdict.LOCKED_KILL_SWITCH:
        return "قاطع الطوارئ ما زال مفعّلاً بعد إعادة التشغيل."
    if report.verdict == StartupVerdict.LOCKED_UNKNOWN_EXECUTION:
        return (
            f"توجد {len(report.unresolved_attempts)} محاولةُ تنفيذٍ غير محسومة. "
            "تُحسَم بالقراءة من الوسيط، لا بإعادة الإرسال."
        )
    problems = report.reconciliation_problems
    if problems:
        return "مطابقةُ الإقلاع لم تنجح: " + problems[0]
    return "بوابةُ الإقلاع لم تُجتَز بعد."
