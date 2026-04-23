"""Curated reply dataset synchronization for local PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from langchain_openai import OpenAIEmbeddings
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from .curated_examples import (
    DATASET_NAME,
    CuratedExample,
    build_reply_example_content_hash,
    compute_dataset_file_hash,
    embedding_input_text,
    load_curated_examples,
)
from .db_models import DatasetSyncState, ReplyExample
from .safe_embeddings import SafeEmbeddingClient
from .settings import QWEN_API_KEY, QWEN_BASE_URL, QWEN_EMBEDDING_DIMENSION, QWEN_EMBEDDING_MODEL

EMBED_BATCH_SIZE = 128


@dataclass(frozen=True)
class ExistingCuratedExampleState:
    id: str
    example_key: str | None
    content_hash: str | None


@dataclass(frozen=True)
class ChangedCuratedExample:
    existing_id: str
    example: CuratedExample


@dataclass(frozen=True)
class CuratedSyncPlan:
    new_examples: list[CuratedExample]
    changed_examples: list[ChangedCuratedExample]
    stale_ids: list[str]
    unchanged_count: int


@dataclass(frozen=True)
class CuratedSyncResult:
    skipped: bool
    inserted: int
    updated: int
    deleted: int
    unchanged: int
    accepted_backfilled: int
    example_count: int
    file_hash: str


def should_skip_curated_sync(
    *,
    state_file_hash: str | None,
    state_example_count: int | None,
    dataset_file_hash: str,
    dataset_example_count: int,
    curated_row_count: int,
    invalid_curated_count: int,
) -> bool:
    return (
        bool(state_file_hash)
        and state_file_hash == dataset_file_hash
        and state_example_count == dataset_example_count
        and curated_row_count == dataset_example_count
        and invalid_curated_count == 0
    )


def plan_curated_sync(
    dataset_examples: Iterable[CuratedExample],
    existing_rows: Iterable[ExistingCuratedExampleState],
) -> CuratedSyncPlan:
    dataset_by_key = {example.example_key: example for example in dataset_examples}
    existing_by_key: dict[str, ExistingCuratedExampleState] = {}
    stale_ids: list[str] = []

    for row in existing_rows:
        if not row.example_key:
            stale_ids.append(row.id)
            continue
        if row.example_key not in dataset_by_key:
            stale_ids.append(row.id)
            continue
        if row.example_key in existing_by_key:
            stale_ids.append(row.id)
            continue
        existing_by_key[row.example_key] = row

    new_examples: list[CuratedExample] = []
    changed_examples: list[ChangedCuratedExample] = []
    unchanged_count = 0

    for example_key, example in dataset_by_key.items():
        existing = existing_by_key.get(example_key)
        if existing is None:
            new_examples.append(example)
        elif existing.content_hash != example.content_hash:
            changed_examples.append(ChangedCuratedExample(existing_id=existing.id, example=example))
        else:
            unchanged_count += 1

    return CuratedSyncPlan(
        new_examples=new_examples,
        changed_examples=changed_examples,
        stale_ids=stale_ids,
        unchanged_count=unchanged_count,
    )


def _chunked(items: list, size: int) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class CuratedDatasetSyncService:
    def __init__(self, session_factory: sessionmaker[Session]):
        if not QWEN_API_KEY:
            raise RuntimeError("QWEN_API_KEY or DASHSCOPE_API_KEY is required for curated dataset sync")
        self._session_factory = session_factory
        self._embedding_model = SafeEmbeddingClient(
            OpenAIEmbeddings(
                model=QWEN_EMBEDDING_MODEL,
                dimensions=QWEN_EMBEDDING_DIMENSION,
                openai_api_key=QWEN_API_KEY,
                openai_api_base=QWEN_BASE_URL,
                tiktoken_enabled=False,
                check_embedding_ctx_length=False,
            )
        )

    def sync(self, *, force: bool = False) -> CuratedSyncResult:
        dataset_examples = load_curated_examples()
        dataset_file_hash = compute_dataset_file_hash()

        with self._session_factory() as session:
            accepted_backfilled = self._backfill_legacy_accepted_examples(session)
            state = session.get(DatasetSyncState, DATASET_NAME)
            curated_row_count = (
                session.scalar(
                    select(func.count()).select_from(ReplyExample).where(ReplyExample.source == "curated")
                )
                or 0
            )
            invalid_curated_count = (
                session.scalar(
                    select(func.count()).select_from(ReplyExample).where(
                        ReplyExample.source == "curated",
                        or_(ReplyExample.example_key.is_(None), ReplyExample.content_hash.is_(None)),
                    )
                )
                or 0
            )

            if not force and should_skip_curated_sync(
                state_file_hash=state.file_hash if state else None,
                state_example_count=state.example_count if state else None,
                dataset_file_hash=dataset_file_hash,
                dataset_example_count=len(dataset_examples),
                curated_row_count=curated_row_count,
                invalid_curated_count=invalid_curated_count,
            ):
                if accepted_backfilled:
                    session.commit()
                return CuratedSyncResult(
                    skipped=True,
                    inserted=0,
                    updated=0,
                    deleted=0,
                    unchanged=len(dataset_examples),
                    accepted_backfilled=accepted_backfilled,
                    example_count=len(dataset_examples),
                    file_hash=dataset_file_hash,
                )

            existing_curated = session.execute(
                select(ReplyExample).where(ReplyExample.source == "curated")
            ).scalars().all()
            plan = plan_curated_sync(
                dataset_examples,
                [
                    ExistingCuratedExampleState(
                        id=row.id,
                        example_key=row.example_key,
                        content_hash=row.content_hash,
                    )
                    for row in existing_curated
                ],
            )
            curated_by_id = {row.id: row for row in existing_curated}

            inserted = self._insert_new_curated_examples(session, plan.new_examples)
            updated = self._update_changed_curated_examples(session, curated_by_id, plan.changed_examples)
            deleted = self._delete_stale_curated_examples(session, plan.stale_ids)

            sync_state = state or DatasetSyncState(dataset_name=DATASET_NAME)
            sync_state.file_hash = dataset_file_hash
            sync_state.example_count = len(dataset_examples)
            sync_state.last_synced_at = datetime.utcnow()
            session.add(sync_state)
            session.commit()

        return CuratedSyncResult(
            skipped=False,
            inserted=inserted,
            updated=updated,
            deleted=deleted,
            unchanged=plan.unchanged_count,
            accepted_backfilled=accepted_backfilled,
            example_count=len(dataset_examples),
            file_hash=dataset_file_hash,
        )

    def _backfill_legacy_accepted_examples(self, session: Session) -> int:
        legacy_examples = session.execute(
            select(ReplyExample).where(
                ReplyExample.source == "accepted",
                ReplyExample.content_hash.is_(None),
            )
        ).scalars().all()
        if not legacy_examples:
            return 0

        embeddings = self._embed_texts([embedding_input_text(example.incoming_text) for example in legacy_examples])
        for example, embedding in zip(legacy_examples, embeddings):
            example.embedding = embedding
            example.content_hash = build_reply_example_content_hash(
                role=example.role,
                scenario=example.scenario,
                incoming_text=example.incoming_text,
                reply_text=example.reply_text,
            )
        return len(legacy_examples)

    def _insert_new_curated_examples(self, session: Session, examples: list[CuratedExample]) -> int:
        if not examples:
            return 0
        for batch in _chunked(examples, EMBED_BATCH_SIZE):
            embeddings = self._embed_texts([embedding_input_text(example.incoming_text) for example in batch])
            for example, embedding in zip(batch, embeddings):
                session.add(
                    ReplyExample(
                        user_id=None,
                        thread_id=None,
                        reply_session_id=None,
                        role=example.role,
                        source="curated",
                        scenario=example.scenario,
                        incoming_text=example.incoming_text,
                        reply_text=example.reply_text,
                        embedding=embedding,
                        example_key=example.example_key,
                        content_hash=example.content_hash,
                    )
                )
        return len(examples)

    def _update_changed_curated_examples(
        self,
        session: Session,
        curated_by_id: dict[str, ReplyExample],
        changed_examples: list[ChangedCuratedExample],
    ) -> int:
        if not changed_examples:
            return 0
        for batch in _chunked(changed_examples, EMBED_BATCH_SIZE):
            embeddings = self._embed_texts([embedding_input_text(change.example.incoming_text) for change in batch])
            for change, embedding in zip(batch, embeddings):
                row = curated_by_id[change.existing_id]
                row.role = change.example.role
                row.scenario = change.example.scenario
                row.incoming_text = change.example.incoming_text
                row.reply_text = change.example.reply_text
                row.embedding = embedding
                row.example_key = change.example.example_key
                row.content_hash = change.example.content_hash
                session.add(row)
        return len(changed_examples)

    def _delete_stale_curated_examples(self, session: Session, stale_ids: list[str]) -> int:
        if not stale_ids:
            return 0
        for batch in _chunked(stale_ids, EMBED_BATCH_SIZE):
            session.execute(delete(ReplyExample).where(ReplyExample.id.in_(batch)))
        return len(stale_ids)

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings: list[list[float]] = []
        for batch in _chunked(texts, EMBED_BATCH_SIZE):
            embeddings.extend(self._embedding_model.embed_documents(batch))
        return embeddings
