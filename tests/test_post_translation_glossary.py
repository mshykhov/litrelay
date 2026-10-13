import json
from pathlib import Path

from litrelay.post_translation_glossary import write_post_translation_glossary_tasks


def test_write_post_translation_glossary_tasks_uses_generated_translation(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "0101.txt").write_text("第101章 棘手的战斗\n动能静滞", encoding="utf-8")
    glossary_csv = tmp_path / "glossary.csv"
    glossary_csv.write_text(
        "source,target_ru,type,note,confidence\n咒法系,Школа Призыва,magic_school,,0.82\n",
        encoding="utf-8",
    )
    results_jsonl = tmp_path / "translation-results.jsonl"
    results_jsonl.write_text(
        json.dumps(
            {
                "custom_id": "translate-0101",
                "status": "completed",
                "output": json.dumps(
                    {
                        "chapter_id": "0101",
                        "translation": "Глава 101\nКинетическая статика.",
                        "qa": {
                            "terminology_checked": True,
                            "omission_risk": "low",
                            "style_match": "good",
                            "issues": [],
                        },
                    },
                    ensure_ascii=False,
                ),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    out_jsonl = tmp_path / "post-glossary.jsonl"

    count = write_post_translation_glossary_tasks(
        source_dir=source_dir,
        translation_results_jsonl=results_jsonl,
        glossary_csv=glossary_csv,
        out_jsonl=out_jsonl,
    )

    assert count == 1
    task = json.loads(out_jsonl.read_text(encoding="utf-8"))
    assert task["custom_id"] == "post-glossary-0101"
    assert task["agent"] == "glossary-extractor"
    assert "动能静滞" in task["input"]["prompt"]
    assert "Кинетическая статика" in task["input"]["prompt"]
    assert "Школа Призыва" in task["input"]["prompt"]
    assert task["expected_output"]["format"] == "csv"
