"""Provider-safe local preprocessing for embedding inputs."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable, Protocol

from langchain_openai import OpenAIEmbeddings


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
WORD_SPLIT_RE = re.compile(r"\S+\s*")
LEXICAL_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")
DEFAULT_EMBEDDING_CTX_TOKENS = 8191


@dataclass(frozen=True)
class TextChunk:
    text: str
    weight: int


class EmbeddingsLike(Protocol):
    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


def approximate_token_count(text: str) -> int:
    value = (text or "").strip()
    if not value:
        return 0
    lexical_count = len(LEXICAL_TOKEN_RE.findall(value))
    char_based = math.ceil(len(value) / 4)
    return max(1, lexical_count, char_based)


def split_text_for_embedding(text: str, *, max_tokens: int = DEFAULT_EMBEDDING_CTX_TOKENS) -> list[TextChunk]:
    value = (text or "").strip()
    if not value:
        raise ValueError("Embedding text cannot be empty")

    total_tokens = approximate_token_count(value)
    if total_tokens <= max_tokens:
        return [TextChunk(text=value, weight=total_tokens)]

    units = [unit.strip() for unit in SENTENCE_SPLIT_RE.split(value) if unit.strip()]
    if not units:
        units = [value]

    chunks: list[TextChunk] = []
    current_parts: list[str] = []
    current_tokens = 0

    def flush_current() -> None:
        nonlocal current_parts, current_tokens
        if not current_parts:
            return
        chunk_text = " ".join(part.strip() for part in current_parts if part.strip()).strip()
        if chunk_text:
            chunk_tokens = approximate_token_count(chunk_text)
            chunks.append(TextChunk(text=chunk_text, weight=chunk_tokens))
        current_parts = []
        current_tokens = 0

    for unit in units:
        unit_tokens = approximate_token_count(unit)
        if unit_tokens > max_tokens:
            flush_current()
            chunks.extend(_split_large_unit(unit, max_tokens=max_tokens))
            continue

        if current_parts and current_tokens + unit_tokens > max_tokens:
            flush_current()

        current_parts.append(unit)
        current_tokens += unit_tokens

    flush_current()

    if not chunks:
        chunks.append(TextChunk(text=value, weight=total_tokens))

    return chunks


def _split_large_unit(text: str, *, max_tokens: int) -> list[TextChunk]:
    parts = WORD_SPLIT_RE.findall(text)
    if not parts:
        stripped = text.strip()
        return [TextChunk(text=stripped, weight=approximate_token_count(stripped))]

    chunks: list[TextChunk] = []
    current_parts: list[str] = []
    current_tokens = 0

    for part in parts:
        stripped_part = part.strip()
        if not stripped_part:
            continue
        part_tokens = approximate_token_count(stripped_part)
        if current_parts and current_tokens + part_tokens > max_tokens:
            chunk_text = "".join(current_parts).strip()
            if chunk_text:
                chunks.append(TextChunk(text=chunk_text, weight=approximate_token_count(chunk_text)))
            current_parts = []
            current_tokens = 0
        current_parts.append(part)
        current_tokens += part_tokens

    chunk_text = "".join(current_parts).strip()
    if chunk_text:
        chunks.append(TextChunk(text=chunk_text, weight=approximate_token_count(chunk_text)))

    return chunks


def combine_chunk_embeddings(embeddings: list[list[float]], weights: Iterable[int]) -> list[float]:
    if not embeddings:
        raise ValueError("No embeddings to combine")

    normalized_weights = [max(1, int(weight)) for weight in weights]
    if len(embeddings) != len(normalized_weights):
        raise ValueError("Embedding and weight counts must match")

    if len(embeddings) == 1:
        return embeddings[0]

    total_weight = sum(normalized_weights)
    averaged = [
        sum(vector[index] * normalized_weights[vector_index] for vector_index, vector in enumerate(embeddings))
        / total_weight
        for index in range(len(embeddings[0]))
    ]
    magnitude = sum(value * value for value in averaged) ** 0.5
    if magnitude == 0:
        return averaged
    return [value / magnitude for value in averaged]


class SafeEmbeddingClient:
    """Add provider-safe local chunking before calling remote embeddings."""

    def __init__(
        self,
        base: OpenAIEmbeddings,
        *,
        max_tokens: int = DEFAULT_EMBEDDING_CTX_TOKENS,
    ) -> None:
        self._base = base
        self._max_tokens = max_tokens

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        per_text_chunks = [split_text_for_embedding(text, max_tokens=self._max_tokens) for text in texts]
        flat_chunks = [chunk.text for chunks in per_text_chunks for chunk in chunks]
        flat_embeddings = self._base.embed_documents(flat_chunks)

        combined: list[list[float]] = []
        offset = 0
        for chunks in per_text_chunks:
            chunk_embeddings = flat_embeddings[offset : offset + len(chunks)]
            combined.append(combine_chunk_embeddings(chunk_embeddings, [chunk.weight for chunk in chunks]))
            offset += len(chunks)
        return combined
