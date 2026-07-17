import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.banned_phrases import lint_resume_content
from core.keyword_analysis import extract_keywords
from core.latex_render import render_resume
from core.tailor import tailor_resume

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MASTER_RESUME = json.loads((FIXTURES_DIR / "master_resume.json").read_text())
JOB_DESCRIPTION = (FIXTURES_DIR / "job_description.txt").read_text()


def _fake_response(data: dict, input_tokens=1000, output_tokens=400):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(data))],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )


def test_full_pipeline_from_jd_to_compiled_pdf(tmp_path):
    client = MagicMock()

    gap_analysis_response = {
        "keywords": ["Go", "Kubernetes", "PostgreSQL"],
        "matched": ["Go", "PostgreSQL"],
        "missing": ["Kubernetes"],
        "match_percentage": 66,
    }
    tailored_draft = {
        "summary": "Backend engineer specializing in Go, PostgreSQL, and high-throughput pipelines.",
        "experience": [
            {
                "company": "Northwind Data",
                "bullets": [
                    "Rebuilt the ingestion pipeline in Go, cutting processing latency from 40 minutes to 6 minutes.",
                    "Migrated the primary datastore from MySQL to PostgreSQL with zero downtime for 2M daily active rows.",
                ],
            }
        ],
        "projects": [
            {"name": "queue-bench", "bullets": ["Built an open-source benchmarking tool for message queue throughput."]}
        ],
    }
    tailored_final = tailored_draft  # self-critique finds nothing to change in this fixture

    client.messages.create.side_effect = [
        _fake_response(gap_analysis_response),
        _fake_response(tailored_draft),
        _fake_response(tailored_final),
    ]

    resume_text = MASTER_RESUME["summary"]
    gap_analysis, kw_usage = extract_keywords(client, JOB_DESCRIPTION, resume_text)
    assert gap_analysis == gap_analysis_response
    assert kw_usage.input_tokens > 0

    tailored_content, tailor_usages = tailor_resume(client, MASTER_RESUME, JOB_DESCRIPTION, gap_analysis)
    assert tailored_content == tailored_final
    assert len(tailor_usages) == 2

    violations = lint_resume_content(tailored_content)
    assert violations == {}

    pdf_path, unmatched_entries = render_resume(MASTER_RESUME, tailored_content, tmp_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert unmatched_entries == []
    assert client.messages.create.call_count == 3
