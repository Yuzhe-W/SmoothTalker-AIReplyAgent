"""Structured retrieval-query rewriting with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


WHITESPACE_RE = re.compile(r"\s+")
TERM_RE = re.compile(r"[A-Za-z0-9_']+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "got",
    "had",
    "has",
    "have",
    "hey",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "just",
    "let",
    "like",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "their",
    "them",
    "there",
    "they",
    "this",
    "to",
    "up",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "would",
    "you",
    "your",
    "redacted",
    "none",
}


@dataclass(frozen=True)
class RetrievalQueryRewrite:
    normalized_message: str
    intent: str
    scenario: str
    tone: str
    entities: list[str]
    retrieval_query: str


def _normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", (value or "").strip())


def _normalize_ascii_text(value: str, fallback: str) -> str:
    text = _normalize_text(value)
    return text or fallback


def _extract_focus_terms(*values: str, limit: int = 8) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    for value in values:
        for raw in TERM_RE.findall((value or "").lower()):
            term = raw.strip("'")
            if len(term) < 3 or term in STOPWORDS or term.isdigit():
                continue
            if term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= limit:
                return terms

    return terms


def _role_defaults(role: str) -> tuple[str, str]:
    role_key = (role or "").strip().lower()
    if role_key == "crush":
        return "dating chat reply", "playful"
    if role_key == "colleague":
        return "professional reply", "professional"
    return "general reply", "natural"


def _normalize_entities(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback

    entities: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _normalize_text(str(item or "")).lower()
        if len(text) < 2 or text in seen:
            continue
        seen.add(text)
        entities.append(text)
        if len(entities) >= 6:
            break
    return entities or fallback


def fallback_retrieval_rewrite(
    *,
    incoming_text: str,
    thread_summary: str = "",
    role: str = "",
) -> RetrievalQueryRewrite:
    message = _normalize_text(incoming_text)
    if not message:
        raise ValueError("incoming_text is required for retrieval query rewriting")

    summary = _normalize_text(thread_summary)
    scenario_default, tone_default = _role_defaults(role)
    entities = _extract_focus_terms(message, summary, limit=6)
    retrieval_query = " ".join(part for part in [message, " ".join(entities[:4])] if part).strip()

    return RetrievalQueryRewrite(
        normalized_message=message,
        intent="reply to latest message",
        scenario=scenario_default,
        tone=tone_default,
        entities=entities,
        retrieval_query=retrieval_query or message,
    )


def parse_retrieval_rewrite_json(
    raw: str,
    *,
    incoming_text: str,
    thread_summary: str = "",
    role: str = "",
) -> RetrievalQueryRewrite:
    fallback = fallback_retrieval_rewrite(
        incoming_text=incoming_text,
        thread_summary=thread_summary,
        role=role,
    )
    try:
        payload = json.loads((raw or "").strip())
    except json.JSONDecodeError:
        return fallback

    if not isinstance(payload, dict):
        return fallback

    normalized_message = _normalize_ascii_text(payload.get("normalized_message", ""), fallback.normalized_message)
    intent = _normalize_ascii_text(payload.get("intent", ""), fallback.intent)
    scenario = _normalize_ascii_text(payload.get("scenario", ""), fallback.scenario)
    tone = _normalize_ascii_text(payload.get("tone", ""), fallback.tone)
    entities = _normalize_entities(payload.get("entities"), fallback.entities)
    retrieval_query = _normalize_ascii_text(payload.get("retrieval_query", ""), "")
    if not retrieval_query:
        retrieval_query = " ".join(part for part in [normalized_message, scenario, " ".join(entities[:4])] if part).strip()

    return RetrievalQueryRewrite(
        normalized_message=normalized_message,
        intent=intent,
        scenario=scenario,
        tone=tone,
        entities=entities,
        retrieval_query=retrieval_query or fallback.retrieval_query,
    )


def format_retrieval_query(
    rewrite: RetrievalQueryRewrite,
    *,
    thread_summary: str = "",
) -> str:
    summary = _normalize_text(thread_summary)
    parts = [f"RAW_MESSAGE: {rewrite.normalized_message}"]
    if summary:
        parts.append(f"THREAD_CONTEXT: {summary}")
    parts.append(f"INTENT: {rewrite.intent}")
    parts.append(f"SCENARIO: {rewrite.scenario}")
    parts.append(f"TONE: {rewrite.tone}")
    if rewrite.entities:
        parts.append(f"ENTITIES: {', '.join(rewrite.entities)}")
    parts.append(f"RETRIEVAL_QUERY: {rewrite.retrieval_query}")
    return "\n".join(parts)


def rewrite_retrieval_query(
    *,
    incoming_text: str,
    thread_summary: str = "",
    role: str = "",
    rewrite: RetrievalQueryRewrite | None = None,
) -> str:
    structured = rewrite or fallback_retrieval_rewrite(
        incoming_text=incoming_text,
        thread_summary=thread_summary,
        role=role,
    )
    return format_retrieval_query(structured, thread_summary=thread_summary)
