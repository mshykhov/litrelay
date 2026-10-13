import csv
from pathlib import Path

from litrelay.alignment_review import (
    build_alignment_review_rows,
    choose_alignment_review_indexes,
    write_alignment_review_csv,
)


def test_choose_alignment_review_indexes_includes_edges_known_risks_and_regular_samples() -> None:
    indexes = choose_alignment_review_indexes(total=120, sample_every=50, known_risks=[83, 151, 999])

    assert indexes == [1, 2, 3, 50, 83, 100, 118, 119, 120]


def test_build_alignment_review_rows_includes_titles_lengths_and_previews(tmp_path: Path) -> None:
    working_map = tmp_path / "working-map.csv"
    source_dir = tmp_path / "source"
    ru_dir = tmp_path / "ru"
    source_dir.mkdir()
    ru_dir.mkdir()
    _write_working_map(working_map)
    (source_dir / "0001.txt").write_text("第1章 多元宇宙\n源文本第一段。\n源文本第二段。", encoding="utf-8")
    (ru_dir / "0001.txt").write_text("Глава 1. Мультивселенная\nРусский первый абзац.", encoding="utf-8")

    rows = build_alignment_review_rows(
        working_map,
        source_dir=source_dir,
        ru_dir=ru_dir,
        indexes=[1],
        preview_chars=80,
    )

    assert len(rows) == 1
    assert rows[0]["aligned_index"] == "1"
    assert rows[0]["ru_title"] == "Многомерная вселенная"
    assert rows[0]["source_title"] == "第1章 多元宇宙"
    assert rows[0]["ru_chars"] == "46"
    assert rows[0]["source_chars"] == "24"
    assert rows[0]["review_status"] == "needs-review"
    assert "Русский первый" in rows[0]["ru_preview"]
    assert "源文本第一段" in rows[0]["source_preview"]


def test_write_alignment_review_csv(tmp_path: Path) -> None:
    out_csv = tmp_path / "alignment-review.csv"
    rows = [{"aligned_index": "1", "ru_title": "RU", "source_title": "ZH"}]

    write_alignment_review_csv(rows, out_csv)

    with out_csv.open(encoding="utf-8", newline="") as csv_file:
        written = list(csv.DictReader(csv_file))
    assert written == [{"aligned_index": "1", "ru_title": "RU", "source_title": "ZH"}]


def _write_working_map(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "aligned_index",
                "ru_title",
                "source_title",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "aligned_index": "1",
                "ru_title": "Многомерная вселенная",
                "source_title": "第1章 多元宇宙",
            }
        )
