from datetime import datetime

import anthropic
import streamlit as st
from dotenv import load_dotenv

from core.banned_phrases import find_banned_phrases, lint_resume_content
from core.cover_letter import generate_cover_letter
from core.keyword_analysis import extract_keywords
from core.latex_render import RenderError, merge_resume, render_cover_letter, render_resume
from core.resume_store import DATA_DIR, OUTPUT_DIR, load_master_resume, save_gap_analysis, save_master_resume
from core.tailor import passthrough_tailored_content, tailor_resume
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
    st.session_state.pop("cover_letter_pdf_path", None)

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
    st.session_state.pop("cover_letter_pdf_path", None)


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
