"""Database configuration and session utilities."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def _validate_database_url(database_url: str) -> str:
    if not database_url:
        raise RuntimeError("DATABASE_URL is required and must point to PostgreSQL with pgvector enabled")
    if not database_url.startswith("postgresql"):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection string for the RAG implementation")
    return database_url


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        database_url = _validate_database_url(get_database_url())
        _engine = create_engine(database_url, future=True, echo=False, pool_pre_ping=True)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def _apply_postgres_schema_updates(engine: Engine) -> None:
    inspector = inspect(engine)
    if "reply_examples" not in inspector.get_table_names():
        return

    statements = [
        "ALTER TABLE reply_examples ADD COLUMN IF NOT EXISTS example_key VARCHAR(128)",
        "ALTER TABLE reply_examples ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_reply_examples_source_example_key "
            "ON reply_examples (source, example_key) WHERE example_key IS NOT NULL"
        ),
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def init_db() -> None:
    """Create required extensions and tables."""
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    from . import db_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_postgres_schema_updates(engine)


def get_session() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope for scripts/background tasks."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
