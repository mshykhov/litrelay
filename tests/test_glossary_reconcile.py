import json
from pathlib import Path

from litrelay.glossary_reconcile import (
    ReconcileFlag,
    build_reconcile_batch_task,
    flag_glossary_terms,
    write_reconcile_overrides,
)


def test_flag_glossary_terms_detects_invented_canonical(tmp_path: Path) -> None:
    glossary = tmp_path / "glossary.csv"
    ru_dir = tmp_path / "ru"
    ru_dir.mkdir()
    glossary.write_text(
        "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives\n"
        "叹息壁垒,Барьер Вздохов,spell,прямой перевод не подтверждён,0.72,0648,0648,1,\n"
        "朋克,Панк,character,stable,0.99,0001,0648,40,\n",
        encoding="utf-8",
    )
    (ru_dir / "0650.txt").write_text("Прочный барьер «Стены Вздоха» защищал мага. Панк ждал.", encoding="utf-8")

    flags = flag_glossary_terms(glossary, ru_dir, confidence_threshold=0.80)

    sources = {flag.source: flag for flag in flags}
    assert "叹息壁垒" in sources
    assert "朋克" not in sources
    reasons = sources["叹息壁垒"].reasons
    assert "low_confidence" in reasons
    assert "absent_from_reference" in reasons
    assert "unsupported_note" in reasons


def test_build_reconcile_batch_task_includes_reference_and_flags(tmp_path: Path) -> None:
    ru_dir = tmp_path / "ru"
    ru_dir.mkdir()
    (ru_dir / "0650.txt").write_text("Барьер «Стены Вздоха» держался крепко.", encoding="utf-8")
    flags = [ReconcileFlag(source="叹息壁垒", current_target="Барьер Вздохов", reasons=["low_confidence"])]

    task = build_reconcile_batch_task(flags, ru_dir, reference_chapters=15)

    assert task["custom_id"] == "reconcile-batch"
    assert task["agent"] == "glossary-extractor"
    assert "Стены Вздоха" in task["input"]["established_reference"]
    assert task["input"]["flagged_terms"][0]["source"] == "叹息壁垒"
    assert task["input"]["flagged_terms"][0]["current_target"] == "Барьер Вздохов"
    assert task["expected_output"]["format"] == "csv"


def test_write_reconcile_overrides_extracts_corrected_target(tmp_path: Path) -> None:
    results = tmp_path / "reconcile.results.jsonl"
    out_csv = tmp_path / "overrides.csv"
    csv_body = "source,target_ru,type,note,confidence\n叹息壁垒,Стена Вздоха,spell,from published,0.97\n"
    results.write_text(
        json.dumps(
            {
                "custom_id": "reconcile-叹息壁垒",
                "agent": "glossary-extractor",
                "status": "completed",
                "output": csv_body,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    count = write_reconcile_overrides(results, out_csv)

    text = out_csv.read_text(encoding="utf-8")
    assert count == 1
    assert text.splitlines()[0] == "source,target_ru,type,note,confidence"
    assert "叹息壁垒,Стена Вздоха,spell,from published,0.97" in text
