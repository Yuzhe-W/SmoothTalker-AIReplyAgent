import pytest
from pydantic import ValidationError

from api.guardrails import (
    enforce_colleague_style,
    enforce_crush_style,
    parse_numbered_output,
    redact_privacy,
)
from api.models import DeleteThreadRequest, GenerateRequest, SelectRequest, ThreadItem, ThreadsRequest
from api.prompts import build_examples_block, build_user_prompt
from api.retrieval_query import parse_retrieval_rewrite_json, rewrite_retrieval_query


def test_parser_happy_path():
    raw = """
OUTPUT:
1) option one
2) option two
3) option three
""".strip()
    opts = parse_numbered_output(raw)
    assert len(opts) == 3
    assert opts[0] == "option one"
    assert opts[2] == "option three"


def test_redaction_phone_and_email():
    text = "Call me at +1 415-555-1212 or a.b@test.com"
    red = redact_privacy(text)
    assert "[redacted]" in red
    assert "415" not in red
    assert "test.com" not in red


def test_crush_style_lowercase_two_lines():
    lines = ["Hey There \U0001F60A", "Let's grab coffee \u2014 maybe?"]
    out = enforce_crush_style(lines)
    assert len(out) == 2
    assert out[0] == out[0].lower()
    assert "\u2014" not in "".join(out)


def test_colleague_style_removes_slang_and_trims():
    text = "btw can u send by eod?  thanks  "
    out = enforce_colleague_style(text)
    assert "btw" not in out.lower()
    assert " u " not in f" {out} "
    assert out.strip() == out


def test_prompt_shape_fields_present():
    payload = {
        "ROLE": "CRUSH",
        "INTENT": "reply",
        "STANCE": "neutral",
        "MUST_INCLUDE": "none",
        "MUST_AVOID": "none",
        "THREAD_SUMMARY": "none",
        "EXAMPLE_REPLIES": "none",
        "AVAILABILITY": "none",
        "INCOMING": "hello",
    }
    user = build_user_prompt(payload)
    for key in [
        "ROLE:",
        "INTENT:",
        "STANCE:",
        "MUST_INCLUDE:",
        "MUST_AVOID:",
        "THREAD_SUMMARY:",
        "EXAMPLE_REPLIES:",
        "AVAILABILITY:",
        "INCOMING:",
    ]:
        assert key in user


def test_examples_block_formats_examples():
    block = build_examples_block(
        [
            {
                "source": "curated",
                "scenario": "greeting",
                "incoming_text": "hey",
                "reply_text": "hey there",
            }
        ]
    )
    assert "SOURCE=curated" in block
    assert "SCENARIO=greeting" in block
    assert "REPLY=hey there" in block


def test_rewrite_retrieval_query_includes_message_summary_and_structured_fields():
    query = rewrite_retrieval_query(
        incoming_text="Can we move our coffee to Friday after work?",
        thread_summary="Playful dating chat. Planning first coffee meetup this week.",
        role="crush",
    )

    lines = query.splitlines()
    assert lines[0] == "RAW_MESSAGE: Can we move our coffee to Friday after work?"
    assert lines[1] == "THREAD_CONTEXT: Playful dating chat. Planning first coffee meetup this week."
    assert lines[2] == "INTENT: reply to latest message"
    assert lines[3] == "SCENARIO: dating chat reply"
    assert lines[4] == "TONE: playful"
    assert lines[5].startswith("ENTITIES: ")
    assert "coffee" in lines[5]
    assert lines[6].startswith("RETRIEVAL_QUERY: ")


def test_rewrite_retrieval_query_omits_empty_thread_summary():
    query = rewrite_retrieval_query(incoming_text="Thanks for the update.", role="colleague")

    assert query.startswith("RAW_MESSAGE: Thanks for the update.")
    assert "THREAD_CONTEXT:" not in query
    assert "SCENARIO: professional reply" in query


def test_parse_retrieval_rewrite_json_uses_structured_output_when_valid():
    rewrite = parse_retrieval_rewrite_json(
        """
        {
          "normalized_message": "move coffee to friday after work",
          "intent": "reschedule meetup",
          "scenario": "dating meetup scheduling",
          "tone": "playful",
          "entities": ["coffee", "friday", "after work"],
          "retrieval_query": "reschedule coffee meetup friday after work"
        }
        """,
        incoming_text="Can we move our coffee to Friday after work?",
        thread_summary="Planning first coffee meetup.",
        role="crush",
    )

    assert rewrite.intent == "reschedule meetup"
    assert rewrite.scenario == "dating meetup scheduling"
    assert rewrite.entities == ["coffee", "friday", "after work"]
    assert rewrite.retrieval_query == "reschedule coffee meetup friday after work"


def test_generate_request_requires_thread_id():
    with pytest.raises(ValidationError):
        GenerateRequest(incoming_text="hello", role="crush")


def test_select_request_option_bounds():
    with pytest.raises(ValidationError):
        SelectRequest(session_id="abc", thread_id="thread-1", option_index=3)


def test_threads_request_limit_bounds():
    with pytest.raises(ValidationError):
        ThreadsRequest(role="crush", limit=0)


def test_delete_thread_request_requires_thread_id():
    with pytest.raises(ValidationError):
        DeleteThreadRequest(thread_id="", role="colleague")


def test_thread_item_requires_iso_timestamp_string():
    item = ThreadItem(
        thread_id="colleague-main",
        role="colleague",
        summary="Follow-up on pricing.",
        updated_at="2026-04-23T14:30:00",
    )

    assert item.thread_id == "colleague-main"
    assert item.updated_at == "2026-04-23T14:30:00"
