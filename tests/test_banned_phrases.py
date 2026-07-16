from core.banned_phrases import find_banned_phrases, lint_resume_content


def test_find_banned_phrases_detects_known_phrase():
    result = find_banned_phrases("I spearheaded the migration project.")
    assert "spearheaded" in result


def test_find_banned_phrases_is_case_insensitive():
    result = find_banned_phrases("I LEVERAGED my skills to deliver results.")
    assert "leveraged" in result


def test_find_banned_phrases_returns_empty_for_clean_text():
    result = find_banned_phrases("Cut database query time from 800ms to 120ms.")
    assert result == []


def test_lint_resume_content_flags_summary_and_bullets():
    tailored_content = {
        "summary": "A passionate engineer who leveraged modern tools.",
        "experience": [
            {"company": "Acme", "bullets": ["Spearheaded the rollout.", "Wrote clean code."]}
        ],
        "projects": [
            {"name": "queue-bench", "bullets": ["Built a benchmarking tool."]}
        ],
    }
    violations = lint_resume_content(tailored_content)
    assert "summary" in violations
    assert "Acme bullet 1" in violations
    assert "Acme bullet 2" not in violations
    assert not any(key.startswith("queue-bench") for key in violations)
