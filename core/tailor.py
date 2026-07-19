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
