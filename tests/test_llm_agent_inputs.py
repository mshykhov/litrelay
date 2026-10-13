import json
from pathlib import Path

from litrelay.llm_agent_inputs import build_alignment_task, build_glossary_task, write_jsonl


def test_build_alignment_task_contains_translator_auditor_contract() -> None:
    task = build_alignment_task(
        chapter_id="0001",
        source_title="第1章 多元宇宙",
        ru_title="Многомерная вселенная",
        source_text="第1章 多元宇宙\n源文本。",
        ru_text="Глава 1. Мультивселенная\nРусский текст.",
    )

    assert task["custom_id"] == "alignment-0001"
    assert task["agent"] == "alignment-auditor"
    assert "professional Chinese-to-Russian literary translation auditor" in task["system"]
    assert task["input"]["chapter_id"] == "0001"
    assert task["expected_output"]["format"] == "json"
    assert "verdict" in task["expected_output"]["required_fields"]


def test_build_glossary_task_contains_glossary_contract() -> None:
    task = build_glossary_task(
        chapter_id="0001",
        prompt="Extract terms",
    )

    assert task["custom_id"] == "glossary-0001"
    assert task["agent"] == "glossary-extractor"
    assert "professional web-novel translation terminologist" in task["system"]
    assert task["input"]["prompt"] == "Extract terms"
    assert task["expected_output"]["format"] == "csv"


def test_write_jsonl_writes_one_json_object_per_line(tmp_path: Path) -> None:
    out_jsonl = tmp_path / "tasks.jsonl"

    write_jsonl([{"custom_id": "one"}, {"custom_id": "two"}], out_jsonl)

    lines = out_jsonl.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["custom_id"] for line in lines] == ["one", "two"]
