"""SQLAlchemy ORM models and helper utilities."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .database import Base
from .settings import QWEN_EMBEDDING_DIMENSION

EMBEDDING_DIMENSION = QWEN_EMBEDDING_DIMENSION


def _uuid_str() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    sessions: Mapped[list["ReplySession"]] = relationship("ReplySession", back_populates="user")
    threads: Mapped[list["ConversationThread"]] = relationship("ConversationThread", back_populates="user")
    examples: Mapped[list["ReplyExample"]] = relationship("ReplyExample", back_populates="user")


class ReplySession(Base):
    __tablename__ = "reply_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    incoming_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="sessions")


class ConversationThread(Base):
    __tablename__ = "conversation_threads"
    __table_args__ = (
        UniqueConstraint("user_id", "thread_id", "role", name="uq_conversation_threads_user_thread_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="threads")


class ReplyExample(Base):
    __tablename__ = "reply_examples"
    __table_args__ = (Index("ix_reply_examples_role_source", "role", "source"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    thread_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    reply_session_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("reply_sessions.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    example_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    scenario: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    incoming_text: Mapped[str] = mapped_column(Text, nullable=False)
    reply_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSION), nullable=False)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped[Optional[User]] = relationship("User", back_populates="examples")


class DatasetSyncState(Base):
    __tablename__ = "dataset_sync_states"

    dataset_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    example_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


def _lookup_external_id(external_id: Optional[str]) -> str:
    return (external_id or "anonymous").strip() or "anonymous"


def find_user_by_external_id(session: Session, external_id: Optional[str]) -> Optional[User]:
    lookup = _lookup_external_id(external_id)
    stmt = select(User).where(User.external_id == lookup)
    return session.execute(stmt).scalar_one_or_none()


def get_or_create_user(session: Session, external_id: Optional[str]) -> User:
    """Find or create a user given an external identifier."""

    lookup = _lookup_external_id(external_id)
    stmt = select(User).where(User.external_id == lookup)
    user = session.execute(stmt).scalar_one_or_none()
    if user:
        return user

    user = User(external_id=lookup, display_name=external_id or "Anonymous")
    session.add(user)
    session.flush()
    return user


def get_or_create_thread(
    session: Session,
    *,
    external_user_id: Optional[str],
    thread_id: str,
    role: str,
) -> ConversationThread:
    user = get_or_create_user(session, external_user_id)
    stmt = select(ConversationThread).where(
        ConversationThread.user_id == user.id,
        ConversationThread.thread_id == thread_id,
        ConversationThread.role == role,
    )
    thread = session.execute(stmt).scalar_one_or_none()
    if thread:
        return thread

    thread = ConversationThread(user_id=user.id, thread_id=thread_id, role=role, summary="")
    session.add(thread)
    session.flush()
    return thread


def get_reply_session(session: Session, session_id: str) -> Optional[ReplySession]:
    stmt = select(ReplySession).where(ReplySession.id == session_id)
    return session.execute(stmt).scalar_one_or_none()


def record_reply_session(
    session: Session,
    *,
    external_user_id: Optional[str],
    thread_id: str,
    role: str,
    incoming_text: str,
    options: list[str],
    meta: dict,
) -> ReplySession:
    """Persist a reply session and return the stored ORM instance."""

    user = get_or_create_user(session, external_user_id)
    thread = get_or_create_thread(
        session,
        external_user_id=external_user_id,
        thread_id=thread_id,
        role=role,
    )
    thread.updated_at = datetime.utcnow()
    reply_session = ReplySession(
        user_id=user.id,
        thread_id=thread_id,
        role=role,
        incoming_text=incoming_text,
        options=options,
        meta=meta,
    )
    session.add(reply_session)
    session.commit()
    session.refresh(reply_session)
    return reply_session


def list_recent_threads(
    session: Session,
    *,
    external_user_id: Optional[str],
    role: str,
    limit: int = 12,
) -> list[ConversationThread]:
    user = find_user_by_external_id(session, external_user_id)
    if user is None:
        return []

    stmt = (
        select(ConversationThread)
        .where(
            ConversationThread.user_id == user.id,
            ConversationThread.role == role,
        )
        .order_by(ConversationThread.updated_at.desc(), ConversationThread.thread_id.asc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars())


def delete_thread_data(
    session: Session,
    *,
    external_user_id: Optional[str],
    thread_id: str,
    role: str,
) -> bool:
    user = find_user_by_external_id(session, external_user_id)
    if user is None:
        return False

    stmt = select(ConversationThread).where(
        ConversationThread.user_id == user.id,
        ConversationThread.thread_id == thread_id,
        ConversationThread.role == role,
    )
    thread = session.execute(stmt).scalar_one_or_none()
    if thread is None:
        return False

    session.execute(
        delete(ReplyExample).where(
            ReplyExample.user_id == user.id,
            ReplyExample.thread_id == thread_id,
            ReplyExample.role == role,
            ReplyExample.source == "accepted",
        )
    )
    session.execute(
        delete(ReplySession).where(
            ReplySession.user_id == user.id,
            ReplySession.thread_id == thread_id,
            ReplySession.role == role,
        )
    )
    session.execute(delete(ConversationThread).where(ConversationThread.id == thread.id))
    session.commit()
    return True
