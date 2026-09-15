"""هجرةٌ خفيفة — `create_all` يُنشئ ولا يُعدّل.

`Base.metadata.create_all(checkfirst=True)` يتخطّى الجدولَ القائم كلّه. فعمودٌ
جديد على جدولٍ موجودٍ في الإنتاج **لا يُنشأ أبداً**، ويظهر العطل بعد النشر
لا قبله: `no such column`. وهذا الملف يضيف ما نقص، مرّةً وبلا أثرٍ إن تكرّر،
ولا يحذف عموداً ولا يغيّر نوعاً — الحذفُ قرارٌ لا هجرةٌ تلقائية.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

_LOG = logging.getLogger(__name__)

#: (جدول، عمود، تعريف SQL) — تُضاف بالترتيب، وتُتخطّى إن وُجدت.
ADDITIONS: tuple[tuple[str, str, str], ...] = (
    ("position_book", "reconciliation", "VARCHAR(16) DEFAULT 'STALE'"),
    ("position_book", "last_confirmed_utc", "DATETIME"),
    ("position_book", "absent_confirmations", "INTEGER DEFAULT 0"),
    # E3 — كلّها بلا `DEFAULT`: الصفقات السابقة لهذه الأعمدة تبقى `NULL`
    # صراحةً. وقيمةٌ افتراضية هنا تكذب: تجعل «لم يُقيَّم» تبدو تقييماً.
    ("position_book", "initial_stop_price", "NUMERIC(20, 8)"),
    ("position_book", "decision_quality", "VARCHAR(16)"),
    ("position_book", "execution_quality", "VARCHAR(16)"),
    ("position_book", "assessment_source", "VARCHAR(32)"),
    ("position_book", "assessment_version", "VARCHAR(32)"),
    ("position_book", "assessed_at_utc", "DATETIME"),
    # 2026-09-05: قرارُ المخاطر بلا أداةٍ لا يُقرأ.
    ("risk_decisions", "symbol", "VARCHAR(24) DEFAULT ''"),
    # 2026-09-15: المركزُ لم يكن يُنسَب إلى قراره لأنّ هويّته عند الوسيط
    # غيرُ هويّة الصفقة. تُحفَظ الهويّاتُ كلُّها هنا ويُبحَث فيها.
    ("broker_orders", "position_deal_ids", "VARCHAR(512)"),
)


def missing(engine: Engine) -> list[tuple[str, str]]:
    """ما ينقص فعلاً — يُقرأ من القاعدة لا من الشيفرة."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    gaps: list[tuple[str, str]] = []
    for table, column, _ in ADDITIONS:
        if table not in tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        if column not in have:
            gaps.append((table, column))
    return gaps


def apply(engine: Engine) -> list[str]:
    """يضيف الأعمدة الناقصة ويعيد أسماء ما أُضيف."""
    gaps = set(missing(engine))
    if not gaps:
        return []
    added: list[str] = []
    with engine.begin() as connection:
        for table, column, ddl in ADDITIONS:
            if (table, column) not in gaps:
                continue
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            added.append(f"{table}.{column}")
    for name in added:
        _LOG.info("migrate: added column %s", name)
    return added


__all__ = ["ADDITIONS", "missing", "apply"]
