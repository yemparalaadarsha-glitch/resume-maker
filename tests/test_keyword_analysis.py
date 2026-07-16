import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.keyword_analysis import extract_keywords


def _fake_response(data: dict, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(data))],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_extract_keywords_returns_parsed_data_and_usage():
    client = MagicMock()
    expected = {
        "keywords": ["Python", "AWS", "Kubernetes"],
        "matched": ["Python"],
        "missing": ["AWS", "Kubernetes"],
        "match_percentage": 33,
    }
    client.messages.create.return_value = _fake_response(expected, input_tokens=1200, output_tokens=300)

    data, usage = extract_keywords(client, "job description text", "resume text")

    assert data == expected
    assert usage.input_tokens == 1200
    assert usage.output_tokens == 300


def test_extract_keywords_calls_haiku_model_with_json_schema():
    client = MagicMock()
    client.messages.create.return_value = _fake_response(
        {"keywords": [], "matched": [], "missing": [], "match_percentage": 0}
    )

    extract_keywords(client, "job description text", "resume text")

    call_kwargs = client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5"
    assert call_kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "job description text" in call_kwargs["messages"][0]["content"]
    assert "resume text" in call_kwargs["messages"][0]["content"]
