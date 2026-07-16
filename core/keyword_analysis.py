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
