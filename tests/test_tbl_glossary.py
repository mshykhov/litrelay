import csv
from pathlib import Path

from litrelay.tbl_glossary import write_tbl_glossary_csv


def test_write_tbl_glossary_csv_maps_columns_and_deduplicates_by_confidence(tmp_path: Path) -> None:
    glossary_csv = tmp_path / "glossary.csv"
    out_csv = tmp_path / "tbl.csv"
    glossary_csv.write_text(
        "\n".join(
            [
                "chapter_id,source,target_ru,type,note,confidence",
                "0001,朋克,Панк,character,,0.70",
                "0002,朋克,Панк-лучше,character,,0.90",
                "0003,魔网,Магическая сеть,cosmology,,0.95",
                "0004,空白,,concept,,0.80",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    count = write_tbl_glossary_csv(glossary_csv, out_csv)

    assert count == 2
    with out_csv.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows == [
        {"source_term": "朋克", "translated_term": "Панк-лучше", "category": "character"},
        {"source_term": "魔网", "translated_term": "Магическая сеть", "category": "cosmology"},
    ]
