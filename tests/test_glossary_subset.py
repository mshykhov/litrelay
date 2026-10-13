import csv
from pathlib import Path

from litrelay.glossary_subset import write_glossary_subset, write_glossary_subsets


def test_write_glossary_subset_keeps_present_terms_and_core_types(tmp_path: Path) -> None:
    glossary_csv = tmp_path / "glossary.csv"
    source_chapter = tmp_path / "0101.txt"
    out_csv = tmp_path / "subset.csv"
    glossary_csv.write_text(
        "\n".join(
            [
                "chapter_id,source,target_ru,type,note,confidence",
                "0001,朋克,Панк,character,,0.99",
                "0002,动能静滞,Кинетический стазис,spell,,0.90",
                "0003,咒法系,Школа Призыва,magic_school,,0.82",
                "0004,无关术语,Ненужный термин,artifact,,0.80",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    source_chapter.write_text("朋克 使用了 动能静滞。", encoding="utf-8")

    count = write_glossary_subset(
        glossary_csv,
        source_chapter,
        out_csv,
        always_include_types={"character", "magic_school"},
    )

    output = out_csv.read_text(encoding="utf-8")
    assert count == 3
    assert "朋克" in output
    assert "动能静滞" in output
    assert "咒法系" in output
    assert "无关术语" not in output


def test_write_glossary_subsets_writes_one_file_per_chapter(tmp_path: Path) -> None:
    glossary_csv = tmp_path / "glossary.csv"
    source_dir = tmp_path / "source"
    out_dir = tmp_path / "subsets"
    source_dir.mkdir()
    glossary_csv.write_text(
        "\n".join(
            [
                "chapter_id,source,target_ru,type,note,confidence",
                "0001,朋克,Панк,character,,0.99",
                "0002,动能静滞,Кинетический стазис,spell,,0.90",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "0101.txt").write_text("朋克 使用了 动能静滞。", encoding="utf-8")
    (source_dir / "0102.txt").write_text("朋克 观察。", encoding="utf-8")

    summary = write_glossary_subsets(glossary_csv, source_dir, out_dir, start=101, end=102)

    assert summary == {"0101": 2, "0102": 1}
    assert (out_dir / "0101.csv").exists()
    assert (out_dir / "0102.csv").exists()


def test_write_glossary_subset_omits_alternatives_that_can_poison_translation(tmp_path: Path) -> None:
    glossary_csv = tmp_path / "glossary.csv"
    source_chapter = tmp_path / "0654.txt"
    out_csv = tmp_path / "subset.csv"
    glossary_csv.write_text(
        "\n".join(
            [
                "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives",
                "崩灭奇点,Сингулярность Разрушения,spell,Легендарное заклинание,0.98,0597,0599,3,«崩灭奇点»:1; Схлопывающаяся сингулярность:1",
                "朋克,Панк,character,Главный персонаж,0.99,0001,0651,481,Панкoм:1; Петер:1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    source_chapter.write_text("朋克 使用 崩灭奇点。", encoding="utf-8")

    count = write_glossary_subset(glossary_csv, source_chapter, out_csv)

    output = out_csv.read_text(encoding="utf-8")
    assert count == 2
    assert output.splitlines()[0] == "source,target_ru,type,note,confidence"
    assert "Сингулярность Разрушения" in output
    assert "«崩灭奇点»:1" not in output
    assert "Панкoм" not in output


def test_write_glossary_subset_sanitizes_source_terms_from_notes(tmp_path: Path) -> None:
    glossary_csv = tmp_path / "glossary.csv"
    source_chapter = tmp_path / "0653.txt"
    out_csv = tmp_path / "subset.csv"
    glossary_csv.write_text(
        "\n".join(
            [
                "source,target_ru,type,note,confidence,first_seen,last_seen,source_count,alternatives",
                "漆黑小球,чёрный шар,artifact,форма заклинания 崩灭奇点,0.76,0598,0598,1,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    source_chapter.write_text("漆黑小球 медленно расширялся.", encoding="utf-8")

    write_glossary_subset(glossary_csv, source_chapter, out_csv)

    with out_csv.open(encoding="utf-8", newline="") as out_file:
        [row] = list(csv.DictReader(out_file))
    assert row["note"] == "форма заклинания"
