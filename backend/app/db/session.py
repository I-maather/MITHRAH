from __future__ import annotations

from pathlib import Path
from threading import Lock

from sqlalchemy import create_engine
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
        return create_engine(url, connect_args={"check_same_thread": False}, future=True)
    return create_engine(url, future=True, pool_pre_ping=True)


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
        Base.metadata.create_all(engine or ENGINE)


def get_session() -> Session:
    return SessionLocal()
