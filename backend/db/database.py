"""Database engine and session management.

SQLite by default for zero-setup development; set ``DATABASE_URL`` to a
PostgreSQL URL and the identical schema runs there - no code changes, because
every column type used is portable.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    # check_same_thread only applies to SQLite; pool settings only to servers.
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create tables and seed reference data. Safe to call repeatedly."""
    from db import models  # noqa: F401 - registers the mappers
    from db.seed import seed_reference_data

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed_reference_data(session)
