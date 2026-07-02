"""Database wiring (+db module). SQLite by default; Postgres via the DATABASE_URL env var."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_sqlite_schema() -> None:
    # SQLite → create tables at startup. Postgres → schema is owned by Alembic (applied at deploy/CI).
    import app.models  # noqa: F401  (register models on Base.metadata)
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
