import json
from pathlib import Path

from litrelay.translation_batch import write_translation_batch_tasks


def test_write_translation_batch_tasks_includes_context_and_guides(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    context_dir = tmp_path / "context"
    source_dir.mkdir()
    context_dir.mkdir()
    (source_dir / "0101.txt").write_text("第101章 棘手的战斗", encoding="utf-8")
    (source_dir / "0102.txt").write_text("第102章 后续", encoding="utf-8")
    (context_dir / "0099.txt").write_text("Русский контекст 99", encoding="utf-8")
    (context_dir / "0100.txt").write_text("Русский контекст 100", encoding="utf-8")
    glossary_csv = tmp_path / "glossary.csv"
    style_guide = tmp_path / "style.md"
    recap = tmp_path / "recap.md"
    out_jsonl = tmp_path / "batch.jsonl"
    glossary_csv.write_text("source,target_ru,type,note,confidence\n朋克,Панк,character,,1.0\n", encoding="utf-8")
    style_guide.write_text("Use established Russian web-novel style.", encoding="utf-8")
    recap.write_text("Punk is preparing for a fight.", encoding="utf-8")

    count = write_translation_batch_tasks(
        source_dir=source_dir,
        context_dir=context_dir,
        glossary_csv=glossary_csv,
        out_jsonl=out_jsonl,
        start=101,
        end=102,
        context_window=2,
        style_guide=style_guide,
        recap=recap,
    )

    assert count == 2
    tasks = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").splitlines()]
    assert tasks[0]["custom_id"] == "translate-0101"
    assert tasks[0]["expected_output"]["format"] == "translation_json"
    assert tasks[0]["input"]["source_text"] == "第101章 棘手的战斗"
    assert tasks[0]["input"]["style_guide"] == "Use established Russian web-novel style."
    assert tasks[0]["input"]["recap"] == "Punk is preparing for a fight."
    assert [item["chapter_id"] for item in tasks[0]["input"]["recent_russian_context"]] == ["0099", "0100"]


def test_write_translation_batch_tasks_prefers_chapter_glossary_subset(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    context_dir = tmp_path / "context"
    subset_dir = tmp_path / "subsets"
    source_dir.mkdir()
    context_dir.mkdir()
    subset_dir.mkdir()
    (source_dir / "0101.txt").write_text("第101章", encoding="utf-8")
    glossary_csv = tmp_path / "glossary.csv"
    glossary_csv.write_text("source,target_ru,type,note,confidence\n全量,Full,concept,,1\n", encoding="utf-8")
    (subset_dir / "0101.csv").write_text(
        "source,target_ru,type,note,confidence\n子集,Subset,concept,,1\n", encoding="utf-8"
    )
    out_jsonl = tmp_path / "batch.jsonl"

    write_translation_batch_tasks(
        source_dir=source_dir,
        context_dir=context_dir,
        glossary_csv=glossary_csv,
        out_jsonl=out_jsonl,
        start=101,
        end=101,
        context_window=2,
        glossary_subset_dir=subset_dir,
    )

    task = json.loads(out_jsonl.read_text(encoding="utf-8"))
    assert "子集" in task["input"]["glossary_csv"]
    assert "全量" not in task["input"]["glossary_csv"]
