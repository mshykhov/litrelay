import json
from pathlib import Path

from litrelay.pilot_tasks import write_translation_qa_no_reference_tasks


def _translation_result(chapter_id: str, translation: str) -> str:
    output = {
        "chapter_id": chapter_id,
        "translation": translation,
        "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
    }
    return json.dumps(
        {
            "custom_id": f"translate-{chapter_id}",
            "agent": "translation-agent",
            "status": "completed",
            "output": json.dumps(output, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


def test_write_translation_qa_no_reference_tasks(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    glossary = tmp_path / "glossary.csv"
    results = tmp_path / "translation.results.jsonl"
    out_jsonl = tmp_path / "qa.tasks.jsonl"
    (source_dir / "0652.txt").write_text("第652章 叹息壁垒", encoding="utf-8")
    glossary.write_text("source,target_ru,type,note,confidence\n", encoding="utf-8")
    results.write_text(_translation_result("0652", "Глава 652. Панк.") + "\n", encoding="utf-8")

    count = write_translation_qa_no_reference_tasks(
        source_dir=source_dir,
        translation_results_jsonl=results,
        glossary_csv=glossary,
        out_jsonl=out_jsonl,
    )

    assert count == 1
    task = json.loads(out_jsonl.read_text(encoding="utf-8").splitlines()[0])
    assert task["agent"] == "translation-qa"
    assert task["custom_id"] == "translation-qa-0652"
    assert task["expected_output"]["format"] == "translation_qa_json"
    assert task["input"]["generated_translation"] == "Глава 652. Панк."
    assert task["input"]["chapter_id"] == "0652"
    assert "reference_translation" not in task["input"]
