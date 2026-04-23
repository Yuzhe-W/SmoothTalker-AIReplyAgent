"""Curated reply example dataset loading and normalization."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


DATASET_NAME = "curated_reply_examples"
DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / f"{DATASET_NAME}.jsonl"
VALID_ROLES = {"crush", "colleague"}


@dataclass(frozen=True)
class CuratedExample:
    example_key: str
    role: str
    scenario: str | None
    incoming_text: str
    reply_text: str
    content_hash: str


def _normalize_required(value: object, *, field_name: str, line_no: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Curated dataset line {line_no}: missing {field_name}")
    return text


def _normalize_optional(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def embedding_input_text(incoming_text: str, reply_text: str = "") -> str:
    text = (incoming_text or "").strip()
    if not text:
        raise ValueError("incoming_text must be present when generating embeddings")
    return text


def build_reply_example_content_hash(
    *,
    role: str,
    scenario: str | None,
    incoming_text: str,
    reply_text: str,
) -> str:
    payload = {
        "role": (role or "").strip().lower(),
        "scenario": (scenario or "").strip() or None,
        "incoming_text": (incoming_text or "").strip(),
        "reply_text": (reply_text or "").strip(),
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_dataset_file_hash(path: Path | None = None) -> str:
    dataset_path = path or DATASET_PATH
    if not dataset_path.exists():
        raise FileNotFoundError(f"Curated dataset file not found: {dataset_path}")
    return hashlib.sha256(dataset_path.read_bytes()).hexdigest()


def load_curated_examples(path: Path | None = None) -> list[CuratedExample]:
    dataset_path = path or DATASET_PATH
    if not dataset_path.exists():
        raise FileNotFoundError(f"Curated dataset file not found: {dataset_path}")

    examples: list[CuratedExample] = []
    seen_keys: set[str] = set()

    with dataset_path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Curated dataset line {line_no}: invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Curated dataset line {line_no}: expected an object")

            example_key = _normalize_required(payload.get("example_key"), field_name="example_key", line_no=line_no)
            if example_key in seen_keys:
                raise ValueError(f"Curated dataset line {line_no}: duplicate example_key '{example_key}'")
            seen_keys.add(example_key)

            role = _normalize_required(payload.get("role"), field_name="role", line_no=line_no).lower()
            if role not in VALID_ROLES:
                raise ValueError(f"Curated dataset line {line_no}: invalid role '{role}'")

            scenario = _normalize_optional(payload.get("scenario"))
            incoming_text = _normalize_required(
                payload.get("incoming_text"), field_name="incoming_text", line_no=line_no
            )
            reply_text = _normalize_required(payload.get("reply_text"), field_name="reply_text", line_no=line_no)

            examples.append(
                CuratedExample(
                    example_key=example_key,
                    role=role,
                    scenario=scenario,
                    incoming_text=incoming_text,
                    reply_text=reply_text,
                    content_hash=build_reply_example_content_hash(
                        role=role,
                        scenario=scenario,
                        incoming_text=incoming_text,
                        reply_text=reply_text,
                    ),
                )
            )

    if not examples:
        raise ValueError(f"Curated dataset file is empty: {dataset_path}")

    return examples
