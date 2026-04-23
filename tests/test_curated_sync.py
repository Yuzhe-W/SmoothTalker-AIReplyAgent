from __future__ import annotations

import json

import pytest

from api.curated_examples import (
    CuratedExample,
    build_reply_example_content_hash,
    embedding_input_text,
    load_curated_examples,
)
from api.curated_sync import ExistingCuratedExampleState, plan_curated_sync, should_skip_curated_sync
from api.safe_embeddings import SafeEmbeddingClient, combine_chunk_embeddings, split_text_for_embedding


def test_load_curated_examples_from_jsonl(tmp_path):
    dataset_path = tmp_path / "curated.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "example_key": "crush-greeting-001",
                "role": "crush",
                "scenario": "greeting",
                "incoming_text": "hey",
                "reply_text": "hey there",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    examples = load_curated_examples(dataset_path)

    assert len(examples) == 1
    assert examples[0].example_key == "crush-greeting-001"
    assert examples[0].content_hash == build_reply_example_content_hash(
        role="crush",
        scenario="greeting",
        incoming_text="hey",
        reply_text="hey there",
    )


def test_load_curated_examples_rejects_duplicate_keys(tmp_path):
    dataset_path = tmp_path / "curated.jsonl"
    record = {
        "example_key": "duplicate-key",
        "role": "crush",
        "scenario": "greeting",
        "incoming_text": "hey",
        "reply_text": "hey there",
    }
    dataset_path.write_text(
        json.dumps(record) + "\n" + json.dumps(record) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate example_key"):
        load_curated_examples(dataset_path)


def test_plan_curated_sync_classifies_new_changed_and_stale_rows():
    unchanged_hash = build_reply_example_content_hash(
        role="crush",
        scenario="greeting",
        incoming_text="hey",
        reply_text="hey there",
    )
    changed_hash = build_reply_example_content_hash(
        role="colleague",
        scenario="follow_up",
        incoming_text="thanks again",
        reply_text="Glad to connect.",
    )

    dataset_examples = [
        CuratedExample(
            example_key="crush-greeting-001",
            role="crush",
            scenario="greeting",
            incoming_text="hey",
            reply_text="hey there",
            content_hash=unchanged_hash,
        ),
        CuratedExample(
            example_key="colleague-follow-up-001",
            role="colleague",
            scenario="follow_up",
            incoming_text="thanks again",
            reply_text="Glad to connect.",
            content_hash=changed_hash,
        ),
        CuratedExample(
            example_key="crush-playful-001",
            role="crush",
            scenario="playful",
            incoming_text="you seem fun",
            reply_text="you havent seen anything yet.",
            content_hash=build_reply_example_content_hash(
                role="crush",
                scenario="playful",
                incoming_text="you seem fun",
                reply_text="you havent seen anything yet.",
            ),
        ),
    ]
    existing_rows = [
        ExistingCuratedExampleState(
            id="row-unchanged",
            example_key="crush-greeting-001",
            content_hash=unchanged_hash,
        ),
        ExistingCuratedExampleState(
            id="row-changed",
            example_key="colleague-follow-up-001",
            content_hash="old-hash",
        ),
        ExistingCuratedExampleState(
            id="row-stale",
            example_key="retired-example",
            content_hash="stale-hash",
        ),
        ExistingCuratedExampleState(
            id="row-missing-key",
            example_key=None,
            content_hash=None,
        ),
    ]

    plan = plan_curated_sync(dataset_examples, existing_rows)

    assert [example.example_key for example in plan.new_examples] == ["crush-playful-001"]
    assert [(change.existing_id, change.example.example_key) for change in plan.changed_examples] == [
        ("row-changed", "colleague-follow-up-001")
    ]
    assert set(plan.stale_ids) == {"row-stale", "row-missing-key"}
    assert plan.unchanged_count == 1


def test_should_skip_curated_sync_requires_matching_hash_and_clean_rows():
    assert should_skip_curated_sync(
        state_file_hash="abc",
        state_example_count=8,
        dataset_file_hash="abc",
        dataset_example_count=8,
        curated_row_count=8,
        invalid_curated_count=0,
    )
    assert not should_skip_curated_sync(
        state_file_hash="abc",
        state_example_count=8,
        dataset_file_hash="abc",
        dataset_example_count=8,
        curated_row_count=7,
        invalid_curated_count=0,
    )
    assert not should_skip_curated_sync(
        state_file_hash="abc",
        state_example_count=8,
        dataset_file_hash="xyz",
        dataset_example_count=8,
        curated_row_count=8,
        invalid_curated_count=0,
    )


def test_embedding_input_text_uses_incoming_text():
    assert embedding_input_text("  hello there  ", "unused reply") == "hello there"


def test_split_text_for_embedding_chunks_long_text():
    long_text = ("alpha beta gamma delta. " * 300).strip()
    chunks = split_text_for_embedding(long_text, max_tokens=40)

    assert len(chunks) > 1
    assert all(chunk.text for chunk in chunks)
    assert all(chunk.weight <= 40 for chunk in chunks)


def test_combine_chunk_embeddings_normalizes_weighted_average():
    combined = combine_chunk_embeddings([[1.0, 0.0], [0.0, 2.0]], [1, 3])

    assert combined[1] > combined[0]
    magnitude = sum(value * value for value in combined) ** 0.5
    assert magnitude == pytest.approx(1.0)


def test_safe_embedding_client_chunks_and_recombines():
    class FakeEmbeddings:
        def __init__(self):
            self.calls = []

        def embed_documents(self, texts):
            self.calls.append(list(texts))
            return [[float(len(text)), 1.0] for text in texts]

    fake = FakeEmbeddings()
    client = SafeEmbeddingClient(fake, max_tokens=20)
    text = ("hello world. " * 80).strip()

    [vector] = client.embed_documents([text])

    assert len(fake.calls) == 1
    assert len(fake.calls[0]) > 1
    assert len(vector) == 2
