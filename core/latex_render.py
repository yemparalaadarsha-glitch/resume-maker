import subprocess
from datetime import datetime
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


def find_unmatched_entries(master_resume: dict, tailored_content: dict) -> list[str]:
    """Return labels for master experience/project entries with no tailored match.

    `merge_resume` keys tailored experience by exact `company` string and
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


def merge_resume(master_resume: dict, tailored_content: dict) -> dict:
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
