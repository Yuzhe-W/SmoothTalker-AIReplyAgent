import json
import os
import time
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

load_dotenv()

PROVIDER = "qwen"
MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))

IN_RATE = float(os.getenv("INPUT_RATE_PER_1K", "0"))
OUT_RATE = float(os.getenv("OUTPUT_RATE_PER_1K", "0"))


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    if IN_RATE <= 0 and OUT_RATE <= 0:
        return 0.0
    return (tokens_in / 1000.0) * IN_RATE + (tokens_out / 1000.0) * OUT_RATE


class SingleLLMClient:
    """
    Legacy OpenAI-compatible client for Qwen chat completions.
    """

    def __init__(self):
        if not QWEN_API_KEY:
            raise RuntimeError("QWEN_API_KEY or DASHSCOPE_API_KEY is not set")
        self._client = httpx.Client(timeout=30)

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        print(f"DEBUG: Request URL: {url}")
        print(f"DEBUG: Request Payload: {json.dumps(payload, indent=2)}")

        r = self._client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResult:
        started = time.perf_counter()

        url = f"{QWEN_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {QWEN_API_KEY}",
        }
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_prompt.strip()},
            ],
            "temperature": 0.6,
            "max_tokens": 3000,
        }

        data = self._post(url, payload, headers)
        print(f"DEBUG: Raw API Response Text:\n'{data}'")

        text = ""
        try:
            text = data["choices"][0]["message"]["content"]
        except Exception:
            text = "schema DIFF"

        usage = data.get("usage", {}) or {}
        latency_ms = int((time.perf_counter() - started) * 1000)
        tokens_in = int(usage.get("prompt_tokens", 0) or max(1, len(system_prompt.split()) + len(user_prompt.split())))
        tokens_out = int(usage.get("completion_tokens", 0) or max(1, len(text.split())))

        return LLMResult(text=text, tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms)
