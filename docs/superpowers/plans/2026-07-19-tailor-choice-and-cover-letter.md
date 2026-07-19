# Tailor/Skip Choice, Match-% Recompute, and Cover Letter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user choose whether to tailor the resume after seeing the keyword gap analysis (vs. just downloading the original), show how much the match percentage improved after tailoring, and add an option to generate a matching cover letter.

**Architecture:** Extends the existing single-page Streamlit app (`app.py`) with `st.session_state` as a small state machine, so the current one-shot "Generate tailored resume" button becomes: Analyze → (Tailor | Use original | Generate cover letter), each independently clickable once analysis exists. New logic lives in small, focused core modules (`core/cover_letter.py`, additions to `core/tailor.py` and `core/latex_render.py`) that mirror the existing `core/tailor.py` / `core/keyword_analysis.py` two-pass and JSON-schema patterns exactly, so behavior stays consistent with the already-shipped pipeline.

**Tech Stack:** Python, Streamlit, Anthropic SDK (`anthropic`), Jinja2 (LaTeX templates), Tectonic (PDF compile), pytest.

## Global Constraints

- Python must run on the environment's current interpreter, which is 3.9.6 — do not use `X | None` union syntax; use `Optional[X]` from `typing` where needed (matches existing `core/resume_store.py` convention).
- Every Claude API call and every `RenderError` must be wrapped in try/except, surfaced to the user via `st.error(...)`, and return early — this is the established convention in `app.py` (added in commit `5c177c3` after the original final review flagged missing error handling).
- New Claude-call modules mirror `core/tailor.py`'s exact shape: a `DEFAULT_MODEL` constant, a JSON-schema dict passed via `output_config={"format": {"type": "json_schema", "schema": ...}}`, a two-pass draft+critique flow, and a cacheable stable content block (`cache_control: {"type": "ephemeral"}`) placed before the volatile block — never after.
- Banned-phrase checking always uses `core.banned_phrases.find_banned_phrases` (or `lint_resume_content` for resume-shaped dicts) — do not introduce a second banned-word list.
- Every `log_usage(...)` call must pass `cache_creation_input_tokens` and `cache_read_input_tokens` through from the SDK response's `usage` object, even when zero — this is required for `core/usage_tracker.py`'s cost math to stay accurate.
- Test fixtures: use `tests/fixtures/master_resume.json` (full resume shape, includes `contact`/`education`) for any test that exercises `render_resume`, `merge_resume`, or `render_cover_letter`, since those functions require `contact` and `education` keys that ad hoc test dicts may lack.

---

### Task 1: Passthrough resume content for the "use original" path

**Files:**
- Modify: `core/tailor.py`
- Test: `tests/test_tailor.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `passthrough_tailored_content(master_resume: dict) -> dict`, returning a dict in the same `{"summary": str, "experience": [{"company": str, "bullets": [str]}], "projects": [{"name": str, "bullets": [str]}]}` shape that `tailor_resume` returns, but with every bullet copied unchanged from `master_resume`. Later tasks (app.py) pass this straight into `render_resume` to render the original resume with zero tailored-content mismatches.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tailor.py` (below the existing tests, keep existing imports and `MASTER_RESUME`/`GAP_ANALYSIS` constants unchanged):

```python
from pathlib import Path

from core.tailor import passthrough_tailored_content

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FULL_MASTER_RESUME = json.loads((FIXTURES_DIR / "master_resume.json").read_text())


def test_passthrough_tailored_content_mirrors_master_resume_bullets_unchanged():
    result = passthrough_tailored_content(MASTER_RESUME)

    assert result["summary"] == MASTER_RESUME["summary"]
    assert result["experience"] == [
        {"company": "Northwind Data", "bullets": ["Rebuilt the ingestion pipeline in Go."]}
    ]
    assert result["projects"] == [
        {"name": "queue-bench", "bullets": ["Built a benchmarking tool."]}
    ]


def test_passthrough_tailored_content_round_trips_through_render_resume_with_no_unmatched(tmp_path):
    from core.latex_render import render_resume

    passthrough = passthrough_tailored_content(FULL_MASTER_RESUME)
    pdf_path, unmatched_entries = render_resume(FULL_MASTER_RESUME, passthrough, tmp_path)

    assert pdf_path.exists()
    assert unmatched_entries == []
```

Note: `tests/test_tailor.py` already imports `json` at the top of the file — only add `from pathlib import Path` (new), do not re-import `json`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_tailor.py -v -k passthrough
```

Expected: FAIL with `ImportError: cannot import name 'passthrough_tailored_content'`.

- [ ] **Step 3: Implement `passthrough_tailored_content`**

Add to `core/tailor.py`, after the `TAILOR_SCHEMA` definition and before `_BANNED_PHRASE_LIST`:

```python
def passthrough_tailored_content(master_resume: dict) -> dict:
    """Build a tailored-content-shaped dict from the master resume, unchanged.

    Used for the "use original resume as-is" path, so it can be fed straight
    into render_resume without a Claude call — the company/name keys match
    exactly, so render_resume's merge is a no-op and unmatched_entries is
    always empty.
    """
    return {
        "summary": master_resume["summary"],
        "experience": [
            {"company": job["company"], "bullets": job["bullets"]}
            for job in master_resume["experience"]
        ],
        "projects": [
            {"name": project["name"], "bullets": project["bullets"]}
            for project in master_resume.get("projects", [])
        ],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_tailor.py -v
```

Expected: all tests in the file pass (existing 4 + 2 new = 6 passed).

- [ ] **Step 5: Commit**

```bash
git add core/tailor.py tests/test_tailor.py
git commit -m "feat: passthrough tailored-content builder for the use-original-resume path"
```

---

### Task 2: Cover letter generation core module

**Files:**
- Create: `core/cover_letter.py`
- Test: `tests/test_cover_letter.py`

**Interfaces:**
- Consumes: `core.banned_phrases.BANNED_PHRASES` (list of strings).
- Produces: `COVER_LETTER_SCHEMA: dict`, `DEFAULT_MODEL: str` ("claude-sonnet-5"), `generate_cover_letter(client, resume_content: dict, job_description: str, company: str, model: str = DEFAULT_MODEL) -> tuple[dict, list]` returning `({"paragraphs": [str, ...]}, [draft_usage, critique_usage])`. `resume_content` is a full resume-shaped dict (same shape as `master_resume` or the output of `core.latex_render.merge_resume`) — Task 4 (app.py) decides which to pass in.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cover_letter.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_cover_letter.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.cover_letter'`.

- [ ] **Step 3: Implement `core/cover_letter.py`**

```python
import json

from core.banned_phrases import BANNED_PHRASES

DEFAULT_MODEL = "claude-sonnet-5"

COVER_LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["paragraphs"],
    "additionalProperties": False,
}

_BANNED_PHRASE_LIST = ", ".join(BANNED_PHRASES)

DRAFT_SYSTEM_PROMPT = (
    "You write a professional cover letter for a candidate applying to a "
    "specific job. Rules you must follow exactly:\n"
    "1. Every fact, number, tool, and claim in your output must be traceable "
    "to the candidate's resume you are given. Never invent metrics, tools, "
    "or experience the candidate does not have.\n"
    "2. Address why the candidate is a strong fit for this specific role, "
    "referencing 2-3 concrete achievements from their resume.\n"
    "3. Match the candidate's existing resume vocabulary and tone — do not "
    "invent a different voice.\n"
    f"4. Never use these words or phrases: {_BANNED_PHRASE_LIST}.\n"
    "5. Return 3 to 5 paragraphs: an opening naming the role and company, "
    "one or two body paragraphs grounding fit in real resume facts, and a "
    "closing paragraph. Do not include a greeting, date, or sign-off — "
    "those are added separately by the renderer."
)

CRITIQUE_SYSTEM_PROMPT = (
    "You review a draft cover letter against the candidate's original "
    "resume. For every paragraph, verify it is grounded in a fact present "
    "in the original resume — if you find a claim that is not traceable to "
    "the original, rewrite that paragraph to only include what is "
    "traceable, or remove the unsupported part. Also check for these "
    f"banned phrases and rewrite any paragraph containing them: "
    f"{_BANNED_PHRASE_LIST}. Return the corrected letter in the same JSON "
    "shape you were given."
)


def _build_content_blocks(stable_text: str, volatile_text: str) -> list[dict]:
    return [
        {"type": "text", "text": stable_text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": volatile_text},
    ]


def _run_json_call(client, model: str, system_prompt: str, content_blocks: list[dict]):
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        output_config={"format": {"type": "json_schema", "schema": COVER_LETTER_SCHEMA}},
        messages=[{"role": "user", "content": content_blocks}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text), response.usage


def generate_cover_letter(
    client,
    resume_content: dict,
    job_description: str,
    company: str,
    model: str = DEFAULT_MODEL,
):
    stable_resume_text = f"Candidate's resume (JSON):\n{json.dumps(resume_content)}"

    draft_volatile = f"Company: {company}\n\nJob description:\n{job_description}"
    draft, draft_usage = _run_json_call(
        client, model, DRAFT_SYSTEM_PROMPT, _build_content_blocks(stable_resume_text, draft_volatile)
    )

    critique_volatile = f"Draft cover letter to review (JSON):\n{json.dumps(draft)}"
    final, critique_usage = _run_json_call(
        client, model, CRITIQUE_SYSTEM_PROMPT, _build_content_blocks(stable_resume_text, critique_volatile)
    )

    return final, [draft_usage, critique_usage]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_cover_letter.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/cover_letter.py tests/test_cover_letter.py
git commit -m "feat: two-pass cover letter generation with anti-fabrication critique"
```

---

### Task 3: Cover letter PDF rendering + latex_render refactor

**Files:**
- Modify: `core/latex_render.py`
- Create: `templates/cover_letter.tex`
- Test: `tests/test_latex_render.py`

**Interfaces:**
- Consumes: `core.cover_letter.generate_cover_letter`'s return shape (`{"paragraphs": [str, ...]}`), full resume-shaped dicts (must include `contact.name/email/phone/location/links`).
- Produces: `merge_resume(master_resume: dict, tailored_content: dict) -> dict` (renamed from the existing private `_merge_resume` — same behavior, now importable by `app.py` for the post-tailor match recompute in Task 4), `render_cover_letter(resume_content: dict, cover_letter: dict, output_dir: Path) -> Path`.

- [ ] **Step 1: Write the failing test**

In `tests/test_latex_render.py`, change the import line at the top from:

```python
from core.latex_render import RenderError, escape_latex, find_unmatched_entries, render_resume
```

to:

```python
from core.latex_render import RenderError, escape_latex, find_unmatched_entries, render_cover_letter, render_resume
```

Then add this test anywhere after the existing tests (it uses the module-level `MASTER_RESUME` fixture already loaded at the top of the file from `tests/fixtures/master_resume.json`):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_latex_render.py -v -k cover_letter
```

Expected: FAIL with `ImportError: cannot import name 'render_cover_letter'`.

- [ ] **Step 3: Refactor `core/latex_render.py`**

Add `from datetime import datetime` to the imports at the top (alongside the existing `import subprocess` and `from pathlib import Path`).

Rename `_merge_resume` to `merge_resume` (drop the leading underscore — no other change to its body), and update `render_resume`'s call site from `merged = _merge_resume(...)` to `merged = merge_resume(...)`.

Extract the tectonic-compile block out of `render_resume` into a shared helper. Replace the current `render_resume` function body:

```python
def render_resume(master_resume: dict, tailored_content: dict, output_dir: Path) -> tuple[Path, list[str]]:
    """Render the tailored resume to PDF.

    Returns a tuple of (pdf_path, unmatched_entries), where unmatched_entries
    lists master experience/project entries whose tailored counterpart could
    not be matched by exact `company`/`name` and therefore fell back to the
    original, untailored bullets. Callers should surface a warning to the
    user when this list is non-empty.
    """
    unmatched_entries = find_unmatched_entries(master_resume, tailored_content)
    merged = merge_resume(master_resume, tailored_content)
    escaped = _escape_context(merged)

    template = LATEX_JINJA_ENV.get_template("resume.tex")
    tex_source = template.render(**escaped)

    output_dir.mkdir(parents=True, exist_ok=True)
    tex_path = output_dir / "resume.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    pdf_path = _compile_tex(tex_path, output_dir, "resume")
    return pdf_path, unmatched_entries
```

Add the shared helper just above `render_resume`:

```python
def _compile_tex(tex_path: Path, output_dir: Path, output_stem: str) -> Path:
    result = subprocess.run(
        ["tectonic", "--outdir", str(output_dir), str(tex_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RenderError(
            f"Tectonic failed to compile {tex_path}:\n{result.stdout}\n{result.stderr}"
        )

    pdf_path = output_dir / f"{output_stem}.pdf"
    if not pdf_path.exists():
        raise RenderError(f"Tectonic reported success but no PDF was produced at {pdf_path}")
    return pdf_path
```

Add `render_cover_letter` at the end of the file:

```python
def render_cover_letter(resume_content: dict, cover_letter: dict, output_dir: Path) -> Path:
    """Render a generated cover letter to PDF using the candidate's contact block."""
    context = {
        "contact": resume_content["contact"],
        "date": datetime.now().strftime("%B %d, %Y"),
        "paragraphs": cover_letter["paragraphs"],
    }
    escaped = _escape_context(context)

    template = LATEX_JINJA_ENV.get_template("cover_letter.tex")
    tex_source = template.render(**escaped)

    output_dir.mkdir(parents=True, exist_ok=True)
    tex_path = output_dir / "cover_letter.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    return _compile_tex(tex_path, output_dir, "cover_letter")
```

- [ ] **Step 4: Create `templates/cover_letter.tex`**

```latex
\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\setlength{\parskip}{1em}

\begin{document}

{\LARGE \VAR{contact.name}} \\
\VAR{contact.email} \textbar{} \VAR{contact.phone} \textbar{} \VAR{contact.location}
\BLOCK{if contact.links}
\\ \BLOCK{for link in contact.links}\VAR{link}\BLOCK{if not loop.last} \textbar{} \BLOCK{endif}\BLOCK{endfor}
\BLOCK{endif}

\VAR{date}

Dear Hiring Manager,

\BLOCK{for paragraph in paragraphs}
\VAR{paragraph}

\BLOCK{endfor}
Sincerely, \\
\VAR{contact.name}

\end{document}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_latex_render.py -v
```

Expected: all tests pass (existing 6 + 1 new = 7 passed). This also re-verifies the refactor didn't break `render_resume`'s existing behavior (the tectonic-failure-patch test, which patches `core.latex_render.subprocess.run`, must still pass since `_compile_tex` lives in the same module).

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
python3 -m pytest -q
```

Expected: all tests pass (35 passed: 28 original + 2 from Task 1 + 4 from Task 2 + 1 from this task).

- [ ] **Step 7: Commit**

```bash
git add core/latex_render.py templates/cover_letter.tex tests/test_latex_render.py
git commit -m "feat: cover letter PDF rendering; expose merge_resume publicly"
```

---

### Task 4: Wire the choice-driven flow into app.py

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `core.tailor.passthrough_tailored_content` (Task 1), `core.cover_letter.generate_cover_letter` (Task 2), `core.latex_render.merge_resume` and `core.latex_render.render_cover_letter` (Task 3), plus everything already imported in `app.py` (`extract_keywords`, `tailor_resume`, `render_resume`, `RenderError`, `lint_resume_content`, `log_usage`).
- Produces: the restructured `tailoring_flow` function and three new helpers (`_run_tailor_action`, `_run_use_original_action`, `_run_cover_letter_action`) — no other file depends on these, they're `app.py`-internal.

- [ ] **Step 1: Update imports at the top of `app.py`**

Change:

```python
from core.banned_phrases import lint_resume_content
from core.keyword_analysis import extract_keywords
from core.latex_render import RenderError, render_resume
from core.resume_store import DATA_DIR, OUTPUT_DIR, load_master_resume, save_gap_analysis, save_master_resume
from core.tailor import tailor_resume
from core.usage_tracker import get_cost_summary, log_usage
```

to:

```python
from core.banned_phrases import find_banned_phrases, lint_resume_content
from core.cover_letter import generate_cover_letter
from core.keyword_analysis import extract_keywords
from core.latex_render import RenderError, merge_resume, render_cover_letter, render_resume
from core.resume_store import DATA_DIR, OUTPUT_DIR, load_master_resume, save_gap_analysis, save_master_resume
from core.tailor import passthrough_tailored_content, tailor_resume
from core.usage_tracker import get_cost_summary, log_usage
```

- [ ] **Step 2: Replace `tailoring_flow` and add the three action helpers**

Replace the entire existing `tailoring_flow` function (currently `app.py` lines 65-144, from `def tailoring_flow(master_resume: dict):` down to the line before `def main():`) with:

```python
def _run_tailor_action(client, master_resume: dict, gap_analysis: dict, run_dir):
    model = st.session_state["model"]
    job_description = st.session_state["job_description"]

    with st.spinner("Tailoring your resume..."):
        try:
            tailored_content, tailor_usages = tailor_resume(
                client, master_resume, job_description, gap_analysis, model=model
            )
        except Exception as e:
            st.error(f"Resume tailoring failed:\n\n{e}")
            return
        for usage in tailor_usages:
            log_usage(
                "tailor", model, usage.input_tokens, usage.output_tokens, USAGE_LOG_PATH,
                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens,
            )

    violations = lint_resume_content(tailored_content)
    if violations:
        st.warning(f"Banned phrases survived the self-critique pass: {violations}")

    with st.spinner("Rendering PDF..."):
        try:
            pdf_path, unmatched_entries = render_resume(master_resume, tailored_content, run_dir)
        except RenderError as e:
            st.error(f"PDF rendering failed:\n\n{e}")
            return

    if unmatched_entries:
        st.warning(
            "Tailoring was silently dropped for these entries (no matching "
            "company/name in the model's response, so the original bullets "
            f"were used instead): {', '.join(unmatched_entries)}"
        )

    save_gap_analysis(run_dir, gap_analysis)
    st.session_state["tailored_content"] = tailored_content
    st.session_state["resume_pdf_path"] = pdf_path

    with st.spinner("Checking new keyword match..."):
        try:
            merged_resume = merge_resume(master_resume, tailored_content)
            new_resume_text = resume_to_text(merged_resume)
            new_gap_analysis, kw_usage = extract_keywords(client, job_description, new_resume_text)
        except Exception as e:
            st.error(f"Match recheck failed:\n\n{e}")
            return
        log_usage(
            "keyword_analysis_recheck", "claude-haiku-4-5",
            kw_usage.input_tokens, kw_usage.output_tokens, USAGE_LOG_PATH,
            cache_creation_input_tokens=kw_usage.cache_creation_input_tokens,
            cache_read_input_tokens=kw_usage.cache_read_input_tokens,
        )
    st.session_state["new_gap_analysis"] = new_gap_analysis


def _run_use_original_action(master_resume: dict, run_dir):
    passthrough = passthrough_tailored_content(master_resume)
    with st.spinner("Rendering PDF..."):
        try:
            pdf_path, _ = render_resume(master_resume, passthrough, run_dir)
        except RenderError as e:
            st.error(f"PDF rendering failed:\n\n{e}")
            return
    st.session_state["tailored_content"] = None
    st.session_state["resume_pdf_path"] = pdf_path
    st.session_state.pop("new_gap_analysis", None)


def _run_cover_letter_action(client, master_resume: dict, run_dir):
    model = st.session_state["model"]
    job_description = st.session_state["job_description"]
    company = st.session_state["company"]
    tailored_content = st.session_state.get("tailored_content")
    resume_content = merge_resume(master_resume, tailored_content) if tailored_content else master_resume

    with st.spinner("Writing your cover letter..."):
        try:
            cover_letter, cl_usages = generate_cover_letter(
                client, resume_content, job_description, company, model=model
            )
        except Exception as e:
            st.error(f"Cover letter generation failed:\n\n{e}")
            return
        for usage in cl_usages:
            log_usage(
                "cover_letter", model, usage.input_tokens, usage.output_tokens, USAGE_LOG_PATH,
                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens,
            )

    violations = find_banned_phrases(" ".join(cover_letter["paragraphs"]))
    if violations:
        st.warning(f"Banned phrases survived the self-critique pass: {violations}")

    with st.spinner("Rendering cover letter PDF..."):
        try:
            pdf_path = render_cover_letter(resume_content, cover_letter, run_dir)
        except RenderError as e:
            st.error(f"Cover letter rendering failed:\n\n{e}")
            return

    st.session_state["cover_letter_pdf_path"] = pdf_path


def tailoring_flow(master_resume: dict):
    st.header("Tailor a resume")
    job_description = st.text_area("Paste the job description", height=300)
    company = st.text_input("Company name (for the archive folder)")
    model = st.selectbox("Model", ["claude-sonnet-5", "claude-opus-4-8"], index=0)

    if st.button("Analyze job description"):
        if len(job_description.strip()) < 100:
            st.error("That job description looks too short — paste the full posting.")
            return
        if not company.strip():
            st.error("Enter a company name so the output can be archived.")
            return

        client = get_client()
        resume_text = resume_to_text(master_resume)

        with st.spinner("Extracting keywords from the job description..."):
            try:
                gap_analysis, kw_usage = extract_keywords(client, job_description, resume_text)
            except Exception as e:
                st.error(f"Keyword extraction failed:\n\n{e}")
                return
            log_usage(
                "keyword_analysis", "claude-haiku-4-5",
                kw_usage.input_tokens, kw_usage.output_tokens, USAGE_LOG_PATH,
                cache_creation_input_tokens=kw_usage.cache_creation_input_tokens,
                cache_read_input_tokens=kw_usage.cache_read_input_tokens,
            )

        date_str = datetime.now().strftime("%Y-%m-%d")
        st.session_state["job_description"] = job_description
        st.session_state["company"] = company
        st.session_state["model"] = model
        st.session_state["gap_analysis"] = gap_analysis
        st.session_state["run_dir"] = OUTPUT_DIR / f"{company.strip().replace(' ', '_')}_{date_str}"
        # A new analysis invalidates any prior tailoring/cover-letter results.
        st.session_state.pop("tailored_content", None)
        st.session_state.pop("new_gap_analysis", None)
        st.session_state.pop("resume_pdf_path", None)
        st.session_state.pop("cover_letter_pdf_path", None)

    if "gap_analysis" not in st.session_state:
        return

    gap_analysis = st.session_state["gap_analysis"]
    run_dir = st.session_state["run_dir"]

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Matched keywords")
        st.write(", ".join(gap_analysis["matched"]) or "None found")
    with col2:
        st.subheader("Missing keywords")
        st.write(", ".join(gap_analysis["missing"]) or "None found")
    st.metric("Match score", f"{gap_analysis['match_percentage']}%")

    action_col1, action_col2, action_col3 = st.columns(3)
    tailor_clicked = action_col1.button("Tailor resume")
    use_original_clicked = action_col2.button("Use original resume as-is")
    cover_letter_clicked = action_col3.button("Generate cover letter")

    client = get_client()

    if tailor_clicked:
        _run_tailor_action(client, master_resume, gap_analysis, run_dir)

    if use_original_clicked:
        _run_use_original_action(master_resume, run_dir)

    if cover_letter_clicked:
        _run_cover_letter_action(client, master_resume, run_dir)

    if "new_gap_analysis" in st.session_state:
        old_pct = gap_analysis["match_percentage"]
        new_pct = st.session_state["new_gap_analysis"]["match_percentage"]
        st.metric("Match score after tailoring", f"{new_pct}%", f"{new_pct - old_pct:+d}%")

    if "resume_pdf_path" in st.session_state:
        st.success("Resume ready.")
        with open(st.session_state["resume_pdf_path"], "rb") as f:
            st.download_button(
                "Download resume PDF", f,
                file_name=f"resume_{st.session_state['company'].strip()}.pdf",
                key="download_resume",
            )

    if "cover_letter_pdf_path" in st.session_state:
        st.success("Cover letter ready.")
        with open(st.session_state["cover_letter_pdf_path"], "rb") as f:
            st.download_button(
                "Download cover letter PDF", f,
                file_name=f"cover_letter_{st.session_state['company'].strip()}.pdf",
                key="download_cover_letter",
            )
```

Note: `main()` below this (calling `tailoring_flow(master_resume)` and the "Replace master resume" checkbox) does not need to change.

- [ ] **Step 3: Run the full automated test suite**

```bash
python3 -m pytest -q
```

Expected: no failures (app.py has no dedicated pytest file — this just confirms the import changes didn't break any core module test collection).

- [ ] **Step 4: Manually verify the flow in the browser**

```bash
streamlit run app.py
```

With a master resume already saved (skip if `data/master_resume.json` already exists), exercise each path in the browser:

1. Paste a real job description (100+ chars) and a company name, click **"Analyze job description"** — confirm matched/missing keywords and a match score appear.
2. Click **"Use original resume as-is"** — confirm a PDF downloads with no Claude spinner for tailoring, and it matches the master resume verbatim.
3. Click **"Analyze job description"** again (fresh run), then click **"Tailor resume"** — confirm the resume PDF renders, and a second metric **"Match score after tailoring"** appears showing the delta (e.g. "81%  +19%").
4. On that same analysis, click **"Generate cover letter"** — confirm a cover letter PDF downloads, open it and check the layout (contact header, date, greeting, body paragraphs, sign-off) renders cleanly with no LaTeX escaping artifacts.
5. Check `data/usage_log.jsonl` — confirm new entries exist with `call_type` values `keyword_analysis_recheck` and `cover_letter`.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: choice-driven tailor flow with match recompute and cover letter"
```

---

### Task 5: Integration test coverage for the new paths

**Files:**
- Modify: `tests/test_integration_pipeline.py`

**Interfaces:**
- Consumes: `core.tailor.passthrough_tailored_content` (Task 1), `core.cover_letter.generate_cover_letter` (Task 2), `core.latex_render.merge_resume` and `render_cover_letter` (Task 3).
- Produces: two new test functions; no new production code.

- [ ] **Step 1: Write the two new tests**

Update the import block at the top of `tests/test_integration_pipeline.py` from:

```python
from core.banned_phrases import lint_resume_content
from core.keyword_analysis import extract_keywords
from core.latex_render import render_resume
from core.tailor import tailor_resume
```

to:

```python
from core.banned_phrases import lint_resume_content
from core.cover_letter import generate_cover_letter
from core.keyword_analysis import extract_keywords
from core.latex_render import merge_resume, render_cover_letter, render_resume
from core.tailor import passthrough_tailored_content, tailor_resume
```

Then add these two test functions at the end of the file:

```python
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
```

- [ ] **Step 2: Run the new tests to verify they pass**

```bash
python3 -m pytest tests/test_integration_pipeline.py -v
```

Expected: 3 passed (1 existing + 2 new).

- [ ] **Step 3: Run the full test suite**

```bash
python3 -m pytest -q
```

Expected: all tests pass (28 original + 2 Task 1 + 4 Task 2 + 1 Task 3 + 2 this task = 37 passed).

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_pipeline.py
git commit -m "test: end-to-end coverage for use-original path, match recheck, and cover letter"
```
