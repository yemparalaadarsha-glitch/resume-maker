import json
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"


def load_master_resume(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_master_resume(resume: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(resume, indent=2), encoding="utf-8")


def save_gap_analysis(run_dir: Path, gap_analysis: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "gap_analysis.json"
    path.write_text(json.dumps(gap_analysis, indent=2), encoding="utf-8")
    return path
