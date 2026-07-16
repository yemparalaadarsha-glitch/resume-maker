import json
from datetime import datetime, timezone
from pathlib import Path

# Sonnet 5 uses intro pricing, active through 2026-08-31.
PRICING = {
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    input_cost = input_tokens / 1_000_000 * rates["input"]
    output_cost = output_tokens / 1_000_000 * rates["output"]
    # Cache writes bill at 1.25x the base input rate; cache reads bill at 0.1x.
    cache_write_cost = cache_creation_input_tokens / 1_000_000 * rates["input"] * 1.25
    cache_read_cost = cache_read_input_tokens / 1_000_000 * rates["input"] * 0.1
    return input_cost + output_cost + cache_write_cost + cache_read_cost


def log_usage(
    call_type: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    log_path: Path,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "call_type": call_type,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "cost": estimate_cost(
            model, input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens
        ),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def get_cost_summary(log_path: Path) -> dict:
    if not log_path.exists():
        return {"today_cost": 0.0, "month_cost": 0.0}

    now = datetime.now(timezone.utc)
    today_cost = 0.0
    month_cost = 0.0

    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            entry_time = datetime.fromisoformat(entry["timestamp"])
            if entry_time.date() == now.date():
                today_cost += entry["cost"]
            if entry_time.year == now.year and entry_time.month == now.month:
                month_cost += entry["cost"]

    return {"today_cost": today_cost, "month_cost": month_cost}
