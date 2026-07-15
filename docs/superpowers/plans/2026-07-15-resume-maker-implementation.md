# Resume Maker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Streamlit app that takes a master resume + a pasted job description and produces an ATS-safe, honestly-tailored PDF resume via a two-pass Claude pipeline and LaTeX/Tectonic rendering.

**Architecture:** Thin Streamlit UI (`app.py`) over plain-Python `core/` modules (resume storage, keyword gap analysis, tailoring, LaTeX rendering, cost tracking) that never import `streamlit`, so the logic stays portable. See `docs/superpowers/specs/2026-07-15-resume-maker-design.md` for the full design rationale.

**Tech Stack:** Python 3.11+, `anthropic` SDK, Streamlit, Jinja2 (LaTeX-safe delimiters), Tectonic (external binary), pytest.

## Global Constraints

- Python packages (exact): `anthropic`, `streamlit`, `jinja2`, `python-dotenv`, `pytest`.
- Models (exact IDs): `claude-haiku-4-5` for keyword extraction, `claude-sonnet-5` as the default for the tailor/self-critique passes, `claude-opus-4-8` as a user-selectable override — never substitute other model IDs.
- Tectonic must be installed and on `PATH` before Task 4 (macOS: `brew install tectonic`). This is an external prerequisite, not something the plan installs.
- Every piece of user- or model-generated text must pass through `escape_latex()` before it reaches the LaTeX template — never interpolate raw text into `.tex` output.
- Anti-fabrication is enforced by always running both the tailor pass and the self-critique pass — never skip the critique pass to save a call.
- Single local user only — no auth, no multi-user data model, no hosting config in this plan.
- `data/master_resume.json`, `data/usage_log.jsonl`, and everything under `output/` must never be committed to git.

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `core/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/master_resume.json`
- Create: `tests/fixtures/job_description.txt`
- Create: `data/.gitkeep`
- Create: `output/.gitkeep`

**Interfaces:**
- Produces: the fixture files `tests/fixtures/master_resume.json` and `tests/fixtures/job_description.txt` that every later test task loads.

- [ ] **Step 1: Create the directory structure and dependency files**

```bash
mkdir -p "core" "tests/fixtures" "templates" "data" "output"
touch "core/__init__.py" "tests/__init__.py" "data/.gitkeep" "output/.gitkeep"
```

- [ ] **Step 2: Write `requirements.txt`**

```
anthropic>=0.40.0
streamlit>=1.38.0
jinja2>=3.1.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

- [ ] **Step 3: Write `.env.example`**

```
ANTHROPIC_API_KEY=your-api-key-here
```

- [ ] **Step 4: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
.env
data/*.json
data/*.jsonl
output/*/
!output/.gitkeep
```

- [ ] **Step 5: Write the shared master resume fixture at `tests/fixtures/master_resume.json`**

```json
{
  "contact": {
    "name": "Jordan Rivera",
    "email": "jordan.rivera@example.com",
    "phone": "555-123-4567",
    "location": "Austin, TX",
    "links": ["linkedin.com/in/jordanrivera"]
  },
  "summary": "Backend engineer with 5 years building distributed systems in Python and Go.",
  "skills": ["Python", "Go", "PostgreSQL", "Kubernetes", "AWS"],
  "experience": [
    {
      "company": "Northwind Data",
      "title": "Senior Backend Engineer",
      "location": "Austin, TX",
      "start": "2022-01",
      "end": "Present",
      "bullets": [
        "Rebuilt the ingestion pipeline in Go, cutting processing latency from 40 minutes to 6 minutes.",
        "Migrated the primary datastore from MySQL to PostgreSQL with zero downtime for 2M daily active rows."
      ]
    }
  ],
  "projects": [
    {
      "name": "queue-bench",
      "bullets": [
        "Built an open-source benchmarking tool for comparing message queue throughput under load."
      ],
      "tech": ["Go", "Redis"]
    }
  ],
  "education": [
    {
      "school": "University of Texas at Austin",
      "degree": "B.S. Computer Science",
      "start": "2014",
      "end": "2018"
    }
  ]
}
```

- [ ] **Step 6: Write the shared job description fixture at `tests/fixtures/job_description.txt`**

```
Senior Backend Engineer — Distributed Systems

We are looking for a Senior Backend Engineer to join our platform team. You will design and build high-throughput data pipelines, own our PostgreSQL infrastructure, and help migrate legacy services to Kubernetes on AWS.

Responsibilities:
- Design and implement backend services in Go and Python
- Own the reliability and performance of our core data ingestion pipeline
- Migrate services from monolithic architecture to Kubernetes-based microservices
- Collaborate with the data team on PostgreSQL schema design and query optimization
- Participate in on-call rotation and incident response

Requirements:
- 5+ years of backend engineering experience
- Strong proficiency in Go or Python
- Experience with PostgreSQL, Kubernetes, and AWS
- Experience with distributed systems and message queues
- Excellent communication skills
```

- [ ] **Step 7: Install dependencies and verify**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: all packages install without error.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .env.example .gitignore core/__init__.py tests/__init__.py tests/fixtures data/.gitkeep output/.gitkeep
git commit -m "chore: project scaffolding and shared test fixtures"
```

---

### Task 2: Banned Phrase Linter

**Files:**
- Create: `core/banned_phrases.py`
- Test: `tests/test_banned_phrases.py`

**Interfaces:**
- Produces: `BANNED_PHRASES: list[str]`, `find_banned_phrases(text: str) -> list[str]`, `lint_resume_content(tailored_content: dict) -> dict[str, list[str]]`. `tailored_content` has the shape `{"summary": str, "experience": [{"company": str, "bullets": [str]}], "projects": [{"name": str, "bullets": [str]}]}` — this exact shape is produced by Task 7's `tailor_resume()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_banned_phrases.py`:

```python
from core.banned_phrases import find_banned_phrases, lint_resume_content


def test_find_banned_phrases_detects_known_phrase():
    result = find_banned_phrases("I spearheaded the migration project.")
    assert "spearheaded" in result


def test_find_banned_phrases_is_case_insensitive():
    result = find_banned_phrases("I LEVERAGED my skills to deliver results.")
    assert "leveraged" in result


def test_find_banned_phrases_returns_empty_for_clean_text():
    result = find_banned_phrases("Cut database query time from 800ms to 120ms.")
    assert result == []


def test_lint_resume_content_flags_summary_and_bullets():
    tailored_content = {
        "summary": "A passionate engineer who leveraged modern tools.",
        "experience": [
            {"company": "Acme", "bullets": ["Spearheaded the rollout.", "Wrote clean code."]}
        ],
        "projects": [
            {"name": "queue-bench", "bullets": ["Built a benchmarking tool."]}
        ],
    }
    violations = lint_resume_content(tailored_content)
    assert "summary" in violations
    assert "Acme bullet 1" in violations
    assert "Acme bullet 2" not in violations
    assert not any(key.startswith("queue-bench") for key in violations)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_banned_phrases.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.banned_phrases'`.

- [ ] **Step 3: Implement `core/banned_phrases.py`**

```python
BANNED_PHRASES = [
    "spearheaded",
    "leveraged",
    "results-driven",
    "utilized",
    "dynamic",
    "passionate",
    "synergy",
    "cutting-edge",
]


def find_banned_phrases(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in BANNED_PHRASES if phrase in lowered]


def lint_resume_content(tailored_content: dict) -> dict[str, list[str]]:
    """Scan every text field of a tailored-resume dict for banned phrases.

    Returns a mapping of location label -> list of phrases found there.
    Empty dict means clean.
    """
    violations: dict[str, list[str]] = {}

    summary_hits = find_banned_phrases(tailored_content.get("summary", ""))
    if summary_hits:
        violations["summary"] = summary_hits

    for job in tailored_content.get("experience", []):
        for i, bullet in enumerate(job.get("bullets", [])):
            hits = find_banned_phrases(bullet)
            if hits:
                violations[f"{job['company']} bullet {i + 1}"] = hits

    for project in tailored_content.get("projects", []):
        for i, bullet in enumerate(project.get("bullets", [])):
            hits = find_banned_phrases(bullet)
            if hits:
                violations[f"{project['name']} bullet {i + 1}"] = hits

    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_banned_phrases.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/banned_phrases.py tests/test_banned_phrases.py
git commit -m "feat: banned-phrase linter for AI-tell language"
```

---

### Task 3: Master Resume Storage

**Files:**
- Create: `core/resume_store.py`
- Test: `tests/test_resume_store.py`

**Interfaces:**
- Produces: `DATA_DIR: Path`, `OUTPUT_DIR: Path`, `load_master_resume(path: Path) -> dict | None`, `save_master_resume(resume: dict, path: Path) -> None`, `save_gap_analysis(run_dir: Path, gap_analysis: dict) -> Path`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resume_store.py`:

```python
import json

from core.resume_store import load_master_resume, save_gap_analysis, save_master_resume


def test_load_master_resume_returns_none_when_file_missing(tmp_path):
    missing_path = tmp_path / "master_resume.json"
    assert load_master_resume(missing_path) is None


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "nested" / "master_resume.json"
    resume = {"summary": "Test resume", "experience": [], "skills": ["Python"]}

    save_master_resume(resume, path)
    loaded = load_master_resume(path)

    assert loaded == resume


def test_save_gap_analysis_writes_json_file(tmp_path):
    run_dir = tmp_path / "Acme_2026-07-15"
    gap_analysis = {"keywords": ["Python"], "matched": ["Python"], "missing": [], "match_percentage": 100}

    result_path = save_gap_analysis(run_dir, gap_analysis)

    assert result_path == run_dir / "gap_analysis.json"
    assert json.loads(result_path.read_text()) == gap_analysis
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_resume_store.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.resume_store'`.

- [ ] **Step 3: Implement `core/resume_store.py`**

```python
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"


def load_master_resume(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_master_resume(resume: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(resume, indent=2), encoding="utf-8")


def save_gap_analysis(run_dir: Path, gap_analysis: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "gap_analysis.json"
    path.write_text(json.dumps(gap_analysis, indent=2), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_resume_store.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/resume_store.py tests/test_resume_store.py
git commit -m "feat: master resume load/save and gap-analysis archival"
```

---

### Task 4: LaTeX Rendering via Tectonic

**Prerequisite:** Tectonic must be installed and on `PATH`. Verify with `tectonic --version` before starting; if missing, run `brew install tectonic` (macOS).

**Files:**
- Create: `templates/resume.tex`
- Create: `core/latex_render.py`
- Test: `tests/test_latex_render.py`

**Interfaces:**
- Consumes: `tests/fixtures/master_resume.json` (Task 1).
- Produces: `RenderError` (exception), `escape_latex(text: str) -> str`, `render_resume(master_resume: dict, tailored_content: dict, output_dir: Path) -> Path`. `tailored_content` has the shape defined in Task 2's interfaces block.

- [ ] **Step 1: Write the LaTeX template at `templates/resume.tex`**

```latex
\documentclass[11pt]{article}
\usepackage[margin=0.75in]{geometry}
\usepackage{enumitem}
\pagestyle{empty}
\setlist[itemize]{leftmargin=*,itemsep=2pt,topsep=2pt,parsep=0pt}

\begin{document}

\begin{center}
{\LARGE \VAR{contact.name}} \\
\VAR{contact.email} \textbar{} \VAR{contact.phone} \textbar{} \VAR{contact.location}
\BLOCK{if contact.links}
\\ \BLOCK{for link in contact.links}\VAR{link}\BLOCK{if not loop.last} \textbar{} \BLOCK{endif}\BLOCK{endfor}
\BLOCK{endif}
\end{center}

\section*{Summary}
\VAR{summary}

\section*{Experience}
\BLOCK{for job in experience}
\textbf{\VAR{job.title}}, \VAR{job.company} \hfill \VAR{job.location} \\
\textit{\VAR{job.start} -- \VAR{job.end}}
\begin{itemize}
\BLOCK{for bullet in job.bullets}
\item \VAR{bullet}
\BLOCK{endfor}
\end{itemize}
\BLOCK{endfor}

\BLOCK{if projects}
\section*{Projects}
\BLOCK{for project in projects}
\textbf{\VAR{project.name}}\BLOCK{if project.tech} \hfill \VAR{project.tech|join(', ')}\BLOCK{endif}
\begin{itemize}
\BLOCK{for bullet in project.bullets}
\item \VAR{bullet}
\BLOCK{endfor}
\end{itemize}
\BLOCK{endfor}
\BLOCK{endif}

\section*{Skills}
\VAR{skills|join(', ')}

\section*{Education}
\BLOCK{for edu in education}
\textbf{\VAR{edu.degree}}, \VAR{edu.school} \hfill \VAR{edu.start} -- \VAR{edu.end} \\
\BLOCK{endfor}

\end{document}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_latex_render.py`:

```python
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from core.latex_render import RenderError, escape_latex, render_resume

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
    pdf_path = render_resume(MASTER_RESUME, TAILORED_CONTENT, tmp_path)

    assert pdf_path == tmp_path / "resume.pdf"
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_render_resume_raises_render_error_on_tectonic_failure(tmp_path):
    fake_result = subprocess.CompletedProcess(
        args=["tectonic"], returncode=1, stdout="", stderr="! Undefined control sequence."
    )
    with patch("core.latex_render.subprocess.run", return_value=fake_result):
        with pytest.raises(RenderError, match="Undefined control sequence"):
            render_resume(MASTER_RESUME, TAILORED_CONTENT, tmp_path)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_latex_render.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.latex_render'`.

- [ ] **Step 4: Implement `core/latex_render.py`**

```python
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"

LATEX_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    block_start_string="\\BLOCK{",
    block_end_string="}",
    variable_start_string="\\VAR{",
    variable_end_string="}",
    comment_start_string="\\#{",
    comment_end_string="}",
    line_statement_prefix="%%",
    line_comment_prefix="%#",
    trim_blocks=True,
    autoescape=False,
)

LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


class RenderError(Exception):
    pass


def escape_latex(text: str) -> str:
    return "".join(LATEX_SPECIAL_CHARS.get(char, char) for char in text)


def _escape_context(value):
    if isinstance(value, str):
        return escape_latex(value)
    if isinstance(value, list):
        return [_escape_context(v) for v in value]
    if isinstance(value, dict):
        return {k: _escape_context(v) for k, v in value.items()}
    return value


def _merge_resume(master_resume: dict, tailored_content: dict) -> dict:
    tailored_by_company = {e["company"]: e for e in tailored_content.get("experience", [])}
    merged_experience = []
    for job in master_resume["experience"]:
        tailored_job = tailored_by_company.get(job["company"])
        merged_experience.append(
            {**job, "bullets": tailored_job["bullets"] if tailored_job else job["bullets"]}
        )

    tailored_by_name = {p["name"]: p for p in tailored_content.get("projects", [])}
    merged_projects = []
    for project in master_resume.get("projects", []):
        tailored_project = tailored_by_name.get(project["name"])
        merged_projects.append(
            {**project, "bullets": tailored_project["bullets"] if tailored_project else project["bullets"]}
        )

    return {
        "contact": master_resume["contact"],
        "summary": tailored_content.get("summary", master_resume["summary"]),
        "skills": master_resume["skills"],
        "experience": merged_experience,
        "projects": merged_projects,
        "education": master_resume["education"],
    }


def render_resume(master_resume: dict, tailored_content: dict, output_dir: Path) -> Path:
    merged = _merge_resume(master_resume, tailored_content)
    escaped = _escape_context(merged)

    template = LATEX_JINJA_ENV.get_template("resume.tex")
    tex_source = template.render(**escaped)

    output_dir.mkdir(parents=True, exist_ok=True)
    tex_path = output_dir / "resume.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    result = subprocess.run(
        ["tectonic", "--outdir", str(output_dir), str(tex_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RenderError(
            f"Tectonic failed to compile {tex_path}:\n{result.stdout}\n{result.stderr}"
        )

    pdf_path = output_dir / "resume.pdf"
    if not pdf_path.exists():
        raise RenderError(f"Tectonic reported success but no PDF was produced at {pdf_path}")
    return pdf_path
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_latex_render.py -v
```

Expected: 4 passed. (`test_render_resume_produces_pdf` requires `tectonic` on `PATH` — if it fails with `FileNotFoundError`, install Tectonic first.)

- [ ] **Step 6: Commit**

```bash
git add templates/resume.tex core/latex_render.py tests/test_latex_render.py
git commit -m "feat: ATS-safe LaTeX template and Tectonic rendering pipeline"
```

---

### Task 5: Usage & Cost Tracking

**Files:**
- Create: `core/usage_tracker.py`
- Test: `tests/test_usage_tracker.py`

**Interfaces:**
- Produces: `PRICING: dict`, `estimate_cost(model: str, input_tokens: int, output_tokens: int, cache_creation_input_tokens: int = 0, cache_read_input_tokens: int = 0) -> float`, `log_usage(call_type: str, model: str, input_tokens: int, output_tokens: int, log_path: Path, cache_creation_input_tokens: int = 0, cache_read_input_tokens: int = 0) -> None`, `get_cost_summary(log_path: Path) -> dict` returning `{"today_cost": float, "month_cost": float}`. Cache token accounting exists because Task 7 turns on prompt caching for the tailor pipeline — without it, the cost tracker would over-report cost once caching kicks in.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_usage_tracker.py`:

```python
import json
from datetime import datetime, timedelta, timezone

from core.usage_tracker import estimate_cost, get_cost_summary, log_usage


def test_estimate_cost_computes_correct_value_for_known_model():
    cost = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 12.00  # $2 input + $10 output per Sonnet 5 intro pricing


def test_estimate_cost_returns_zero_for_unknown_model():
    assert estimate_cost("some-future-model", input_tokens=1000, output_tokens=1000) == 0.0


def test_estimate_cost_discounts_cache_reads():
    full_price = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
    cached = estimate_cost(
        "claude-sonnet-5", input_tokens=0, output_tokens=0, cache_read_input_tokens=1_000_000
    )
    assert round(cached, 6) == round(full_price * 0.1, 6)


def test_estimate_cost_surcharges_cache_writes():
    full_price = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
    written = estimate_cost(
        "claude-sonnet-5", input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000
    )
    assert round(written, 6) == round(full_price * 1.25, 6)


def test_log_usage_appends_jsonl_entry(tmp_path):
    log_path = tmp_path / "usage_log.jsonl"

    log_usage("keyword_analysis", "claude-haiku-4-5", 1000, 200, log_path)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["call_type"] == "keyword_analysis"
    assert entry["model"] == "claude-haiku-4-5"
    assert entry["input_tokens"] == 1000
    assert entry["output_tokens"] == 200
    assert entry["cache_creation_input_tokens"] == 0
    assert entry["cache_read_input_tokens"] == 0
    assert entry["cost"] > 0


def test_log_usage_records_cache_tokens_when_provided(tmp_path):
    log_path = tmp_path / "usage_log.jsonl"

    log_usage(
        "tailor", "claude-sonnet-5", 500, 300, log_path,
        cache_creation_input_tokens=1200, cache_read_input_tokens=0,
    )

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["cache_creation_input_tokens"] == 1200
    assert entry["cost"] > estimate_cost("claude-sonnet-5", 500, 300)


def test_get_cost_summary_sums_todays_and_months_entries(tmp_path):
    log_path = tmp_path / "usage_log.jsonl"
    now = datetime.now(timezone.utc)
    last_month = now.replace(day=1) - timedelta(days=1)

    entries = [
        {"timestamp": now.isoformat(), "call_type": "tailor", "model": "claude-sonnet-5",
         "input_tokens": 1000, "output_tokens": 500, "cost": 0.01},
        {"timestamp": now.isoformat(), "call_type": "tailor", "model": "claude-sonnet-5",
         "input_tokens": 1000, "output_tokens": 500, "cost": 0.02},
        {"timestamp": last_month.isoformat(), "call_type": "tailor", "model": "claude-sonnet-5",
         "input_tokens": 1000, "output_tokens": 500, "cost": 5.00},
    ]
    with log_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    summary = get_cost_summary(log_path)

    assert round(summary["today_cost"], 2) == 0.03
    assert round(summary["month_cost"], 2) == 0.03


def test_get_cost_summary_returns_zeros_when_log_missing(tmp_path):
    summary = get_cost_summary(tmp_path / "does_not_exist.jsonl")
    assert summary == {"today_cost": 0.0, "month_cost": 0.0}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_usage_tracker.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.usage_tracker'`.

- [ ] **Step 3: Implement `core/usage_tracker.py`**

```python
import json
from datetime import datetime, timezone
from pathlib import Path

# Sonnet 5 uses intro pricing, active through 2026-08-31.
PRICING = {
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    input_cost = input_tokens / 1_000_000 * rates["input"]
    output_cost = output_tokens / 1_000_000 * rates["output"]
    # Cache writes bill at 1.25x the base input rate; cache reads bill at 0.1x.
    cache_write_cost = cache_creation_input_tokens / 1_000_000 * rates["input"] * 1.25
    cache_read_cost = cache_read_input_tokens / 1_000_000 * rates["input"] * 0.1
    return input_cost + output_cost + cache_write_cost + cache_read_cost


def log_usage(
    call_type: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    log_path: Path,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "call_type": call_type,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "cost": estimate_cost(
            model, input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens
        ),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_cost_summary(log_path: Path) -> dict:
    if not log_path.exists():
        return {"today_cost": 0.0, "month_cost": 0.0}

    now = datetime.now(timezone.utc)
    today_cost = 0.0
    month_cost = 0.0

    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            entry_time = datetime.fromisoformat(entry["timestamp"])
            if entry_time.date() == now.date():
                today_cost += entry["cost"]
            if entry_time.year == now.year and entry_time.month == now.month:
                month_cost += entry["cost"]

    return {"today_cost": today_cost, "month_cost": month_cost}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_usage_tracker.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add core/usage_tracker.py tests/test_usage_tracker.py
git commit -m "feat: local API usage and cost tracking"
```

---

### Task 6: Keyword Gap Analysis (Claude Haiku 4.5)

**Files:**
- Create: `core/keyword_analysis.py`
- Test: `tests/test_keyword_analysis.py`

**Interfaces:**
- Produces: `extract_keywords(client, job_description: str, resume_text: str) -> tuple[dict, Usage]` where the returned dict has shape `{"keywords": [str], "matched": [str], "missing": [str], "match_percentage": int}` and `Usage` exposes `.input_tokens` / `.output_tokens` (matches `anthropic`'s response `.usage`).
- Deliberately **no prompt caching here**, unlike Task 7: Haiku 4.5's minimum cacheable prefix is 4096 tokens, and a resume's plain-text form is typically far shorter — a cache breakpoint would silently never activate, so it's not worth the added complexity for this call.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keyword_analysis.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_keyword_analysis.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.keyword_analysis'`.

- [ ] **Step 3: Implement `core/keyword_analysis.py`**

```python
import json

MODEL = "claude-haiku-4-5"

KEYWORD_SCHEMA = {
    "type": "object",
    "properties": {
        "keywords": {"type": "array", "items": {"type": "string"}},
        "matched": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "match_percentage": {"type": "integer"},
    },
    "required": ["keywords", "matched", "missing", "match_percentage"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You extract the most important skills, tools, and qualifications from a "
    "job description, then compare them against a candidate's resume. "
    "Return 15 to 25 of the most important keywords from the job description, "
    "then split them into 'matched' (present in the resume, even if phrased "
    "differently) and 'missing' (not present in the resume). "
    "match_percentage is matched count divided by (matched + missing) count, "
    "as an integer 0-100."
)


def extract_keywords(client, job_description: str, resume_text: str):
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": KEYWORD_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Job description:\n{job_description}\n\n"
                    f"Candidate resume:\n{resume_text}"
                ),
            }
        ],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text), response.usage
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keyword_analysis.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/keyword_analysis.py tests/test_keyword_analysis.py
git commit -m "feat: JD keyword extraction and gap analysis via Haiku 4.5"
```

---

### Task 7: Resume Tailoring — Two-Pass Pipeline (Claude Sonnet 5)

**Files:**
- Create: `core/tailor.py`
- Test: `tests/test_tailor.py`

**Interfaces:**
- Consumes: `core.banned_phrases.BANNED_PHRASES` (Task 2).
- Produces: `tailor_resume(client, master_resume: dict, job_description: str, gap_analysis: dict, model: str = "claude-sonnet-5") -> tuple[dict, list[Usage]]`. The returned dict has the same shape consumed by `core.latex_render.render_resume`'s `tailored_content` argument and `core.banned_phrases.lint_resume_content`.
- Both underlying API calls mark the master-resume text as a cacheable content block (`cache_control: {"type": "ephemeral"}`), per the spec's cost design — it's identical across every application run in a session, so the 2nd+ application of the day reads it from cache instead of paying full input price. `Usage` objects returned therefore also carry `.cache_creation_input_tokens` / `.cache_read_input_tokens`, which Task 8 passes through to `usage_tracker.log_usage`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tailor.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_tailor.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.tailor'`.

Note: `test_tailor_resume_marks_master_resume_block_as_cacheable` will also fail once the module exists but before Step 3's caching-aware implementation is written (it currently expects `messages[0]["content"]` to be a list of content blocks, not the plain string an earlier draft would produce) — that failure is expected until Step 3 is complete.

- [ ] **Step 3: Implement `core/tailor.py`**

```python
import json

from core.banned_phrases import BANNED_PHRASES

DEFAULT_MODEL = "claude-sonnet-5"

TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["company", "bullets"],
                "additionalProperties": False,
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "bullets"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "experience", "projects"],
    "additionalProperties": False,
}

_BANNED_PHRASE_LIST = ", ".join(BANNED_PHRASES)

TAILOR_SYSTEM_PROMPT = (
    "You rewrite resume content to target a specific job description. "
    "Rules you must follow exactly:\n"
    "1. Every fact, number, tool, and claim in your output must be traceable "
    "to the candidate's original resume you are given. Never invent metrics, "
    "tools, or experience the candidate does not have.\n"
    "2. Use the candidate's existing bullets as a voice reference — match "
    "their vocabulary and sentence rhythm — but you may sharpen phrasing, "
    "verbs, and structure where it is a genuine improvement in clarity or "
    "impact.\n"
    "3. Weave in keywords from the job description's gap analysis only where "
    "the candidate genuinely has that skill or experience.\n"
    f"4. Never use these words or phrases: {_BANNED_PHRASE_LIST}.\n"
    "5. Return content for every experience entry and project in the "
    "original resume, even if unchanged."
)

CRITIQUE_SYSTEM_PROMPT = (
    "You review a draft tailored resume against the candidate's original "
    "resume. For every bullet and the summary, verify it is grounded in a "
    "fact present in the original resume — if you find a claim that is not "
    "traceable to the original, rewrite that bullet to only include what is "
    "traceable, or remove the unsupported part. Also check for these banned "
    f"phrases and rewrite any bullet containing them: {_BANNED_PHRASE_LIST}. "
    "Return the corrected resume in the same JSON shape you were given."
)


def _build_content_blocks(stable_text: str, volatile_text: str) -> list[dict]:
    """Two content blocks: a cacheable stable prefix, then varying content after it.

    The stable block (the master resume) is identical across every application
    tailored in a session, so marking it cacheable means the 2nd+ application
    of the day reads it at ~10% of input price instead of full price. It must
    come first — caching is a prefix match, so anything after the breakpoint
    (the job description, which changes every call) cannot itself be cached.
    """
    return [
        {"type": "text", "text": stable_text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": volatile_text},
    ]


def _run_json_call(client, model: str, system_prompt: str, content_blocks: list[dict]):
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        output_config={"format": {"type": "json_schema", "schema": TAILOR_SCHEMA}},
        messages=[{"role": "user", "content": content_blocks}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text), response.usage


def tailor_resume(
    client,
    master_resume: dict,
    job_description: str,
    gap_analysis: dict,
    model: str = DEFAULT_MODEL,
):
    stable_resume_text = f"Candidate's original resume (JSON):\n{json.dumps(master_resume)}"

    tailor_volatile = (
        f"Job description:\n{job_description}\n\n"
        f"Keyword gap analysis:\n{json.dumps(gap_analysis)}"
    )
    draft, tailor_usage = _run_json_call(
        client, model, TAILOR_SYSTEM_PROMPT, _build_content_blocks(stable_resume_text, tailor_volatile)
    )

    critique_volatile = f"Draft tailored resume to review (JSON):\n{json.dumps(draft)}"
    final, critique_usage = _run_json_call(
        client, model, CRITIQUE_SYSTEM_PROMPT, _build_content_blocks(stable_resume_text, critique_volatile)
    )

    return final, [tailor_usage, critique_usage]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_tailor.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/tailor.py tests/test_tailor.py
git commit -m "feat: two-pass resume tailoring with anti-fabrication self-critique"
```

---

### Task 8: Streamlit UI

**Prerequisite:** Copy `.env.example` to `.env` and fill in a real `ANTHROPIC_API_KEY` before manual verification.

**Files:**
- Create: `app.py`

**Interfaces:**
- Consumes: every `core/*` function produced by Tasks 2–7.

- [ ] **Step 1: Implement `app.py`**

```python
from datetime import datetime

import anthropic
import streamlit as st
from dotenv import load_dotenv

from core.banned_phrases import lint_resume_content
from core.keyword_analysis import extract_keywords
from core.latex_render import RenderError, render_resume
from core.resume_store import DATA_DIR, OUTPUT_DIR, load_master_resume, save_gap_analysis, save_master_resume
from core.tailor import tailor_resume
from core.usage_tracker import get_cost_summary, log_usage

load_dotenv()

USAGE_LOG_PATH = DATA_DIR / "usage_log.jsonl"
MASTER_RESUME_PATH = DATA_DIR / "master_resume.json"

st.set_page_config(page_title="Resume Maker", layout="wide")


def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def resume_to_text(resume: dict) -> str:
    lines = [resume["summary"]]
    for job in resume["experience"]:
        lines.append(f"{job['title']} at {job['company']}")
        lines.extend(job["bullets"])
    for project in resume.get("projects", []):
        lines.append(project["name"])
        lines.extend(project["bullets"])
    lines.append("Skills: " + ", ".join(resume["skills"]))
    return "\n".join(lines)


def render_sidebar():
    summary = get_cost_summary(USAGE_LOG_PATH)
    applications_today = 0
    if OUTPUT_DIR.exists():
        today_str = datetime.now().strftime("%Y-%m-%d")
        applications_today = sum(1 for p in OUTPUT_DIR.iterdir() if p.is_dir() and today_str in p.name)
    st.sidebar.metric("Today", f"${summary['today_cost']:.2f}", f"{applications_today} applications")
    st.sidebar.metric("This month", f"${summary['month_cost']:.2f}")


def master_resume_form():
    st.header("Set up your master resume")
    st.write("Paste your resume as JSON matching the master resume schema, once.")
    raw = st.text_area("Master resume JSON", height=400)
    if st.button("Save master resume"):
        import json

        try:
            resume = json.loads(raw)
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
            return
        save_master_resume(resume, MASTER_RESUME_PATH)
        st.success("Master resume saved.")
        st.rerun()


def tailoring_flow(master_resume: dict):
    st.header("Tailor a resume")
    job_description = st.text_area("Paste the job description", height=300)
    company = st.text_input("Company name (for the archive folder)")
    model = st.selectbox("Model", ["claude-sonnet-5", "claude-opus-4-8"], index=0)

    if st.button("Generate tailored resume"):
        if len(job_description.strip()) < 100:
            st.error("That job description looks too short — paste the full posting.")
            return
        if not company.strip():
            st.error("Enter a company name so the output can be archived.")
            return

        client = get_client()
        resume_text = resume_to_text(master_resume)

        with st.spinner("Extracting keywords from the job description..."):
            gap_analysis, kw_usage = extract_keywords(client, job_description, resume_text)
            log_usage(
                "keyword_analysis", "claude-haiku-4-5",
                kw_usage.input_tokens, kw_usage.output_tokens, USAGE_LOG_PATH,
                cache_creation_input_tokens=kw_usage.cache_creation_input_tokens,
                cache_read_input_tokens=kw_usage.cache_read_input_tokens,
            )

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Matched keywords")
            st.write(", ".join(gap_analysis["matched"]) or "None found")
        with col2:
            st.subheader("Missing keywords")
            st.write(", ".join(gap_analysis["missing"]) or "None found")
        st.metric("Match score", f"{gap_analysis['match_percentage']}%")

        with st.spinner("Tailoring your resume..."):
            tailored_content, tailor_usages = tailor_resume(
                client, master_resume, job_description, gap_analysis, model=model
            )
            for usage in tailor_usages:
                log_usage(
                    "tailor", model, usage.input_tokens, usage.output_tokens, USAGE_LOG_PATH,
                    cache_creation_input_tokens=usage.cache_creation_input_tokens,
                    cache_read_input_tokens=usage.cache_read_input_tokens,
                )

        violations = lint_resume_content(tailored_content)
        if violations:
            st.warning(f"Banned phrases survived the self-critique pass: {violations}")

        date_str = datetime.now().strftime("%Y-%m-%d")
        run_dir = OUTPUT_DIR / f"{company.strip().replace(' ', '_')}_{date_str}"

        with st.spinner("Rendering PDF..."):
            try:
                pdf_path = render_resume(master_resume, tailored_content, run_dir)
            except RenderError as e:
                st.error(f"PDF rendering failed:\n\n{e}")
                return

        save_gap_analysis(run_dir, gap_analysis)

        st.success("Resume ready.")
        with open(pdf_path, "rb") as f:
            st.download_button("Download PDF", f, file_name=f"resume_{company.strip()}.pdf")


def main():
    render_sidebar()
    master_resume = load_master_resume(MASTER_RESUME_PATH)
    if master_resume is None:
        master_resume_form()
        return

    tailoring_flow(master_resume)
    if st.sidebar.checkbox("Replace master resume"):
        master_resume_form()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manually verify the master-resume setup flow**

```bash
cp .env.example .env  # then edit .env and add a real ANTHROPIC_API_KEY
streamlit run app.py
```

In the browser: paste the contents of `tests/fixtures/master_resume.json` into the text area, click "Save master resume". Expected: success message, page reruns into the tailoring view, and `data/master_resume.json` now exists on disk with that content.

- [ ] **Step 3: Manually verify the tailoring flow**

Paste the contents of `tests/fixtures/job_description.txt` into the job description box, enter "Acme" as the company, click "Generate tailored resume". Expected: matched/missing keyword columns populate, a match score appears, a success message appears, a "Download PDF" button appears, and `output/Acme_<today's date>/` contains `resume.tex`, `resume.pdf`, and `gap_analysis.json`.

- [ ] **Step 4: Manually verify the cost sidebar**

Expected: after Step 3, the sidebar's "Today" metric shows a non-zero dollar amount and "1 applications", matching what's in `data/usage_log.jsonl`.

- [ ] **Step 5: Manually verify prompt caching is active**

Repeat Step 3 with a different company name (e.g. "Beta Corp") in the same running app session. Then inspect the log:

```bash
tail -n 6 data/usage_log.jsonl | python3 -c "import json,sys; [print(json.loads(l)['call_type'], json.loads(l)['cache_read_input_tokens']) for l in sys.stdin]"
```

Expected: the `tailor` entries from this second run show a non-zero `cache_read_input_tokens` (the master-resume block was served from cache), while the first run's entries showed `cache_creation_input_tokens` > 0 instead. If both are 0 on the second run, the master resume is likely too short to clear the model's minimum cacheable prefix — not a bug, just means caching won't help until the resume is longer.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: Streamlit UI wiring the full tailoring pipeline"
```

---

### Task 9: End-to-End Integration Smoke Test

**Prerequisite:** Tectonic must be on `PATH` (same as Task 4).

**Files:**
- Create: `tests/test_integration_pipeline.py`

**Interfaces:**
- Consumes: `core.keyword_analysis.extract_keywords`, `core.tailor.tailor_resume`, `core.latex_render.render_resume`, `core.banned_phrases.lint_resume_content` (all prior tasks), `tests/fixtures/master_resume.json` and `tests/fixtures/job_description.txt` (Task 1).

- [ ] **Step 1: Write the failing test**

Create `tests/test_integration_pipeline.py`:

```python
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

    pdf_path = render_resume(MASTER_RESUME, tailored_content, tmp_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert client.messages.create.call_count == 3
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_integration_pipeline.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` if any prior task is incomplete — otherwise it should already pass, since every piece it exercises was built and unit-tested in Tasks 4, 6, and 7. If it fails for a reason other than a missing module, that's a real integration bug — fix the mismatch between tasks before proceeding.

- [ ] **Step 3: Run the test to verify it passes**

```bash
pytest tests/test_integration_pipeline.py -v
```

Expected: 1 passed.

- [ ] **Step 4: Run the full test suite**

```bash
pytest -v
```

Expected: all tests across every task pass together.

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_pipeline.py
git commit -m "test: end-to-end smoke test from JD to compiled PDF"
```
