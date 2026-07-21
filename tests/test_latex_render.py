import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from core.latex_render import RenderError, escape_latex, find_unmatched_entries, render_cover_letter, render_resume

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MASTER_RESUME = json.loads((FIXTURES_DIR / "master_resume.json").read_text())

TAILORED_CONTENT = {
    "summary": "Backend engineer focused on distributed systems & 100% uptime.",
    "experience": [
        {
            "company": "Northwind Data",
            "bullets": [
                "Cut ingestion latency from 40 min to 6 min using Go & Kubernetes.",
                "Owned a zero-downtime PostgreSQL migration for 2M rows/day.",
            ],
        }
    ],
    "projects": [
        {"name": "queue-bench", "bullets": ["Benchmarked queue throughput under load."]}
    ],
}


def test_escape_latex_handles_special_characters():
    result = escape_latex("50% growth & $10K saved_now {test} ~x^2")
    assert result == r"50\% growth \& \$10K saved\_now \{test\} \textasciitilde{}x\textasciicircum{}2"


def test_escape_latex_handles_backslash_without_double_escaping():
    result = escape_latex("a\\b")
    assert result == r"a\textbackslash{}b"


def test_render_resume_produces_pdf(tmp_path):
    pdf_path, unmatched_entries = render_resume(MASTER_RESUME, TAILORED_CONTENT, tmp_path)

    assert pdf_path == tmp_path / "resume.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert unmatched_entries == []


def test_render_resume_raises_render_error_on_tectonic_failure(tmp_path):
    fake_result = subprocess.CompletedProcess(
        args=["tectonic"], returncode=1, stdout="", stderr="! Undefined control sequence."
    )
    with patch("core.latex_render.subprocess.run", return_value=fake_result):
        with pytest.raises(RenderError, match="Undefined control sequence"):
            render_resume(MASTER_RESUME, TAILORED_CONTENT, tmp_path)


def test_find_unmatched_entries_detects_company_and_project_name_mismatch():
    mismatched_tailored_content = {
        "summary": "Backend engineer focused on distributed systems & 100% uptime.",
        "experience": [
            {
                # Trailing whitespace vs. master's "Northwind Data" — a realistic
                # near-miss the model could return.
                "company": "Northwind Data ",
                "bullets": ["This bullet should never reach the rendered PDF."],
            }
        ],
        "projects": [
            {
                # Different casing vs. master's "queue-bench".
                "name": "Queue-Bench",
                "bullets": ["This bullet should never reach the rendered PDF either."],
            }
        ],
    }

    unmatched = find_unmatched_entries(MASTER_RESUME, mismatched_tailored_content)

    assert unmatched == ["experience: Northwind Data", "project: queue-bench"]


def test_render_resume_surfaces_unmatched_entries_and_falls_back_to_master_bullets(tmp_path):
    mismatched_tailored_content = {
        "summary": "Backend engineer focused on distributed systems & 100% uptime.",
        "experience": [
            {"company": "Northwind Data ", "bullets": ["Tailored bullet that should be dropped."]}
        ],
        "projects": [
            {"name": "Queue-Bench", "bullets": ["Tailored bullet that should be dropped."]}
        ],
    }

    pdf_path, unmatched_entries = render_resume(MASTER_RESUME, mismatched_tailored_content, tmp_path)

    assert pdf_path.exists()
    assert unmatched_entries == ["experience: Northwind Data", "project: queue-bench"]


COVER_LETTER_CONTENT = {
    "paragraphs": [
        "I am excited to apply for the Senior Backend Engineer role at Northwind Data.",
        "In my current role I rebuilt the ingestion pipeline in Go, cutting processing "
        "latency from 40 minutes to 6 minutes, which directly matches the scale "
        "problems described in your posting.",
        "I would welcome the opportunity to bring this experience to your team.",
    ]
}


def test_render_cover_letter_produces_pdf(tmp_path):
    pdf_path = render_cover_letter(MASTER_RESUME, COVER_LETTER_CONTENT, tmp_path)

    assert pdf_path == tmp_path / "cover_letter.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
