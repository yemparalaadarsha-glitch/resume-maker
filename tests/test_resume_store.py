import json

from core.resume_store import load_master_resume, save_gap_analysis, save_master_resume


def test_load_master_resume_returns_none_when_file_missing(tmp_path):
    missing_path = tmp_path / "master_resume.json"
    assert load_master_resume(missing_path) is None


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "nested" / "master_resume.json"
    resume = {"summary": "Test resume", "experience": [], "skills": ["Python"]}

    save_master_resume(resume, path)
    loaded = load_master_resume(path)

    assert loaded == resume


def test_save_gap_analysis_writes_json_file(tmp_path):
    run_dir = tmp_path / "Acme_2026-07-15"
    gap_analysis = {"keywords": ["Python"], "matched": ["Python"], "missing": [], "match_percentage": 100}

    result_path = save_gap_analysis(run_dir, gap_analysis)

    assert result_path == run_dir / "gap_analysis.json"
    assert json.loads(result_path.read_text()) == gap_analysis
