from pathlib import Path

from litrelay.chapter_pairs import discover_pairs


def test_discover_pairs_matches_source_and_russian_by_chapter_id(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    ru_dir = tmp_path / "ru"
    source_dir.mkdir()
    ru_dir.mkdir()
    (source_dir / "0001.txt").write_text("源文本一", encoding="utf-8")
    (source_dir / "0002.txt").write_text("源文本二", encoding="utf-8")
    (ru_dir / "0001.txt").write_text("Русский текст один", encoding="utf-8")
    (ru_dir / "0003.txt").write_text("Русский текст три", encoding="utf-8")

    pairs = discover_pairs(source_dir, ru_dir)

    assert [pair.chapter_id for pair in pairs] == ["0001"]
    assert pairs[0].source_path == source_dir / "0001.txt"
    assert pairs[0].ru_path == ru_dir / "0001.txt"
