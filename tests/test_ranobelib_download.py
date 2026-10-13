import csv
from pathlib import Path

from litrelay.ranobelib_download import download_ranobelib_chapters, read_ranobelib_refs_from_csv


def test_read_ranobelib_refs_from_csv_uses_map_fields(tmp_path: Path) -> None:
    chapter_map = tmp_path / "chapter-map.csv"
    with chapter_map.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["aligned_index", "ru_volume", "ru_number", "ru_branch_id", "ru_title"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "aligned_index": "1",
                "ru_volume": "1",
                "ru_number": "2",
                "ru_branch_id": "23590",
                "ru_title": "Глава",
            }
        )

    refs = read_ranobelib_refs_from_csv(chapter_map)

    assert len(refs) == 1
    assert refs[0].chapter_id == "0001"
    assert refs[0].volume == "1"
    assert refs[0].number == "2"
    assert refs[0].branch_id == 23590


def test_download_ranobelib_chapters_writes_json_and_text(tmp_path: Path) -> None:
    refs = read_ranobelib_refs_from_csv(_write_single_row_map(tmp_path))
    requested_urls: list[str] = []

    def fake_fetch(url: str) -> dict:
        requested_urls.append(url)
        return {
            "data": {
                "content": {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Глава 1"}]},
                        {"type": "paragraph", "content": [{"type": "text", "text": "Текст."}]},
                    ],
                }
            }
        }

    summary = download_ranobelib_chapters(
        refs,
        api_slug="117346--netherils-glory",
        out_json_dir=tmp_path / "json",
        out_text_dir=tmp_path / "txt",
        fetch_json=fake_fetch,
    )

    assert summary.downloaded == 1
    assert requested_urls == [
        "https://api.cdnlibs.org/api/manga/117346--netherils-glory/chapter?branch_id=23590&number=1&volume=1"
    ]
    assert (tmp_path / "json" / "0001.json").exists()
    assert (tmp_path / "txt" / "0001.txt").read_text(encoding="utf-8") == "Глава 1\n\nТекст."


def _write_single_row_map(tmp_path: Path) -> Path:
    chapter_map = tmp_path / "chapter-map.csv"
    with chapter_map.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["aligned_index", "ru_volume", "ru_number", "ru_branch_id", "ru_title"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "aligned_index": "1",
                "ru_volume": "1",
                "ru_number": "1",
                "ru_branch_id": "23590",
                "ru_title": "Глава",
            }
        )
    return chapter_map
