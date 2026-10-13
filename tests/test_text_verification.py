import csv
from pathlib import Path

from litrelay.text_verification import verify_numbered_texts, verify_text_directory


def test_verify_text_directory_accepts_full_text_files(tmp_path: Path) -> None:
    chapter_map = _write_map(tmp_path, [1, 2])
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "0001.txt").write_text("Глава 1\n\n" + ("Текст. " * 200), encoding="utf-8")
    (text_dir / "0002.txt").write_text("Глава 2\n\n" + ("Текст. " * 200), encoding="utf-8")

    report = verify_text_directory(chapter_map, text_dir, min_chars=1000)

    assert report.expected == 2
    assert report.present == 2
    assert report.missing == []
    assert report.too_short == []
    assert report.suspicious == []


def test_verify_text_directory_reports_missing_short_and_suspicious(tmp_path: Path) -> None:
    chapter_map = _write_map(tmp_path, [1, 2, 3])
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "0001.txt").write_text("short", encoding="utf-8")
    (text_dir / "0002.txt").write_text("<html>captcha</html>" + ("x" * 1200), encoding="utf-8")

    report = verify_text_directory(chapter_map, text_dir, min_chars=1000)

    assert report.expected == 3
    assert report.present == 2
    assert report.missing == ["0003"]
    assert report.too_short == [("0001", 5)]
    assert report.suspicious == [("0002", "looks-like-html")]


def test_verify_numbered_texts_checks_expected_count(tmp_path: Path) -> None:
    text_dir = tmp_path / "text"
    text_dir.mkdir()
    (text_dir / "0001.txt").write_text("第1章\n\n" + ("正文。" * 400), encoding="utf-8")
    (text_dir / "0002.txt").write_text("short", encoding="utf-8")

    report = verify_numbered_texts(text_dir, expected_count=3, min_chars=1000)

    assert report.expected == 3
    assert report.present == 2
    assert report.missing == ["0003"]
    assert report.too_short == [("0002", 5)]


def _write_map(tmp_path: Path, indexes: list[int]) -> Path:
    chapter_map = tmp_path / "chapter-map.csv"
    with chapter_map.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["aligned_index"])
        writer.writeheader()
        for index in indexes:
            writer.writerow({"aligned_index": str(index)})
    return chapter_map
