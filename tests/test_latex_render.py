import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from core.latex_render import (
    MAX_PDF_PAGES,
    MIN_EXPERIENCE_BULLETS,
    MIN_PROJECT_BULLETS,
    RenderError,
    count_pdf_pages,
    escape_latex,
    find_unmatched_entries,
    render_resume,
)

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
    pdf_path, unmatched_entries, trimmed_entries = render_resume(MASTER_RESUME, TAILORED_CONTENT, tmp_path)

    assert pdf_path == tmp_path / "resume.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert unmatched_entries == []
    assert trimmed_entries == []


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

    pdf_path, unmatched_entries, _ = render_resume(MASTER_RESUME, mismatched_tailored_content, tmp_path)

    assert pdf_path.exists()
    assert unmatched_entries == ["experience: Northwind Data", "project: queue-bench"]


def test_render_resume_includes_certifications_when_present(tmp_path):
    master_with_certs = {
        **MASTER_RESUME,
        "certifications": [
            {"name": "GCP Cloud Architect", "credential": "credly.com/badges/abc-123"},
            {"name": "Salesforce Certified Platform App Builder", "credential": "Credential ID 7910931"},
        ],
    }

    pdf_path, _, _ = render_resume(master_with_certs, TAILORED_CONTENT, tmp_path)

    tex_source = (tmp_path / "resume.tex").read_text(encoding="utf-8")
    assert pdf_path.exists()
    assert "Certifications" in tex_source
    assert "GCP Cloud Architect" in tex_source
    assert "credly.com/badges/abc-123" in tex_source
    assert "Salesforce Certified Platform App Builder" in tex_source
    assert "Credential ID 7910931" in tex_source


def test_render_resume_omits_certifications_section_when_absent(tmp_path):
    pdf_path, _, _ = render_resume(MASTER_RESUME, TAILORED_CONTENT, tmp_path)

    tex_source = (tmp_path / "resume.tex").read_text(encoding="utf-8")
    assert pdf_path.exists()
    assert "Certifications" not in tex_source


def test_count_pdf_pages_returns_correct_page_count(tmp_path):
    pdf_path, _, _ = render_resume(MASTER_RESUME, TAILORED_CONTENT, tmp_path)

    assert count_pdf_pages(pdf_path) == 1


def _repeat_bullet(label: str, index: int) -> str:
    # Long enough that a handful of these reliably force multi-page overflow
    # at the template's compact 10.5pt/0.6in settings, without relying on
    # exact font-metric assumptions.
    return (
        f"{label} bullet {index}: drove a cross-functional initiative spanning "
        "distributed systems, data pipelines, and platform reliability work "
        "that measurably improved throughput, latency, and developer velocity."
    )


def _oversized_master_resume() -> dict:
    experience = []
    for i in range(6):
        experience.append({
            "company": f"Company {i}",
            "title": "Senior Engineer",
            "location": "Remote",
            "start": f"20{10 + i}",
            "end": f"20{11 + i}",
            "bullets": [_repeat_bullet(f"Company {i}", j) for j in range(10)],
        })
    projects = []
    for i in range(4):
        projects.append({
            "name": f"Project {i}",
            "tech": ["Python", "Go"],
            "bullets": [_repeat_bullet(f"Project {i}", j) for j in range(6)],
        })
    return {
        "contact": {
            "name": "Jordan Rivera",
            "email": "jordan.rivera@example.com",
            "phone": "555-123-4567",
            "location": "Austin, TX",
            "links": ["linkedin.com/in/jordanrivera"],
        },
        "summary": "Backend engineer with extensive distributed-systems experience.",
        "skills": [f"Skill{i}" for i in range(20)],
        "experience": experience,
        "projects": projects,
        "education": [
            {"school": "University of Texas at Austin", "degree": "B.S. Computer Science",
             "start": "2014", "end": "2018"}
        ],
    }


def test_render_resume_trims_lowest_priority_bullets_to_fit_page_limit(tmp_path):
    master = _oversized_master_resume()
    # Tailored content mirrors the master exactly (same company/name keys)
    # so nothing is dropped via the unrelated unmatched-entries path — this
    # test is only exercising the page-fit trimming behavior.
    tailored_content = {
        "summary": master["summary"],
        "experience": [{"company": e["company"], "bullets": e["bullets"]} for e in master["experience"]],
        "projects": [{"name": p["name"], "bullets": p["bullets"]} for p in master["projects"]],
    }

    pdf_path, unmatched_entries, trimmed_entries = render_resume(master, tailored_content, tmp_path)

    assert unmatched_entries == []
    assert pdf_path.exists()
    assert count_pdf_pages(pdf_path) <= MAX_PDF_PAGES
    assert trimmed_entries != []

    tex_source = (tmp_path / "resume.tex").read_text(encoding="utf-8")
    # Floors are respected: every entry still has at least its minimum bullet count.
    for i in range(6):
        assert tex_source.count(f"Company {i} bullet") >= MIN_EXPERIENCE_BULLETS
    for i in range(4):
        assert tex_source.count(f"Project {i} bullet") >= MIN_PROJECT_BULLETS
