import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from pypdf import PdfReader

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"

# The resume must read as one deliberately-sized document, not a partially
# filled trailing page. Anything over the page cap is trimmed automatically;
# these floors keep every entry recognizable even after trimming.
MAX_PDF_PAGES = 2
MIN_EXPERIENCE_BULLETS = 2
MIN_PROJECT_BULLETS = 1

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


def count_pdf_pages(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def _escape_context(value):
    if isinstance(value, str):
        return escape_latex(value)
    if isinstance(value, list):
        return [_escape_context(v) for v in value]
    if isinstance(value, dict):
        return {k: _escape_context(v) for k, v in value.items()}
    return value


def find_unmatched_entries(master_resume: dict, tailored_content: dict) -> list[str]:
    """Return labels for master experience/project entries with no tailored match.

    `_merge_resume` keys tailored experience by exact `company` string and
    tailored projects by exact `name` string, falling back to the master
    resume's original bullets when no match is found. That fallback is
    silent by construction, so this function exists to make the mismatch
    visible to callers (e.g. so `app.py` can show a warning) instead of the
    tailoring being discarded with zero indication.
    """
    tailored_companies = {e["company"] for e in tailored_content.get("experience", [])}
    tailored_names = {p["name"] for p in tailored_content.get("projects", [])}

    unmatched = []
    for job in master_resume.get("experience", []):
        if job["company"] not in tailored_companies:
            unmatched.append(f"experience: {job['company']}")
    for project in master_resume.get("projects", []):
        if project["name"] not in tailored_names:
            unmatched.append(f"project: {project['name']}")
    return unmatched


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
        "certifications": master_resume.get("certifications", []),
    }


def _compile_pdf(merged: dict, output_dir: Path) -> Path:
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


def _build_removal_ops(merged: dict) -> list[tuple[str, int]]:
    """Flat, priority-ordered list of "(kind, index)" bullet-removal steps.

    Applying the first N ops removes N bullets total, always from the
    lowest-priority entry with bullets still above its floor. Priority order:
    least-important project first (last-listed = lowest), fully drained to
    its floor before moving to the next, then the same for experience
    entries oldest-first (last-listed = oldest, by resume convention).
    """
    ops: list[tuple[str, int]] = []
    for i in reversed(range(len(merged["projects"]))):
        above_floor = len(merged["projects"][i]["bullets"]) - MIN_PROJECT_BULLETS
        ops.extend([("project", i)] * max(above_floor, 0))
    for i in reversed(range(len(merged["experience"]))):
        above_floor = len(merged["experience"][i]["bullets"]) - MIN_EXPERIENCE_BULLETS
        ops.extend([("experience", i)] * max(above_floor, 0))
    return ops


def _apply_removals(merged: dict, removal_ops: list[tuple[str, int]], n: int) -> dict:
    """Copy of `merged` with the first n removal ops applied (bullets popped from the end)."""
    copy = {
        **merged,
        "experience": [{**e, "bullets": list(e["bullets"])} for e in merged["experience"]],
        "projects": [{**p, "bullets": list(p["bullets"])} for p in merged["projects"]],
    }
    for kind, idx in removal_ops[:n]:
        entries = copy["projects"] if kind == "project" else copy["experience"]
        entries[idx]["bullets"].pop()
    return copy


def _trim_label(merged: dict, kind: str, idx: int) -> str:
    entries = merged["projects"] if kind == "project" else merged["experience"]
    entry = entries[idx]
    return f"{kind}: {entry.get('name') or entry.get('company')}"


def _fit_to_page_limit(merged: dict, output_dir: Path) -> tuple[Path, list[str]]:
    """Render `merged`, trimming lowest-priority bullets until it fits MAX_PDF_PAGES.

    Uses a binary search over "how many bullets to remove" (in the fixed
    priority order from `_build_removal_ops`) rather than removing one bullet
    per render — O(log N) Tectonic compiles instead of O(N). Page count is
    assumed non-increasing as more bullets are removed, which holds for this
    single-column template. If even trimming every entry down to its floor
    still doesn't fit, the floor-trimmed version is used as a best effort.
    """
    pdf_path = _compile_pdf(merged, output_dir)
    if count_pdf_pages(pdf_path) <= MAX_PDF_PAGES:
        return pdf_path, []

    removal_ops = _build_removal_ops(merged)
    if not removal_ops:
        return pdf_path, []

    lo, hi = 1, len(removal_ops)
    while lo < hi:
        mid = (lo + hi) // 2
        candidate_pdf = _compile_pdf(_apply_removals(merged, removal_ops, mid), output_dir)
        if count_pdf_pages(candidate_pdf) <= MAX_PDF_PAGES:
            hi = mid
        else:
            lo = mid + 1

    final_pdf_path = _compile_pdf(_apply_removals(merged, removal_ops, lo), output_dir)
    trimmed_labels = sorted({_trim_label(merged, kind, idx) for kind, idx in removal_ops[:lo]})
    return final_pdf_path, trimmed_labels


def render_resume(master_resume: dict, tailored_content: dict, output_dir: Path) -> tuple[Path, list[str], list[str]]:
    """Render the tailored resume to PDF, auto-fit to MAX_PDF_PAGES.

    Returns (pdf_path, unmatched_entries, trimmed_entries):
    - unmatched_entries: master experience/project entries whose tailored
      counterpart could not be matched by exact `company`/`name`, so the
      original untailored bullets were used. Callers should surface a
      warning when this is non-empty.
    - trimmed_entries: entries that had bullets automatically dropped to fit
      the resume within MAX_PDF_PAGES pages. Callers should surface an info
      message when this is non-empty.
    """
    unmatched_entries = find_unmatched_entries(master_resume, tailored_content)
    merged = _merge_resume(master_resume, tailored_content)
    pdf_path, trimmed_entries = _fit_to_page_limit(merged, output_dir)
    return pdf_path, unmatched_entries, trimmed_entries
