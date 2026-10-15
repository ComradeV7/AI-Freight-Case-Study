"""Aggregate logs/usage.jsonl into logs/COST_LOG.json.

Reads one cold-cache run's usage log, counts LLM calls, sums input/output tokens,
computes local cost (always 0 for local Ollama models), and estimates the hosted
cost using the equivalent rate from config/pricing.yaml.
"""

import json
import sys
from pathlib import Path

import yaml

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))


def aggregate(usage_path: Path, pricing_path: Path, output_path: Path) -> None:
    usage_path = Path(usage_path)
    pricing_path = Path(pricing_path)
    output_path = Path(output_path)

    if not usage_path.exists():
        raise FileNotFoundError(f"Usage log not found: {usage_path}")

    with open(pricing_path, "r", encoding="utf-8") as f:
        pricing = yaml.safe_load(f)["pricing"]

    local = pricing["local"]
    hosted = pricing["hosted_equivalent"]

    calls = 0
    cache_hits = 0
    fallbacks = 0
    input_tokens = 0
    output_tokens = 0
    models = set()

    with open(usage_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            calls += 1
            if record.get("cache_hit"):
                cache_hits += 1
            if record.get("fallback"):
                fallbacks += 1
            # Newer logs use prompt_tokens/completion_tokens; older logs
            # used prompt_eval_count/eval_count.
            input_tokens += int(
                record.get("prompt_tokens") or record.get("prompt_eval_count") or 0
            )
            output_tokens += int(
                record.get("completion_tokens") or record.get("eval_count") or 0
            )
            if record.get("model"):
                models.add(record["model"])

    local_cost = 0.0
    hosted_input_rate = float(hosted["input_per_1m_tokens"])
    hosted_output_rate = float(hosted["output_per_1m_tokens"])
    hosted_cost = (
        input_tokens * hosted_input_rate / 1_000_000
        + output_tokens * hosted_output_rate / 1_000_000
    )

    report = {
        "local_model": sorted(models),
        "llm_calls": calls,
        "cache_hits": cache_hits,
        "fallbacks": fallbacks,
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "local_cost": {
            "currency": local["currency"],
            "input_per_1m_tokens": local["input_per_1m_tokens"],
            "output_per_1m_tokens": local["output_per_1m_tokens"],
            "total": local_cost,
        },
        "hosted_equivalent": {
            "provider": hosted["provider"],
            "model": hosted["model"],
            "input_per_1m_tokens": hosted_input_rate,
            "output_per_1m_tokens": hosted_output_rate,
            "estimated_total": round(hosted_cost, 6),
            "source": hosted["source"],
            "date": hosted["date"],
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Aggregated {calls} calls -> {output_path}")
    print(f"  Tokens: {input_tokens} in / {output_tokens} out")
    print(f"  Local cost: ${local_cost:.4f}  |  Hosted equivalent: ${hosted_cost:.6f}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/aggregate_cost.py <usage.jsonl> <COST_LOG.json>")
        sys.exit(1)
    aggregate(
        Path(sys.argv[1]),
        Path("config/pricing.yaml"),
        Path(sys.argv[2]),
    )
