import json

from litrelay.agent_backends import build_cli_requester
from litrelay.agent_executor import extract_response_text


def test_cli_requester_builds_prompt_and_extracts_fenced_json() -> None:
    captured: dict = {}

    def fake_runner(argv: list[str], prompt: str) -> str:
        captured["argv"] = argv
        captured["prompt"] = prompt
        return 'Sure, here you go:\n```json\n{"chapter_id": "0659", "translation": "Текст"}\n```\n'

    payload = {
        "model": "gpt",
        "input": [
            {"role": "system", "content": "SYSTEM-PROMPT"},
            {"role": "user", "content": '{"chapter_id": "0659"}'},
        ],
        "text": {"format": {"type": "json_schema", "schema": {"type": "object"}}},
        "metadata": {"custom_id": "translate-0659", "agent": "translation-agent"},
    }

    requester = build_cli_requester("claude", runner=fake_runner)
    response = requester(payload)
    text = extract_response_text(response)

    assert json.loads(text) == {"chapter_id": "0659", "translation": "Текст"}
    assert captured["argv"][:2] == ["claude", "-p"]
    assert "--strict-mcp-config" in captured["argv"]
    assert "SYSTEM-PROMPT" in captured["prompt"]
    assert "Schema:" in captured["prompt"]


def test_cli_requester_codex_parses_jsonl_text_and_usage() -> None:
    captured: dict = {}
    csv_text = "source,target_ru,type,note,confidence\n叹息壁垒,Стена Вздоха,spell,x,0.9"

    def fake_runner(argv: list[str], prompt: str) -> str:
        captured["argv"] = argv
        return "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "t1"}),
                json.dumps({"type": "turn.started"}),
                json.dumps({"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": csv_text}}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 21233,
                            "cached_input_tokens": 2432,
                            "output_tokens": 44,
                            "reasoning_output_tokens": 37,
                        },
                    }
                ),
            ]
        )

    payload = {
        "input": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
        "text": {"format": {"type": "text"}},
    }

    requester = build_cli_requester("codex", runner=fake_runner)
    response = requester(payload)
    text = extract_response_text(response)

    assert "--json" in captured["argv"]
    assert text.splitlines()[0] == "source,target_ru,type,note,confidence"
    assert "Стена Вздоха" in text
    assert response["usage"] == {
        "input_tokens": 21233,
        "cached_input_tokens": 2432,
        "output_tokens": 44,
        "reasoning_output_tokens": 37,
    }


def test_cli_requester_codex_jsonl_json_schema_extraction() -> None:
    def fake_runner(argv: list[str], prompt: str) -> str:
        msg = 'Sure:\n```json\n{"chapter_id": "0659", "translation": "Текст"}\n```'
        return "\n".join(
            [
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": msg}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10}}),
            ]
        )

    payload = {
        "model": "gpt-5.5",
        "input": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}],
        "text": {"format": {"type": "json_schema", "schema": {"type": "object"}}},
    }

    response = build_cli_requester("codex", runner=fake_runner)(payload)
    assert json.loads(extract_response_text(response)) == {"chapter_id": "0659", "translation": "Текст"}
    assert response["usage"]["input_tokens"] == 100


def test_codex_translation_worker_uses_read_only_sandbox() -> None:
    captured = {}

    def runner(argv, prompt):
        captured["argv"] = argv
        return json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}})

    build_cli_requester("codex", runner=runner)({"input": []})
    assert "--dangerously-bypass-approvals-and-sandbox" not in captured["argv"]
    assert captured["argv"][captured["argv"].index("--sandbox") + 1] == "read-only"
