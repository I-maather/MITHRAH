from __future__ import annotations

from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from .models import Base


def make_engine(url: str | None = None):
    settings = get_settings()
    url = url or settings.database_url
    if url.startswith("sqlite"):
        path = url.replace("sqlite:///", "")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            future=True,
        )
        _tune_sqlite(engine)
        return engine
    return create_engine(url, future=True, pool_pre_ping=True)


def _tune_sqlite(engine) -> None:
    """
    **القفلُ الذي أسقط النظام أربعة أيام.**

    `journal_mode=delete` يقفل الملفَّ كلَّه عند كل كتابة، وكاتبان — حلقةُ
    القرار والواجهة — على قاعدةٍ واحدة يعني أنّ قارئاً واحداً يكفي ليُفشل
    الكاتبَ في الحال:

        sqlite3.OperationalError: database is locked

    وهو ما وقع في ٢٠٢٦-٠٩-١٥ ٢٠:٠١Z: فشلت كتابةُ الدفتر، فبقي مركزان
    مفتوحَين في دفترٍ لم يعد يطابق الوسيط، فأقفلت بوابةُ الإقلاع، فمات
    النظام أربعة أيام. العلاجُ عند الجذر لا عند النتيجة:

      WAL             — كاتبٌ واحد و**قرّاءٌ متزامنون**؛ القارئ لا يحجب الكاتب.
      busy_timeout    — الكاتبُ ينتظر ثلاثين ثانية بدل أن يرفع استثناءً فوراً.
      synchronous=NORMAL — الآمنُ والموصى به مع WAL؛ لا يفقد المعاملات
                          المثبَّتة، ويزيل مزامنةً قرصيةً لكل كتابة.

    ولا يُقلَّم `audit_events`: سلسلةُ تجزئتِه مترابطة، وحذفُ صفٍّ يكسر
    التدقيق إلى الأبد. الحجمُ لم يكن المشكلة قطّ — القفلُ كان.
    """

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()


ENGINE = make_engine()
SessionLocal = sessionmaker(bind=ENGINE, class_=Session, expire_on_commit=False, future=True)


#: قفل التهيئة — حارس ثانٍ مستقلّ عن قفل بناء النظام.
#:
#: `create_all(checkfirst=True)` يفحص ثم يُنشئ، وبين الفحص والإنشاء فجوة.
#: فخيطان يبدآن معاً يريان الجدول غائباً فيُنشئانه، ويفشل الثاني:
#:
#:     sqlite3.OperationalError: table accounts already exists
#:
#: القفل هنا لا يغني عن القفل في `main.system()` ولا يُغني عنه: ذاك يمنع
#: بناء النظام مرّتين، وهذا يحمي أي مسار آخر يهيّئ القاعدة.
_INIT_LOCK = Lock()


def init_db(engine=None) -> None:
    with _INIT_LOCK:
        target = engine or ENGINE
        Base.metadata.create_all(target)
        # **ثم ما لا يفعله `create_all`.** هو يُنشئ الجدول الغائب ويتخطّى
        # القائم كلَّه — فعمودٌ جديد على جدولٍ في الإنتاج لا يُنشأ، ويظهر
        # العطل بعد النشر لا قبله.
        from .migrate import apply as _apply_migrations

        _apply_migrations(target)


def get_session() -> Session:
    return SessionLocal()
