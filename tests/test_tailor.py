import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.tailor import TailorResponseError, tailor_resume

MASTER_RESUME = {
    "summary": "Backend engineer with 5 years building distributed systems.",
    "skills": ["Python", "Go"],
    "experience": [{"company": "Northwind Data", "title": "Senior Backend Engineer",
                     "location": "Austin, TX", "start": "2022-01", "end": "Present",
                     "bullets": ["Rebuilt the ingestion pipeline in Go."]}],
    "projects": [{"name": "queue-bench", "bullets": ["Built a benchmarking tool."], "tech": ["Go"]}],
}
GAP_ANALYSIS = {"keywords": ["Kubernetes"], "matched": [], "missing": ["Kubernetes"], "match_percentage": 0}


def _fake_response(data: dict, input_tokens=1000, output_tokens=500, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(data))],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
    )


def _fake_truncated_response(partial_text: str, stop_reason: str):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=partial_text)],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=8192),
        stop_reason=stop_reason,
    )


def test_tailor_resume_runs_two_calls_and_returns_final_content():
    client = MagicMock()
    draft = {"summary": "draft summary", "experience": [], "projects": []}
    final = {"summary": "final summary, no banned phrases", "experience": [], "projects": []}
    client.messages.create.side_effect = [_fake_response(draft), _fake_response(final)]

    result, usages = tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS)

    assert result == final
    assert len(usages) == 2
    assert client.messages.create.call_count == 2


def test_tailor_resume_uses_requested_model_for_both_calls():
    client = MagicMock()
    empty = {"summary": "", "experience": [], "projects": []}
    client.messages.create.side_effect = [_fake_response(empty), _fake_response(empty)]

    tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS, model="claude-opus-4-8")

    for call in client.messages.create.call_args_list:
        assert call.kwargs["model"] == "claude-opus-4-8"


def test_tailor_resume_system_prompts_include_banned_phrases():
    client = MagicMock()
    empty = {"summary": "", "experience": [], "projects": []}
    client.messages.create.side_effect = [_fake_response(empty), _fake_response(empty)]

    tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS)

    tailor_call, critique_call = client.messages.create.call_args_list
    assert "spearheaded" in tailor_call.kwargs["system"]
    assert "spearheaded" in critique_call.kwargs["system"]


def test_tailor_resume_marks_master_resume_block_as_cacheable():
    client = MagicMock()
    empty = {"summary": "", "experience": [], "projects": []}
    client.messages.create.side_effect = [_fake_response(empty), _fake_response(empty)]

    tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS)

    tailor_call, critique_call = client.messages.create.call_args_list
    for call in (tailor_call, critique_call):
        content_blocks = call.kwargs["messages"][0]["content"]
        assert len(content_blocks) == 2
        assert content_blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "Northwind Data" in content_blocks[0]["text"]
        assert "cache_control" not in content_blocks[1]


def test_tailor_resume_disables_thinking_and_gives_output_headroom():
    # claude-sonnet-5 runs adaptive thinking by default when `thinking` is
    # omitted, and max_tokens is a hard cap on thinking + output combined.
    # For a full-size resume the model can burn the budget on invisible
    # thinking tokens and truncate the JSON mid-string. Thinking is disabled
    # explicitly since this call is a deterministic JSON transform, and
    # max_tokens is raised well past the plan's original 4096 so a large
    # resume (every experience/project bullet echoed back, per the system
    # prompt) has room to complete even if thinking were ever re-enabled.
    client = MagicMock()
    empty = {"summary": "", "experience": [], "projects": []}
    client.messages.create.side_effect = [_fake_response(empty), _fake_response(empty)]

    tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS)

    tailor_call, critique_call = client.messages.create.call_args_list
    for call in (tailor_call, critique_call):
        assert call.kwargs["thinking"] == {"type": "disabled"}
        assert call.kwargs["max_tokens"] >= 16000


def test_tailor_resume_raises_clear_error_when_response_truncated_at_max_tokens():
    # A prior fix disabled thinking and raised max_tokens, but truncation
    # recurred at an even shorter position — inconsistent with "still just
    # running out of budget" (more budget should truncate later, not
    # earlier). Rather than guess at a third max_tokens value blindly, make
    # the failure mode legible: check stop_reason before attempting to parse,
    # so the next occurrence (if any) reports plainly that generation was
    # cut off at the token limit instead of surfacing a bare, unexplained
    # JSONDecodeError.
    client = MagicMock()
    truncated_text = '{"summary": "Backend engineer focused on distributed sys'
    client.messages.create.side_effect = [
        _fake_truncated_response(truncated_text, stop_reason="max_tokens")
    ]

    with pytest.raises(TailorResponseError, match="max_tokens"):
        tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS)


def test_tailor_resume_raises_clear_error_for_unexpected_stop_reason():
    client = MagicMock()
    empty_text = json.dumps({"summary": "", "experience": [], "projects": []})
    client.messages.create.side_effect = [
        _fake_truncated_response(empty_text, stop_reason="refusal")
    ]

    with pytest.raises(TailorResponseError, match="refusal"):
        tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS)


def test_tailor_resume_raises_diagnostic_error_when_json_invalid_despite_end_turn():
    # Observed in production against claude-sonnet-5: stop_reason reports
    # "end_turn" (Claude believes it finished normally) yet response.content
    # is not valid JSON, so json.loads() raised a bare, contextless
    # JSONDecodeError ("Unterminated string starting at: line 1 column N")
    # that gave no way to diagnose what actually went wrong. The stop_reason
    # checks above don't catch this case by design (stop_reason IS
    # end_turn) — this is a different failure mode: the guard here is
    # around the parse itself, surfacing stop_reason, response length, and
    # the actual text near the parse failure instead of a bare traceback.
    client = MagicMock()
    malformed_text = '{"summary": "Backend engineer focused on distributed sys'
    client.messages.create.side_effect = [
        _fake_truncated_response(malformed_text, stop_reason="end_turn")
    ]

    with pytest.raises(TailorResponseError) as exc_info:
        tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS)

    message = str(exc_info.value)
    assert "end_turn" in message
    assert "distributed sys" in message  # actual response text, not just the parser error


def test_tailor_resume_concatenates_multiple_text_blocks_before_parsing():
    # Structured-output responses are normally a single text block, but
    # taking only response.content[0] would silently drop the rest of the
    # JSON if the model ever splits output across multiple text blocks.
    client = MagicMock()
    draft = {"summary": "draft", "experience": [], "projects": []}
    final = {"summary": "final split across blocks", "experience": [], "projects": []}
    final_json = json.dumps(final)
    split_at = len(final_json) // 2
    split_response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text=final_json[:split_at]),
            SimpleNamespace(type="text", text=final_json[split_at:]),
        ],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
        stop_reason="end_turn",
    )
    client.messages.create.side_effect = [_fake_response(draft), split_response]

    result, _ = tailor_resume(client, MASTER_RESUME, "job description text", GAP_ANALYSIS)

    assert result == final
