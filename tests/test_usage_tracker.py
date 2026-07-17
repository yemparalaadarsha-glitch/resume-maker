import json
from datetime import datetime, timedelta, timezone

from core.usage_tracker import estimate_cost, get_cost_summary, log_usage


def test_estimate_cost_computes_correct_value_for_known_model():
    cost = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 12.00  # $2 input + $10 output per Sonnet 5 intro pricing


def test_estimate_cost_returns_zero_for_unknown_model():
    assert estimate_cost("some-future-model", input_tokens=1000, output_tokens=1000) == 0.0


def test_estimate_cost_discounts_cache_reads():
    full_price = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
    cached = estimate_cost(
        "claude-sonnet-5", input_tokens=0, output_tokens=0, cache_read_input_tokens=1_000_000
    )
    assert round(cached, 6) == round(full_price * 0.1, 6)


def test_estimate_cost_surcharges_cache_writes():
    full_price = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
    written = estimate_cost(
        "claude-sonnet-5", input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000
    )
    assert round(written, 6) == round(full_price * 1.25, 6)


def test_log_usage_appends_jsonl_entry(tmp_path):
    log_path = tmp_path / "usage_log.jsonl"

    log_usage("keyword_analysis", "claude-haiku-4-5", 1000, 200, log_path)

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["call_type"] == "keyword_analysis"
    assert entry["model"] == "claude-haiku-4-5"
    assert entry["input_tokens"] == 1000
    assert entry["output_tokens"] == 200
    assert entry["cache_creation_input_tokens"] == 0
    assert entry["cache_read_input_tokens"] == 0
    assert entry["cost"] > 0


def test_log_usage_records_cache_tokens_when_provided(tmp_path):
    log_path = tmp_path / "usage_log.jsonl"

    log_usage(
        "tailor", "claude-sonnet-5", 500, 300, log_path,
        cache_creation_input_tokens=1200, cache_read_input_tokens=0,
    )

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["cache_creation_input_tokens"] == 1200
    assert entry["cost"] > estimate_cost("claude-sonnet-5", 500, 300)


def test_get_cost_summary_sums_todays_and_months_entries(tmp_path):
    log_path = tmp_path / "usage_log.jsonl"
    now = datetime.now(timezone.utc)
    last_month = now.replace(day=1) - timedelta(days=1)

    entries = [
        {"timestamp": now.isoformat(), "call_type": "tailor", "model": "claude-sonnet-5",
         "input_tokens": 1000, "output_tokens": 500, "cost": 0.01},
        {"timestamp": now.isoformat(), "call_type": "tailor", "model": "claude-sonnet-5",
         "input_tokens": 1000, "output_tokens": 500, "cost": 0.02},
        {"timestamp": last_month.isoformat(), "call_type": "tailor", "model": "claude-sonnet-5",
         "input_tokens": 1000, "output_tokens": 500, "cost": 5.00},
    ]
    with log_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    summary = get_cost_summary(log_path)

    assert round(summary["today_cost"], 2) == 0.03
    assert round(summary["month_cost"], 2) == 0.03


def test_get_cost_summary_returns_zeros_when_log_missing(tmp_path):
    summary = get_cost_summary(tmp_path / "does_not_exist.jsonl")
    assert summary == {"today_cost": 0.0, "month_cost": 0.0}
