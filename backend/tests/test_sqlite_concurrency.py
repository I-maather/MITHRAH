"""
إعداداتُ SQLite للتزامن — اختبارُ انحدار.

في ٢٠٢٦-٠٩-١٥ ٢٠:٠١Z فشلت كتابةُ الدفتر بـ`OperationalError` تحت
`journal_mode=delete`، فبقي مركزان مفتوحَين في دفترٍ لا يطابق الوسيط،
فأقفلت بوابةُ الإقلاع أربعة أيام. الاختبارُ يحرس ألّا يعود الوضع.
"""
from __future__ import annotations

from sqlalchemy import text

from app.db.session import make_engine


def test_file_database_uses_wal_and_waits(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'probe.db'}")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() >= 30000
