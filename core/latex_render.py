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
