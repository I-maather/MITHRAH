from __future__ import annotations

from pathlib import Path

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


def init_db(engine=None) -> None:
    Base.metadata.create_all(engine or ENGINE)


def get_session() -> Session:
    return SessionLocal()
