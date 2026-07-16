import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.tailor import tailor_resume

MASTER_RESUME = {
    "summary": "Backend engineer with 5 years building distributed systems.",
    "skills": ["Python", "Go"],
    "experience": [{"company": "Northwind Data", "title": "Senior Backend Engineer",
                     "location": "Austin, TX", "start": "2022-01", "end": "Present",
                     "bullets": ["Rebuilt the ingestion pipeline in Go."]}],
    "projects": [{"name": "queue-bench", "bullets": ["Built a benchmarking tool."], "tech": ["Go"]}],
}
GAP_ANALYSIS = {"keywords": ["Kubernetes"], "matched": [], "missing": ["Kubernetes"], "match_percentage": 0}


def _fake_response(data: dict, input_tokens=1000, output_tokens=500):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(data))],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
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
