import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.banned_phrases import lint_resume_content
from core.cover_letter import generate_cover_letter
from core.keyword_analysis import extract_keywords
from core.latex_render import merge_resume, render_cover_letter, render_resume
from core.tailor import passthrough_tailored_content, tailor_resume

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MASTER_RESUME = json.loads((FIXTURES_DIR / "master_resume.json").read_text())
JOB_DESCRIPTION = (FIXTURES_DIR / "job_description.txt").read_text()


def _fake_response(data: dict, input_tokens=1000, output_tokens=400):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(data))],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
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


def test_use_original_resume_path_renders_master_bullets_with_no_unmatched(tmp_path):
    passthrough = passthrough_tailored_content(MASTER_RESUME)

    pdf_path, unmatched_entries = render_resume(MASTER_RESUME, passthrough, tmp_path)

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert unmatched_entries == []


def test_full_pipeline_with_post_tailor_recheck_and_cover_letter(tmp_path):
    client = MagicMock()

    gap_analysis_response = {
        "keywords": ["Go", "Kubernetes", "PostgreSQL"],
        "matched": ["Go", "PostgreSQL"],
        "missing": ["Kubernetes"],
        "match_percentage": 66,
    }
    tailored_final = {
        "summary": "Backend engineer specializing in Go, PostgreSQL, and Kubernetes-based pipelines.",
        "experience": [
            {
                "company": "Northwind Data",
                "bullets": [
                    "Rebuilt the ingestion pipeline in Go and Kubernetes, cutting processing "
                    "latency from 40 minutes to 6 minutes.",
                ],
            }
        ],
        "projects": [
            {"name": "queue-bench", "bullets": ["Built an open-source benchmarking tool for message queue throughput."]}
        ],
    }
    recheck_gap_analysis = {
        "keywords": ["Go", "Kubernetes", "PostgreSQL"],
        "matched": ["Go", "PostgreSQL", "Kubernetes"],
        "missing": [],
        "match_percentage": 100,
    }
    cover_letter_final = {
        "paragraphs": [
            "I am excited to apply for the Senior Backend Engineer role at Northwind Data.",
            "I rebuilt the ingestion pipeline in Go, cutting processing latency from 40 minutes to 6 minutes.",
            "I would welcome the opportunity to bring this experience to your team.",
        ]
    }

    client.messages.create.side_effect = [
        _fake_response(gap_analysis_response),  # initial keyword analysis
        _fake_response(tailored_final),           # tailor draft
        _fake_response(tailored_final),           # tailor critique
        _fake_response(recheck_gap_analysis),     # post-tailor recheck
        _fake_response(cover_letter_final),       # cover letter draft
        _fake_response(cover_letter_final),       # cover letter critique
    ]

    resume_text = MASTER_RESUME["summary"]
    gap_analysis, _ = extract_keywords(client, JOB_DESCRIPTION, resume_text)
    tailored_content, _ = tailor_resume(client, MASTER_RESUME, JOB_DESCRIPTION, gap_analysis)

    pdf_path, unmatched_entries = render_resume(MASTER_RESUME, tailored_content, tmp_path)
    assert unmatched_entries == []

    merged_resume = merge_resume(MASTER_RESUME, tailored_content)
    new_gap_analysis, _ = extract_keywords(client, JOB_DESCRIPTION, json.dumps(merged_resume))
    assert new_gap_analysis["match_percentage"] == 100
    assert new_gap_analysis["match_percentage"] > gap_analysis["match_percentage"]

    cover_letter, cl_usages = generate_cover_letter(client, merged_resume, JOB_DESCRIPTION, "Northwind Data")
    assert cover_letter == cover_letter_final
    assert len(cl_usages) == 2

    cover_letter_pdf_path = render_cover_letter(merged_resume, cover_letter, tmp_path)
    assert cover_letter_pdf_path.exists()
    assert cover_letter_pdf_path.stat().st_size > 0
    assert client.messages.create.call_count == 6
