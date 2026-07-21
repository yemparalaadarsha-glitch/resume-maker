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
