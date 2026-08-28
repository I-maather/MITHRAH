#!/usr/bin/env python3
"""
أداة التحقق من سلامة سلسلة سجل التدقيق.

    python3 scripts/verify_audit_chain.py
    python3 scripts/verify_audit_chain.py --database-url sqlite:///./data/maather.db

مستوى الحماية الذي تقدّمه: **كشف** التعديل والحذف وإعادة الترتيب — لا منعها.
انظر docs/KNOWN_LIMITATIONS.md §5.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.audit.log import verify_chain  # noqa: E402
from app.audit.sqlstore import SqlAuditStore  # noqa: E402
from app.clock import format_riyadh  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    url = args.database_url or get_settings().database_url
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)

    with Session(engine, future=True) as session:
        events = list(SqlAuditStore(session).all())

    result = verify_chain(events)
    print(f"قاعدة البيانات : {url}")
    print(f"عدد الصفوف     : {len(events)}")

    if result.ok:
        print("النتيجة        : ✅ السلسلة سليمة")
        if events:
            print(f"أول حدث        : {format_riyadh(events[0].timestamp_utc)}")
            print(f"آخر حدث        : {format_riyadh(events[-1].timestamp_utc)}")
            print(f"آخر بصمة       : {events[-1].entry_hash}")
        return 0

    print("النتيجة        : ❌ السلسلة مكسورة")
    print(f"أول صف مشبوه   : {result.first_bad_sequence}")
    print(f"المشكلة        : {result.problem_ar}")
    print()
    print("الإجراء المطلوب: لا تُصلحي السلسلة. استعيدي من نسخة احتياطية سليمة،")
    print("واعتبري كل ما بعد الصف المكسور موضع شك حتى يُطابق مع كشف IBKR.")
    print("انظري docs/INCIDENT_RESPONSE.md §8.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
