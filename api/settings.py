"""Application settings and provider metadata."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

PROVIDER = "qwen"
MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
QWEN_EMBEDDING_MODEL = os.getenv("QWEN_EMBEDDING_MODEL", "text-embedding-v4")
QWEN_EMBEDDING_DIMENSION = int(os.getenv("QWEN_EMBEDDING_DIMENSION", "1536"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "4"))
THREAD_SUMMARY_MAX_CHARS = int(os.getenv("THREAD_SUMMARY_MAX_CHARS", "800"))
ENABLE_LLM_QUERY_REWRITE = _env_flag("ENABLE_LLM_QUERY_REWRITE", "1")

IN_RATE = float(os.getenv("INPUT_RATE_PER_1K", "0"))
OUT_RATE = float(os.getenv("OUTPUT_RATE_PER_1K", "0"))


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    if IN_RATE <= 0 and OUT_RATE <= 0:
        return 0.0
    return (tokens_in / 1000.0) * IN_RATE + (tokens_out / 1000.0) * OUT_RATE
