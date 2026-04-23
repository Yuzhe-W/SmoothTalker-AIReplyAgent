"""LangChain-backed generation, retrieval, and thread memory services."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from .curated_examples import (
    build_reply_example_content_hash,
    embedding_input_text,
)
from .retrieval_query import parse_retrieval_rewrite_json, rewrite_retrieval_query
from .safe_embeddings import SafeEmbeddingClient
from .db_models import ConversationThread, ReplyExample, ReplySession, find_user_by_external_id, get_or_create_thread
from .prompts import build_examples_block, build_user_prompt, get_system_prompt
from .settings import (
    ENABLE_LLM_QUERY_REWRITE,
    MODEL,
    PROVIDER,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_EMBEDDING_DIMENSION,
    QWEN_EMBEDDING_MODEL,
    RAG_TOP_K,
    THREAD_SUMMARY_MAX_CHARS,
    estimate_cost,
)


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content or "")


def _truncate_text(value: str, limit: int) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 0)].rstrip() + "..."


@dataclass
class GenerationResult:
    text: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    retrieved_examples_count: int
    thread_summary_used: bool


class ReplyExampleRetriever(BaseRetriever):
    session_factory: sessionmaker[Session]
    embedding_model: SafeEmbeddingClient
    role: str
    external_user_id: str
    thread_id: str
    k: int = RAG_TOP_K

    def _get_relevant_documents(self, query: str) -> list[Document]:
        query_embedding = self.embedding_model.embed_query(query)
        documents: list[Document] = []
        seen_example_ids: set[str] = set()

        with self.session_factory() as session:
            user = find_user_by_external_id(session, self.external_user_id)

            groups: list[Callable[[], Select[tuple[ReplyExample, float]]]] = []
            if user is not None:
                groups.append(
                    lambda user_id=user.id: self._example_query(
                        query_embedding,
                        filters=(
                            ReplyExample.source == "accepted",
                            ReplyExample.user_id == user_id,
                            ReplyExample.thread_id == self.thread_id,
                        ),
                    )
                )
                groups.append(
                    lambda user_id=user.id: self._example_query(
                        query_embedding,
                        filters=(
                            ReplyExample.source == "accepted",
                            ReplyExample.user_id == user_id,
                        ),
                    )
                )

            groups.append(
                lambda: self._example_query(
                    query_embedding,
                    filters=(ReplyExample.source == "curated",),
                )
            )

            for build_query in groups:
                if len(documents) >= self.k:
                    break
                rows = session.execute(build_query().limit(self.k)).all()
                for example, distance in rows:
                    if example.id in seen_example_ids:
                        continue
                    seen_example_ids.add(example.id)
                    documents.append(
                        Document(
                            page_content=example.reply_text,
                            metadata={
                                "example_id": example.id,
                                "distance": float(distance),
                                "incoming_text": example.incoming_text,
                                "role": example.role,
                                "scenario": example.scenario or "",
                                "source": example.source,
                                "thread_id": example.thread_id or "",
                            },
                        )
                    )
                    if len(documents) >= self.k:
                        break

        return documents

    def _example_query(
        self,
        query_embedding: list[float],
        *,
        filters: Iterable[Any],
    ) -> Select[tuple[ReplyExample, float]]:
        distance = ReplyExample.embedding.cosine_distance(query_embedding).label("distance")
        return (
            select(ReplyExample, distance)
            .where(ReplyExample.role == self.role, *filters)
            .order_by(distance, ReplyExample.created_at.desc())
        )


class ReplyRAGService:
    def __init__(self, session_factory: sessionmaker[Session]):
        if not QWEN_API_KEY:
            raise RuntimeError("QWEN_API_KEY or DASHSCOPE_API_KEY is required for generation")

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
        self._chat_model = ChatOpenAI(
            model_name=MODEL,
            temperature=0.6,
            openai_api_key=QWEN_API_KEY,
            openai_api_base=QWEN_BASE_URL,
            max_retries=2,
        )
        self._query_rewrite_model = ChatOpenAI(
            model_name=MODEL,
            temperature=0.0,
            openai_api_key=QWEN_API_KEY,
            openai_api_base=QWEN_BASE_URL,
            max_retries=2,
        )
        self._query_rewrite_chain = (
            ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You rewrite ambiguous incoming messages into retrieval queries for similar reply-example search. "
                        "Return only compact JSON with keys normalized_message, intent, scenario, tone, entities, "
                        "retrieval_query. Use only facts supported by INCOMING and THREAD_SUMMARY. "
                        "normalized_message should be a cleaned restatement of the latest message. "
                        "intent should be a short action or goal phrase. "
                        "scenario should be a short retrieval label. "
                        "tone should be a brief style label. "
                        "entities should be a JSON array of up to 6 short concrete terms. "
                        "retrieval_query should be a short search-oriented string optimized for semantic retrieval. "
                        "ASCII only. No Markdown. No commentary.",
                    ),
                    (
                        "human",
                        "ROLE: {role}\n"
                        "THREAD_SUMMARY: {thread_summary}\n"
                        "INCOMING: {incoming_text}\n",
                    ),
                ]
            )
            | self._query_rewrite_model
        )
        self._summary_chain = (
            ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You maintain a concise conversation memory for SmoothTalker. "
                        "Write a short summary in plain ASCII. Keep only durable context, tone, commitments, "
                        "boundaries, and open threads. Do not invent facts.",
                    ),
                    (
                        "human",
                        "ROLE: {role}\n"
                        "PREVIOUS_SUMMARY: {previous_summary}\n"
                        "LATEST_INCOMING: {incoming_text}\n"
                        "LATEST_SELECTED_REPLY: {selected_reply}\n\n"
                        "Return a compact summary under {max_chars} characters.",
                    ),
                ]
            )
            | self._chat_model
        )

    def get_thread_summary(self, db: Session, *, external_user_id: Optional[str], thread_id: str, role: str) -> str:
        user = find_user_by_external_id(db, external_user_id)
        if user is None:
            return ""
        stmt = select(ConversationThread).where(
            ConversationThread.user_id == user.id,
            ConversationThread.thread_id == thread_id,
            ConversationThread.role == role,
        )
        thread = db.execute(stmt).scalar_one_or_none()
        return (thread.summary or "").strip() if thread else ""

    def retrieve_examples(
        self,
        *,
        external_user_id: Optional[str],
        thread_id: str,
        role: str,
        incoming_text: str,
        thread_summary: str = "",
    ) -> list[dict[str, str]]:
        retriever = ReplyExampleRetriever(
            session_factory=self._session_factory,
            embedding_model=self._embedding_model,
            role=role,
            external_user_id=external_user_id or "anonymous",
            thread_id=thread_id,
            k=RAG_TOP_K,
        )
        retrieval_query = self._build_retrieval_query(
            role=role,
            incoming_text=incoming_text,
            thread_summary=thread_summary,
        )
        docs = retriever.invoke(retrieval_query)
        examples: list[dict[str, str]] = []
        for doc in docs:
            examples.append(
                {
                    "source": str(doc.metadata.get("source", "")),
                    "scenario": str(doc.metadata.get("scenario", "")),
                    "incoming_text": str(doc.metadata.get("incoming_text", "")),
                    "reply_text": doc.page_content,
                }
            )
        return examples

    def _build_retrieval_query(self, *, role: str, incoming_text: str, thread_summary: str) -> str:
        if not ENABLE_LLM_QUERY_REWRITE:
            return rewrite_retrieval_query(
                incoming_text=incoming_text,
                thread_summary=thread_summary,
                role=role,
            )

        try:
            ai_message = self._query_rewrite_chain.invoke(
                {
                    "role": role,
                    "thread_summary": thread_summary or "none",
                    "incoming_text": incoming_text,
                }
            )
            rewrite = parse_retrieval_rewrite_json(
                _message_text(ai_message.content),
                incoming_text=incoming_text,
                thread_summary=thread_summary,
                role=role,
            )
            return rewrite_retrieval_query(
                incoming_text=incoming_text,
                thread_summary=thread_summary,
                role=role,
                rewrite=rewrite,
            )
        except Exception:
            return rewrite_retrieval_query(
                incoming_text=incoming_text,
                thread_summary=thread_summary,
                role=role,
            )

    def generate(
        self,
        *,
        role: str,
        incoming_text: str,
        thread_summary: str,
        examples: list[dict[str, str]],
    ) -> GenerationResult:
        payload = {
            "ROLE": role,
            "INTENT": "reply",
            "STANCE": "none",
            "MUST_INCLUDE": "none",
            "MUST_AVOID": "none",
            "THREAD_SUMMARY": thread_summary or "none",
            "EXAMPLE_REPLIES": build_examples_block(examples),
            "AVAILABILITY": "none",
            "INCOMING": incoming_text,
        }
        prompt = build_user_prompt(payload)
        started = time.perf_counter()
        messages = ChatPromptTemplate.from_messages(
            [
                ("system", get_system_prompt(role)),
                ("human", "{prompt}"),
            ]
        ).invoke({"prompt": prompt})
        ai_message = self._chat_model.invoke(messages)
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(ai_message, "usage_metadata", {}) or {}
        tokens_in = int(usage.get("input_tokens", 0) or 0)
        tokens_out = int(usage.get("output_tokens", 0) or 0)
        return GenerationResult(
            text=_message_text(ai_message.content),
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            retrieved_examples_count=len(examples),
            thread_summary_used=bool((thread_summary or "").strip()),
        )

    def select_reply(
        self,
        db: Session,
        *,
        reply_session: ReplySession,
        external_user_id: Optional[str],
        thread_id: str,
        option_index: int,
    ) -> None:
        selected_reply = reply_session.options[option_index]
        embedding = self._embedding_model.embed_query(embedding_input_text(reply_session.incoming_text))
        thread = get_or_create_thread(
            db,
            external_user_id=external_user_id,
            thread_id=thread_id,
            role=reply_session.role,
        )
        db.add(
            ReplyExample(
                user_id=thread.user_id,
                thread_id=thread_id,
                reply_session_id=reply_session.id,
                role=reply_session.role,
                source="accepted",
                scenario=None,
                incoming_text=reply_session.incoming_text,
                reply_text=selected_reply,
                embedding=embedding,
                content_hash=build_reply_example_content_hash(
                    role=reply_session.role,
                    scenario=None,
                    incoming_text=reply_session.incoming_text,
                    reply_text=selected_reply,
                ),
            )
        )
        thread.summary = self._summarize_thread(
            role=reply_session.role,
            previous_summary=thread.summary,
            incoming_text=reply_session.incoming_text,
            selected_reply=selected_reply,
        )
        db.commit()

    def _summarize_thread(
        self,
        *,
        role: str,
        previous_summary: str,
        incoming_text: str,
        selected_reply: str,
    ) -> str:
        try:
            ai_message = self._summary_chain.invoke(
                {
                    "role": role,
                    "previous_summary": previous_summary or "none",
                    "incoming_text": incoming_text,
                    "selected_reply": selected_reply,
                    "max_chars": THREAD_SUMMARY_MAX_CHARS,
                }
            )
            return _truncate_text(_message_text(ai_message.content), THREAD_SUMMARY_MAX_CHARS)
        except Exception:
            fallback = (
                f"{previous_summary.strip()} Latest incoming: {incoming_text.strip()} "
                f"Latest selected reply: {selected_reply.strip()}"
            ).strip()
            return _truncate_text(fallback, THREAD_SUMMARY_MAX_CHARS)

    def build_meta(self, result: GenerationResult) -> dict[str, Any]:
        return {
            "provider": PROVIDER,
            "model": MODEL,
            "latency_ms": result.latency_ms,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "estimated_cost_usd": round(estimate_cost(result.tokens_in, result.tokens_out), 6),
            "retrieval_used": result.retrieved_examples_count > 0,
            "retrieved_examples_count": result.retrieved_examples_count,
            "thread_summary_used": result.thread_summary_used,
        }
