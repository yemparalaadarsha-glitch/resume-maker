BANNED_PHRASES = [
    "spearheaded",
    "leveraged",
    "results-driven",
    "utilized",
    "dynamic",
    "passionate",
    "synergy",
    "cutting-edge",
]


def find_banned_phrases(text: str) -> list[str]:
    lowered = text.lower()
    return [phrase for phrase in BANNED_PHRASES if phrase in lowered]


def lint_resume_content(tailored_content: dict) -> dict[str, list[str]]:
    """Scan every text field of a tailored-resume dict for banned phrases.

    Returns a mapping of location label -> list of phrases found there.
    Empty dict means clean.
    """
    violations: dict[str, list[str]] = {}

    summary_hits = find_banned_phrases(tailored_content.get("summary", ""))
    if summary_hits:
        violations["summary"] = summary_hits

    for job in tailored_content.get("experience", []):
        for i, bullet in enumerate(job.get("bullets", [])):
            hits = find_banned_phrases(bullet)
            if hits:
                violations[f"{job['company']} bullet {i + 1}"] = hits

    for project in tailored_content.get("projects", []):
        for i, bullet in enumerate(project.get("bullets", [])):
            hits = find_banned_phrases(bullet)
            if hits:
                violations[f"{project['name']} bullet {i + 1}"] = hits

    return violations
