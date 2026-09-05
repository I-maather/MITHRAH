"""
`trades` مهجورٌ موثَّق — ولا يعود قارئٌ إنتاجيّ إليه صامتاً.

قرار المالكة 2026-09-05: **الخيار (ب)** — يبقى الجدول، ويُوسَم، ويمنع اختبارٌ
أيَّ اعتمادٍ إنتاجيّ عليه. ولا يُحذف الجدول ولا صفوفُه.

## لماذا حارسٌ لا مجرّد تعليق

`load_session_state` كانت تبني منه أربعةَ عدّاداتِ مخاطرة، وهو جدولٌ لا
يُكتَب فيه — فكانت أربعُ بوّاباتٍ تقرأ من فراغ سنةً كاملة بلا أن يلاحظ أحد.
والتعليقُ لا يمنع عودةَ ذلك؛ الاختبارُ يمنعها.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: الموضع الوحيد المسموح: تعريفُ الصفّ نفسه.
ALLOWED = {"db/models.py"}


def _uses_trade_row(path: pathlib.Path) -> bool:
    """
    هل يُستعمَل `TradeRow` **في الشيفرة**؟

    بالشجرة النحوية لا بالبحث النصّي: خمسةُ ملفّاتٍ تذكره في توثيقها لتشرح
    لماذا هُجر — وبحثٌ نصّيٌّ يعاقب الشرح الصادق ويمرّر الاستعمال المخفيّ في
    سلسلةٍ نصّية.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "TradeRow":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "TradeRow":
            return True
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "TradeRow" for alias in node.names):
                return True
    return False


class TestNoProductionReaderDependsOnTheDeadTable:
    def test_only_the_model_file_mentions_it_in_code(self):
        offenders = []
        for path in sorted(APP.rglob("*.py")):
            rel = path.relative_to(APP).as_posix()
            if rel in ALLOWED:
                continue
            if _uses_trade_row(path):
                offenders.append(rel)
        assert offenders == [], (
            "عاد قارئٌ إنتاجيّ إلى `trades` — وهو جدولٌ لا يُكتَب فيه. "
            f"المواضع: {offenders}. المصدر هو `position_book`."
        )

    def test_the_risk_state_reads_the_book_we_write(self):
        from app.risk import session_state as ss

        tree = ast.parse(pathlib.Path(ss.__file__).read_text(encoding="utf-8"))
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        assert "PositionBookRow" in used
        assert "TradeRow" not in used

    def test_the_table_itself_is_not_deleted(self):
        """الهجرُ لا يعني الحذف: الجدول يبقى، وصفوفُه (إن ظهرت) شهادةٌ لا تُمحى."""
        from app.db.models import Base, TradeRow

        assert TradeRow.__tablename__ == "trades"
        assert "trades" in Base.metadata.tables

    def test_it_carries_a_written_reason(self):
        from app.db.models import TradeRow

        doc = TradeRow.__doc__ or ""
        assert "مهجور" in doc, "الجدول مهجورٌ بلا سببٍ مكتوب — والقارئ التالي لن يعرف."
