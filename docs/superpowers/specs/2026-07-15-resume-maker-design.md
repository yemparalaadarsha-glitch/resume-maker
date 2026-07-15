# Resume Maker — Design

**Date:** 2026-07-15
**Status:** Approved for planning

## Purpose

A standalone, local tool for one person's own job search. Paste a job description, get back a resume tailored to that JD from a single "master resume" source of truth — ATS-safe, honestly grounded in the user's real experience, and written in prose that reads as human, not AI-generated boilerplate. Not a product, not multi-user, not hosted (initially).

## Non-goals

- Not a multi-user SaaS product. No auth, no accounts, no billing.
- Not pixel-perfect design customization — one solid ATS-safe template, not a template gallery.
- Not a job-board scraper or application tracker beyond a simple local archive of what was generated.

## Architecture

Streamlit app (`app.py`) as a thin UI layer only. All real logic lives in plain Python modules under `core/` that never import `streamlit`, so the hard part (prompting, keyword analysis, LaTeX rendering, cost tracking) stays portable if the UI is ever rebuilt in another framework later.

```
resume-maker/
  app.py                    # UI only: forms, buttons, results display, sidebar cost widget
  core/
    resume_store.py         # load/save master resume, archive past runs
    keyword_analysis.py     # Claude call (Haiku 4.5): extract JD keywords, compute match/gap
    tailor.py                # Claude calls (Sonnet 5): tailor pass + self-critique pass
    banned_phrases.py       # AI-tell phrase list + linter
    latex_render.py         # inject data into .tex, escape special chars, run Tectonic
    usage_tracker.py        # log each call's token usage + estimated cost
  templates/
    resume.tex               # single-column, ATS-safe LaTeX template
  data/
    master_resume.json      # the one stored source-of-truth resume
    usage_log.jsonl          # append-only log of API usage/cost per call
  output/
    <company>_<date>/       # archived .tex + .pdf + gap_analysis.json per application
```

## Components

**`resume_store.py`** — Loads/saves `data/master_resume.json` (contact info, summary, skills, experience entries with bullets, projects, education). Archives each generated application under `output/<company>_<date>/`.

**`keyword_analysis.py`** — One Claude call (Haiku 4.5 — cheap, the task is plain extraction) that pulls ~15–25 keywords/skills/tools out of the pasted JD and diffs them against the master resume, returning matched vs. missing terms plus a rough match percentage.

**`tailor.py`** — Two Claude calls on Sonnet 5 (near-Opus quality on writing/reasoning at a third of the cost — this is where quality actually matters):
1. **Tailor pass** — rewrites/selects bullets grounded only in the master resume, weaving in truthful keyword overlaps from the gap analysis. Uses the user's existing bullets as a voice reference (few-shot in the prompt) but is allowed to sharpen phrasing, verbs, and sentence structure where it's a genuine improvement — never allowed to invent facts.
2. **Self-critique pass** — re-reads the draft against the master resume and strips anything not traceable to a real fact, and against `banned_phrases.py`'s list strips AI-tell language ("spearheaded," "leveraged," "results-driven," etc.).

A config flag allows swapping either call to Opus 4.8 for a specific high-stakes application without any code change.

**`banned_phrases.py`** — Static list of AI-cliché words/phrases plus a regex linter function, used by the self-critique step and as a final safety net before LaTeX rendering.

**`latex_render.py`** — Escapes LaTeX special characters (`& % $ # _ { } ~ ^ \`) in all generated/user text, injects it into `templates/resume.tex` via string templating, shells out to Tectonic to compile a PDF. Surfaces the raw Tectonic log on compile failure instead of failing silently.

**`usage_tracker.py`** — After every Claude API call, reads `response.usage` (input/output/cache-read/cache-write tokens) and appends a line to `data/usage_log.jsonl` with the call type, tokens, and an estimated cost computed from a hardcoded per-model price table. The Streamlit sidebar reads this log to show "Today: $X.XX (N applications) · This month: $Y.YY". This is a local estimate for the daily workflow — the Anthropic Console's Usage tab remains the authoritative billing record.

## Data flow

1. **First run only** — paste/upload the resume once → parsed into structured JSON → saved to `data/master_resume.json`.
2. **Per application** — paste a JD → `keyword_analysis.py` (Haiku 4.5) extracts keywords and computes the gap → shown in the UI as matched vs. missing terms with a rough match %.
3. `tailor.py` runs the tailor pass then the self-critique pass (Sonnet 5), producing final tailored content grounded in the master resume.
4. `latex_render.py` escapes and injects the content into the LaTeX template, compiles via Tectonic.
5. Result: PDF for download, archived under `output/<company>_<date>/` alongside the `.tex` and the gap-analysis JSON, for the user's own record of what was submitted where.
6. Every Claude call along the way logs its usage; the sidebar cost widget updates live.

## Guardrails

- **Anti-fabrication, enforced twice** — once as an explicit instruction in the tailor-pass prompt, once as an active removal step in the self-critique pass (never trust the first pass alone to have complied).
- **LaTeX injection escaping** — a dedicated, unit-tested escape function; this is the most common way this class of tool breaks in practice.
- **Tectonic compile failures** surface the raw compiler log in an expandable UI section rather than failing silently.
- **JD sanity check** — a cheap length/garbage check on the pasted JD before spending an API call on it.

## Cost design

Mixed-model pipeline to control cost without sacrificing quality where it matters:
- Haiku 4.5 for keyword extraction (trivial task, ~$1/$5 per MTok).
- Sonnet 5 for the tailor and self-critique passes (~$2/$10 per MTok on current intro pricing through 2026-08-31; the writing-quality work).
- Opus 4.8 available as a per-run override, not the default.
- **Prompt caching** on the master-resume portion of the tailor/self-critique prompts — it's identical across every application in a session, so repeated same-day applications pay the ~10%-of-normal cached-read rate on that chunk instead of full price.

At 5–10 applications/day this lands at roughly $5–$11/month on Sonnet 5, well under any level that needs active management — the usage tracker is for visibility, not budget alarm.

## Testing

- Pytest unit tests: LaTeX escaper (all special characters + edge cases), banned-phrase linter (known-bad examples), master-resume JSON round-trip (load → save → load).
- One integration smoke test: fixture master resume + fixture JD → mocked Claude responses → full pipeline → verify a PDF actually compiles without error.
- No automated UI testing — this is a single-user personal tool; manual click-through is sufficient for the Streamlit layer.

## Future: hosting

Not part of this build, but the design doesn't block it: Streamlit apps deploy to Streamlit Community Cloud, or as a Docker container to Fly.io/Railway/a private VPS. Moving there later means relocating the Claude API key to the host's secrets manager and ensuring Tectonic is present in the container — no architecture change. If a future move to Next.js is ever wanted, the `core/` modules (prompts, LaTeX template, API calls) port with only mechanical translation to TypeScript since they never depend on Streamlit; only the UI layer would be rebuilt from scratch.
