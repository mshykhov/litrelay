import json
from pathlib import Path

from litrelay.translation_results import export_translation_results, validate_translation_results


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_validate_translation_results_counts_invalid_outputs(tmp_path: Path) -> None:
    tasks_jsonl = tmp_path / "tasks.jsonl"
    results_jsonl = tmp_path / "results.jsonl"
    _write_jsonl(tasks_jsonl, [{"custom_id": "translate-0101"}, {"custom_id": "translate-0102"}])
    _write_jsonl(
        results_jsonl,
        [
            {
                "custom_id": "translate-0101",
                "status": "completed",
                "output": json.dumps(
                    {
                        "chapter_id": "0101",
                        "translation": "Перевод",
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
            {"custom_id": "translate-0102", "status": "completed", "output": '{"chapter_id":"0102"}'},
        ],
    )

    report = validate_translation_results(tasks_jsonl, results_jsonl)

    assert report.expected == 2
    assert report.present == 2
    assert report.completed == 2
    assert report.invalid_outputs == 1
    assert not report.ok


def test_export_translation_results_writes_chapter_files(tmp_path: Path) -> None:
    results_jsonl = tmp_path / "results.jsonl"
    out_dir = tmp_path / "accepted"
    _write_jsonl(
        results_jsonl,
        [
            {
                "custom_id": "translate-0101",
                "status": "completed",
                "output": json.dumps(
                    {
                        "chapter_id": "0101",
                        "translation": "Глава 101\n\nПеревод",
                        "qa": {
                            "terminology_checked": True,
                            "omission_risk": "low",
                            "style_match": "good",
                            "issues": [],
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    )

    count = export_translation_results(results_jsonl, out_dir)

    assert count == 1
    assert (out_dir / "0101.txt").read_text(encoding="utf-8") == "Глава 101\n\nПеревод\n"


def test_model_chapter_id_cannot_escape_export_directory(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    _write_jsonl(
        results,
        [
            {
                "custom_id": "translate-0001",
                "status": "completed",
                "output": json.dumps(
                    {
                        "chapter_id": "../escape",
                        "translation": "Text",
                        "qa": {
                            "terminology_checked": True,
                            "omission_risk": "low",
                            "style_match": "good",
                            "issues": [],
                        },
                    }
                ),
            }
        ],
    )
    assert export_translation_results(results, tmp_path / "out") == 0
    assert not (tmp_path / "escape.txt").exists()
