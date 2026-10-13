import json
from pathlib import Path

from litrelay.agent_usage import summarize_agent_usage


def test_summarize_agent_usage_estimates_gpt54_mini_cost(tmp_path: Path) -> None:
    results_jsonl = tmp_path / "results.jsonl"
    results_jsonl.write_text(
        json.dumps(
            {
                "custom_id": "glossary-0001",
                "status": "completed",
                "model": "gpt-5.4-mini",
                "usage": {
                    "input_tokens": 10_000,
                    "input_tokens_details": {"cached_tokens": 2_000},
                    "output_tokens": 1_000,
                    "total_tokens": 11_000,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_agent_usage(results_jsonl, model="gpt-5.4-mini")

    assert summary.completed == 1
    assert summary.input_tokens == 10_000
    assert summary.cached_input_tokens == 2_000
    assert summary.output_tokens == 1_000
    assert summary.estimated_cost_usd == 0.01065
