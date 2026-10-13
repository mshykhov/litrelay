import json
from pathlib import Path

from litrelay.agent_executor import build_responses_payload, extract_response_text, run_agent_tasks


def test_build_responses_payload_uses_structured_output_for_alignment() -> None:
    task = {
        "custom_id": "alignment-0001",
        "agent": "alignment-auditor",
        "system": "Audit alignment.",
        "input": {"chapter_id": "0001"},
        "expected_output": {"format": "json"},
    }

    payload = build_responses_payload(task, model="gpt-5.4", max_output_tokens=800)

    assert payload["model"] == "gpt-5.4"
    assert payload["store"] is False
    assert payload["max_output_tokens"] == 800
    assert payload["input"][0] == {"role": "system", "content": "Audit alignment."}
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["name"] == "alignment_audit"


def test_extract_response_text_reads_output_text_parts() -> None:
    response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "part one"},
                    {"type": "output_text", "text": " part two"},
                ],
            }
        ]
    }

    assert extract_response_text(response) == "part one part two"


def test_build_responses_payload_uses_translation_schema() -> None:
    task = {
        "custom_id": "translate-0101",
        "agent": "translation-agent",
        "system": "Translate.",
        "input": {"chapter_id": "0101"},
        "expected_output": {"format": "translation_json"},
    }

    payload = build_responses_payload(task, model="gpt-5.4-mini")

    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["name"] == "chapter_translation"


def test_run_agent_tasks_writes_jsonl_results(tmp_path: Path) -> None:
    in_jsonl = tmp_path / "tasks.jsonl"
    out_jsonl = tmp_path / "results.jsonl"
    task = {
        "custom_id": "alignment-0001",
        "agent": "alignment-auditor",
        "system": "Audit alignment.",
        "input": {"chapter_id": "0001"},
        "expected_output": {"format": "json"},
    }
    in_jsonl.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")

    def fake_requester(payload: dict) -> dict:
        assert payload["metadata"]["custom_id"] == "alignment-0001"
        return {
            "id": "resp_123",
            "model": "gpt-5.4-mini",
            "service_tier": "default",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "total_tokens": 14,
            },
            "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"verdict":"aligned"}'}]}],
        }

    summary = run_agent_tasks(
        in_jsonl,
        out_jsonl,
        model="gpt-5.4",
        max_output_tokens=800,
        requester=fake_requester,
    )

    assert summary.completed == 1
    assert summary.failed == 0
    result = json.loads(out_jsonl.read_text(encoding="utf-8"))
    assert result["custom_id"] == "alignment-0001"
    assert result["status"] == "completed"
    assert result["output"] == '{"verdict":"aligned"}'
    assert result["response_id"] == "resp_123"
    assert result["model"] == "gpt-5.4-mini"
    assert result["usage"]["input_tokens"] == 10
