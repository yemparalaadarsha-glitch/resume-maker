import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.cover_letter import generate_cover_letter

RESUME_CONTENT = {
    "contact": {"name": "Jordan Rivera", "email": "jordan.rivera@example.com",
                "phone": "555-123-4567", "location": "Austin, TX", "links": []},
    "summary": "Backend engineer with 5 years building distributed systems.",
    "skills": ["Python", "Go"],
    "experience": [{"company": "Northwind Data", "title": "Senior Backend Engineer",
                    "location": "Austin, TX", "start": "2022-01", "end": "Present",
                    "bullets": ["Rebuilt the ingestion pipeline in Go."]}],
    "projects": [{"name": "queue-bench", "bullets": ["Built a benchmarking tool."], "tech": ["Go"]}],
    "education": [{"school": "UT Austin", "degree": "B.S. Computer Science", "start": "2014", "end": "2018"}],
}


def _fake_response(data: dict, input_tokens=800, output_tokens=300):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(data))],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_generate_cover_letter_runs_two_calls_and_returns_final_content():
    client = MagicMock()
    draft = {"paragraphs": ["draft paragraph one.", "draft paragraph two."]}
    final = {"paragraphs": ["final paragraph one.", "final paragraph two."]}
    client.messages.create.side_effect = [_fake_response(draft), _fake_response(final)]

    result, usages = generate_cover_letter(client, RESUME_CONTENT, "job description text", "Northwind Data")

    assert result == final
    assert len(usages) == 2
    assert client.messages.create.call_count == 2


def test_generate_cover_letter_uses_requested_model_for_both_calls():
    client = MagicMock()
    empty = {"paragraphs": []}
    client.messages.create.side_effect = [_fake_response(empty), _fake_response(empty)]

    generate_cover_letter(client, RESUME_CONTENT, "job description text", "Northwind Data", model="claude-opus-4-8")

    for call in client.messages.create.call_args_list:
        assert call.kwargs["model"] == "claude-opus-4-8"


def test_generate_cover_letter_system_prompts_include_banned_phrases():
    client = MagicMock()
    empty = {"paragraphs": []}
    client.messages.create.side_effect = [_fake_response(empty), _fake_response(empty)]

    generate_cover_letter(client, RESUME_CONTENT, "job description text", "Northwind Data")

    draft_call, critique_call = client.messages.create.call_args_list
    assert "spearheaded" in draft_call.kwargs["system"]
    assert "spearheaded" in critique_call.kwargs["system"]


def test_generate_cover_letter_marks_resume_block_as_cacheable():
    client = MagicMock()
    empty = {"paragraphs": []}
    client.messages.create.side_effect = [_fake_response(empty), _fake_response(empty)]

    generate_cover_letter(client, RESUME_CONTENT, "job description text", "Northwind Data")

    draft_call, critique_call = client.messages.create.call_args_list
    for call in (draft_call, critique_call):
        content_blocks = call.kwargs["messages"][0]["content"]
        assert len(content_blocks) == 2
        assert content_blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "Northwind Data" in content_blocks[0]["text"]
        assert "cache_control" not in content_blocks[1]
