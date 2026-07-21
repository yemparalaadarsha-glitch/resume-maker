# Design: Tailor/Skip Choice, Post-Tailor Match %, and Cover Letter Generation

## Context

The current app (`app.py::tailoring_flow`) does keyword extraction, resume tailoring, and PDF rendering in one linear pass triggered by a single "Generate tailored resume" button. This adds three capabilities on top of the merged Task 1-9 pipeline:

1. After keywords are shown, let the user choose whether to tailor the resume at all (vs. just getting the original resume as a PDF).
2. After tailoring, show how much the match percentage improved.
3. Let the user generate a cover letter alongside the resume.

## Flow

1. User pastes job description + company name, clicks **"Analyze job description"**.
   - Runs `extract_keywords` (Haiku) against the master resume text.
   - Displays matched/missing keywords and match percentage.
   - Stores `job_description`, `company`, `gap_analysis` in `st.session_state`.
   - Starting a new analysis (re-clicking with a changed JD) resets any prior tailored/cover-letter state.
2. Three independent actions become available once analysis exists, in any order:
   - **"Tailor resume"** — runs the existing two-pass `tailor_resume` (draft + critique), lints banned phrases, renders the merged resume to PDF via `render_resume`. Then re-runs `extract_keywords` against the *tailored* resume text to get a new `gap_analysis`, and displays old% → new% (e.g. "62% → 81%"). Stores `tailored_content` and `new_gap_analysis` in session_state.
   - **"Use original resume as-is"** — no Claude call. Builds a pass-through `tailored_content` shape from the master resume unchanged (same company/name keys so `render_resume`'s merge is a no-op) and renders directly to PDF. Does not touch match percentage.
   - **"Generate cover letter"** — runs the new two-pass `generate_cover_letter` using `tailored_content` if it already exists in session_state, otherwise the master resume. Renders via a new LaTeX template into the same run's archive folder as the resume.
3. All PDFs (resume + cover letter, when generated) are offered as downloads and saved under `output/{Company}_{date}/`.

## Components

### `core/cover_letter.py` (new)

Mirrors the shape of `core/tailor.py`:

- `COVER_LETTER_SCHEMA`: JSON schema for `{"paragraphs": ["string", ...]}` (3-5 paragraphs: opening/hook, why-this-role fit grounded in resume facts, closing).
- `DRAFT_SYSTEM_PROMPT`: instructs the model to write a professional cover letter addressing the job description, grounding every claim in the given resume content (master or tailored), matching the candidate's voice, avoiding the same banned-phrase list as resume tailoring, and never fabricating facts not present in the source resume.
- `CRITIQUE_SYSTEM_PROMPT`: same anti-fabrication + banned-phrase re-check pattern as `tailor.py`'s critique pass, applied to the draft cover letter.
- `generate_cover_letter(client, resume_content: dict, job_description: str, company: str, model: str) -> tuple[dict, list[Usage]]`: runs draft then critique, returns final `{"paragraphs": [...]}` plus both calls' usage objects (for cost logging, consistent with `tailor_resume`'s return shape).
- Reuses `find_banned_phrases` from `core/banned_phrases.py` directly on the joined paragraph text (no need for a new lint function — the existing one is generic enough).

### `templates/cover_letter.tex` (new)

- Contact header identical in style to `resume.tex` (`contact.name`, `contact.email`, `contact.phone`, `contact.location`, `contact.links`).
- Today's date (passed in from `app.py`, not the model).
- `Dear Hiring Manager,` salutation (no per-company hiring-manager name available in the schema — kept generic).
- One paragraph per entry in `paragraphs`.
- Sign-off: `Sincerely,` + `contact.name`.

### `core/latex_render.py`

- Factor the existing tectonic subprocess-compile + error-handling block out of `render_resume` into a shared helper: `_compile_tex(tex_path: Path, output_dir: Path, output_stem: str) -> Path`, raising `RenderError` on non-zero exit or missing output PDF. `render_resume` calls this after writing `resume.tex`.
- Add `render_cover_letter(resume_content: dict, cover_letter: dict, company: str, output_dir: Path) -> Path`: builds the escaped template context (contact block + today's date + escaped paragraphs), writes `cover_letter.tex`, calls `_compile_tex`, returns the PDF path.

### `app.py`

- Restructure `tailoring_flow` around `st.session_state` keys: `gap_analysis`, `job_description`, `company`, `run_dir`, `tailored_content`, `new_gap_analysis`, `cover_letter_content`.
- "Analyze job description" button populates the initial state (and clears the tailored/cover-letter keys if present from a prior run).
- "Tailor resume", "Use original resume as-is", and "Generate cover letter" become independently clickable buttons/sections, each reading from and writing to session_state, each wrapped in its own try/except following the existing `st.error(...)` pattern so a failure in one action doesn't discard state from another already-completed action.
- Match percentage delta shown via `st.metric("Match score", f"{new}%", f"{new - old:+d}%")` (Streamlit's built-in delta rendering) once `new_gap_analysis` exists.

## Error Handling

Follows the app's existing pattern exactly: every Claude API call and `RenderError` is wrapped in try/except, surfaced via `st.error(...)`, and returns early — extended to the new cover-letter call and the post-tailor recompute call. Because each of the three actions (tailor / use-original / cover-letter) only reads/writes its own session_state keys, a failure in "Generate cover letter" (for example) can't corrupt or discard an already-rendered tailored resume.

## Testing

- `tests/test_cover_letter.py` (new): unit tests for `generate_cover_letter` with a mocked Claude client — verifies the two-pass call sequence (draft then critique), the returned shape, and that banned phrases surviving critique are still caught by `find_banned_phrases`. Mirrors `tests/test_tailor.py`'s structure.
- `tests/test_latex_render.py` (extend): add a test for `render_cover_letter` that does a real `tectonic` compile (matching the existing real-compile test for `render_resume`) and asserts a PDF is produced.
- `tests/test_integration_pipeline.py` (extend): extend the existing end-to-end smoke test to also exercise the "use original resume" path (no Claude tailoring call) and cover letter generation, and to assert the post-tailor recompute produces a `new_gap_analysis` with a `match_percentage`.

## Out of Scope

- Hiring-manager name / employer address fields (schema has none; salutation stays generic "Dear Hiring Manager,").
- Editing generated cover letter text in the UI before rendering (one-shot generation, consistent with current resume tailoring UX).
- Multi-page Streamlit navigation — everything stays on the single existing page, gated by session_state.
