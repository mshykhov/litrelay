from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelRate:
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float


@dataclass(frozen=True)
class AgentUsageSummary:
    model: str
    completed: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float


MODEL_RATES = {
    "gpt-5.4-mini": ModelRate(input_per_1m=0.75, cached_input_per_1m=0.075, output_per_1m=4.50),
    "gpt-5.4": ModelRate(input_per_1m=2.50, cached_input_per_1m=0.25, output_per_1m=15.00),
}


def summarize_agent_usage(results_jsonl: Path, *, model: str) -> AgentUsageSummary:
    rate = MODEL_RATES[model]
    completed = 0
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    total_tokens = 0

    with results_jsonl.open(encoding="utf-8") as results_file:
        for line in results_file:
            if not line.strip():
                continue
            result = json.loads(line)
            if result.get("status") != "completed":
                continue
            completed += 1
            usage = result.get("usage", {})
            input_tokens += int(usage.get("input_tokens", 0))
            cached_input_tokens += _cached_tokens(usage)
            output_tokens += int(usage.get("output_tokens", 0))
            total_tokens += int(usage.get("total_tokens", 0))

    non_cached_input_tokens = max(0, input_tokens - cached_input_tokens)
    cost = (
        non_cached_input_tokens * rate.input_per_1m
        + cached_input_tokens * rate.cached_input_per_1m
        + output_tokens * rate.output_per_1m
    ) / 1_000_000
    return AgentUsageSummary(
        model=model,
        completed=completed,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=round(cost, 6),
    )


def format_agent_usage_summary(summary: AgentUsageSummary) -> str:
    return "\n".join(
        [
            f"model={summary.model}",
            f"completed={summary.completed}",
            f"input_tokens={summary.input_tokens}",
            f"cached_input_tokens={summary.cached_input_tokens}",
            f"output_tokens={summary.output_tokens}",
            f"total_tokens={summary.total_tokens}",
            f"estimated_cost_usd={summary.estimated_cost_usd:.6f}",
        ]
    )


def _cached_tokens(usage: dict[str, Any]) -> int:
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    return int(details.get("cached_tokens", 0))
