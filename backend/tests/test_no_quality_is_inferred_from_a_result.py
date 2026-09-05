"""
جودةُ القرار لا تُشتَقّ من النتيجة، و«لم يُقيَّم» ليست تقييماً.

صفقةٌ رابحة قد تكون قراراً رديئاً نجا، وصفقةٌ خاسرة قد تكون قراراً سليماً لم
يُوفَّق. فإذا قِيس القرارُ بنتيجته صار النظام يتعلّم الحظّ ويسمّيه مهارة.

وهذه الاختبارات تحرس ثلاثاً: أنّ غير المقيَّم يُقرأ `UNKNOWN` مهما كانت
نتيجته، وأنّ التقييم لا يُكتَب بلا مصدرٍ ونسخةٍ وتاريخ، وأنّ الصفقات التي
سبقت هذه الأعمدة تبقى فارغةً صراحةً ولا يُستنتَج لها شيء.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.clock import now_utc
from app.db import migrate
from app.db.models import Base, PositionBookRow
from app.portfolio.book import KIND_ADMINISTRATIVE
from app.review import quality as q


@pytest.fixture()
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _row(session, deal_id="d1", pnl=None, **kw):
    at = now_utc()
    row = PositionBookRow(
        broker_deal_id=deal_id,
        symbol="EURUSD",
        quantity=Decimal("1"),
        state="CLOSED",
        first_seen_utc=at,
        last_seen_utc=at,
        closed_at_utc=at,
        realised_pnl=pnl,
        **kw,
    )
    session.add(row)
    session.commit()
    return row


class TestTheOldTradesStayEmpty:
    def test_a_row_written_before_these_columns_is_all_none(self, session):
        row = _row(session)
        assert row.initial_stop_price is None
        assert row.decision_quality is None
        assert row.execution_quality is None
        assert row.assessment_source is None
        assert row.assessment_version is None
        assert row.assessed_at_utc is None

    def test_it_reads_as_unknown_and_says_it_was_not_assessed(self, session):
        view = q.read_quality(_row(session))
        assert view.decision == q.QUALITY_UNKNOWN
        assert view.execution == q.QUALITY_UNKNOWN
        assert view.assessed is False
        assert view.as_dict()["assessed"] is False


class TestNothingIsInferredFromTheResult:
    def test_a_large_win_is_not_read_as_a_sound_decision(self, session):
        view = q.read_quality(_row(session, pnl=Decimal("250")))
        assert view.decision == q.QUALITY_UNKNOWN
        assert view.assessed is False

    def test_a_large_loss_is_not_read_as_an_unsound_decision(self, session):
        view = q.read_quality(_row(session, pnl=Decimal("-250")))
        assert view.decision == q.QUALITY_UNKNOWN
        assert view.assessed is False

    def test_the_reader_never_looks_at_the_result(self):
        """
        برهانٌ بنيويّ: وحدة التقييم **لا تقرأ نتيجة الصفقة** ولا `state`.

        بالشجرة النحوية لا بالنصّ: التوثيق يذكر `realised_pnl` ليقول إنه
        لا يُقرأ — وبحثٌ نصّيٌّ يعاقب الشرح الصادق.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(q))
        touched = {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        } | {
            n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
        }
        for forbidden in ("realised_pnl", "gross_pnl", "net_pnl"):
            assert forbidden not in touched, (
                f"وحدةُ التقييم تقرأ {forbidden} — والجودةُ لا تُشتَقّ من النتيجة."
            )


class TestNoAssessmentWithoutItsProvenance:
    def test_a_version_is_required(self, session):
        with pytest.raises(q.AssessmentRefused):
            q.record_assessment(
                session, _row(session),
                decision=q.QUALITY_SOUND, execution=None,
                source=q.SOURCE_RULES, version="  ",
            )

    def test_an_unknown_source_is_refused(self, session):
        with pytest.raises(q.AssessmentRefused):
            q.record_assessment(
                session, _row(session),
                decision=q.QUALITY_SOUND, execution=None,
                source="VIBES", version="v1",
            )

    def test_a_grade_outside_the_ladder_is_refused(self, session):
        with pytest.raises(q.AssessmentRefused):
            q.record_assessment(
                session, _row(session),
                decision="EXCELLENT", execution=None,
                source=q.SOURCE_RULES, version="v1",
            )

    def test_an_empty_assessment_is_refused(self, session):
        with pytest.raises(q.AssessmentRefused):
            q.record_assessment(
                session, _row(session),
                decision=None, execution=None,
                source=q.SOURCE_RULES, version="v1",
            )

    def test_a_refused_assessment_leaves_the_row_untouched(self, session):
        row = _row(session)
        with pytest.raises(q.AssessmentRefused):
            q.record_assessment(
                session, row, decision="EXCELLENT", execution=None,
                source=q.SOURCE_RULES, version="v1",
            )
        assert row.decision_quality is None
        assert row.assessment_source is None

    def test_a_recorded_assessment_carries_source_version_and_date(self, session):
        row = _row(session)
        when = now_utc() - timedelta(minutes=5)
        view = q.record_assessment(
            session, row,
            decision=q.QUALITY_MARGINAL, execution=q.EXECUTION_DEGRADED,
            source=q.SOURCE_RULES, version="rules-2026.09.1", at=when,
        )
        assert view.assessed is True
        assert view.decision == q.QUALITY_MARGINAL
        assert view.execution == q.EXECUTION_DEGRADED
        assert row.assessment_source == q.SOURCE_RULES
        assert row.assessment_version == "rules-2026.09.1"
        # SQLite لا يحفظ المنطقة الزمنية، فيعود الوقت ساذجاً. اللحظةُ نفسها
        # واللبْسُ في التمثيل لا في القيمة — والمقارنة على اللحظة.
        stored = row.assessed_at_utc
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)
        assert stored == when


class TestTheAdministrativeKindExists:
    def test_a_row_can_be_marked_administrative(self, session):
        row = _row(session, kind=KIND_ADMINISTRATIVE)
        assert row.kind == "ADMINISTRATIVE"

    def test_it_is_not_the_default(self, session):
        assert _row(session, deal_id="d2").kind == "UNATTRIBUTED"


class TestTheMigrationCarriesEveryNewColumn:
    NEW = (
        "initial_stop_price",
        "decision_quality",
        "execution_quality",
        "assessment_source",
        "assessment_version",
        "assessed_at_utc",
    )

    def test_every_new_column_is_in_the_migration(self):
        listed = {c for t, c, _ in migrate.ADDITIONS if t == "position_book"}
        missing = [c for c in self.NEW if c not in listed]
        assert not missing, (
            f"أعمدةٌ في النموذج وليست في الهجرة: {missing}. "
            "`create_all` لا يُعدّل جدولاً قائماً، فالعمود لن يُنشأ في الإنتاج."
        )

    def test_no_new_column_carries_a_default(self):
        """قيمةٌ افتراضية هنا تكذب: تجعل «لم يُقيَّم» تبدو تقييماً."""
        for table, column, ddl in migrate.ADDITIONS:
            if column in self.NEW:
                assert "DEFAULT" not in ddl.upper(), (
                    f"{table}.{column} يحمل قيمةً افتراضية — والصفقات القديمة "
                    "يجب أن تبقى `NULL` صراحةً."
                )

    def test_the_migration_adds_them_to_an_older_table(self):
        """جدولٌ قديمٌ بلا الأعمدة الستّة تُضاف إليه — ولا تُلمَس بياناته."""
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as con:
            from sqlalchemy import text

            con.execute(text(
                "CREATE TABLE position_book ("
                " id INTEGER PRIMARY KEY, broker_deal_id VARCHAR(64),"
                " symbol VARCHAR(24), state VARCHAR(16))"
            ))
            con.execute(text(
                "INSERT INTO position_book (broker_deal_id, symbol, state)"
                " VALUES ('old-1', 'EURUSD', 'CLOSED')"
            ))
        added = migrate.apply(engine)
        for column in self.NEW:
            assert f"position_book.{column}" in added

        have = {c["name"] for c in sa_inspect(engine).get_columns("position_book")}
        assert set(self.NEW) <= have

        with engine.connect() as con:
            from sqlalchemy import text

            row = con.execute(text(
                "SELECT broker_deal_id, decision_quality, initial_stop_price"
                " FROM position_book"
            )).one()
        assert row[0] == "old-1"
        assert row[1] is None, "الصفقة القديمة اكتسبت تقييماً لم يُصدره أحد."
        assert row[2] is None

    def test_applying_twice_changes_nothing(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        assert migrate.apply(engine) == []
        assert migrate.apply(engine) == []
