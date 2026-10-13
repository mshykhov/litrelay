from pathlib import Path

from litrelay.integrations.reader import ReaderApiPublisher
from litrelay.publisher import (
    LocalExportPublisher,
    build_chapter_payload,
)


def test_local_export_publisher_copies_chapters(tmp_path: Path) -> None:
    chapters_dir = tmp_path / "guarded"
    out_dir = tmp_path / "published"
    chapters_dir.mkdir()
    (chapters_dir / "0652.txt").write_text("Глава 652", encoding="utf-8")
    (chapters_dir / "0653.txt").write_text("Глава 653", encoding="utf-8")

    summary = LocalExportPublisher(out_dir=out_dir).publish(chapters_dir, manifest={"slug": "demo"})

    assert summary.published == 2
    assert summary.target == str(out_dir)
    assert (out_dir / "0652.txt").read_text(encoding="utf-8") == "Глава 652"


def test_build_chapter_payload_wraps_paragraphs_and_escapes(tmp_path: Path) -> None:
    text = "Глава 1. Начало\n\nПервый абзац.\nВторой & <тег>."

    payload = build_chapter_payload(text)

    assert payload["title"] == "Глава 1. Начало"
    assert payload["content"] == "<p>Первый абзац.</p><p>Второй &amp; &lt;тег&gt;.</p>"
    assert payload["status"] == "publish"


def test_reader_api_publisher_posts_each_chapter(tmp_path: Path) -> None:
    chapters_dir = tmp_path / "guarded"
    chapters_dir.mkdir()
    (chapters_dir / "0652.txt").write_text("Глава 652\n\nТекст.", encoding="utf-8")
    (chapters_dir / "0653.txt").write_text("Глава 653\n\nТекст.", encoding="utf-8")
    posted: list[tuple[str, dict]] = []

    publisher = ReaderApiPublisher(
        base_url="https://read.example.com/wp-json/reader/v1",
        book_id=25,
        username="u",
        app_password="p",
        poster=lambda url, payload: posted.append((url, payload)),
    )
    summary = publisher.publish(chapters_dir, manifest={})

    assert summary.published == 2
    assert posted[0][0] == "https://read.example.com/wp-json/reader/v1/books/25/chapters"
    assert posted[0][1]["title"] == "Глава 652"
    assert posted[0][1]["content"] == "<p>Текст.</p>"


def test_renumber_from_rewrites_chapter_numbers(tmp_path: Path) -> None:
    chapters_dir = tmp_path / "published"
    chapters_dir.mkdir()
    (chapters_dir / "0649.txt").write_text("Глава 649 Легендарная «битва» (3)\n\nТекст.", encoding="utf-8")
    (chapters_dir / "0650.txt").write_text("Глава 650 Легендарная «битва» (4)\n\nТекст.", encoding="utf-8")
    posted: list[tuple[str, dict]] = []

    publisher = ReaderApiPublisher(
        base_url="https://x/wp-json/reader/v1",
        book_id=25,
        username="u",
        app_password="p",
        renumber_from=653,
        poster=lambda url, payload: posted.append((url, payload)),
    )
    publisher.publish(chapters_dir, manifest={})

    assert posted[0][1]["title"] == "Глава 653. Легендарная «битва» (3)"
    assert posted[1][1]["title"] == "Глова 654. Легендарная «битва» (4)".replace("Глова", "Глава")
