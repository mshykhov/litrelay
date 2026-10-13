import csv
from pathlib import Path

from litrelay.chapter_map import build_chapter_map_rows, numbered_qidian_chapters
from litrelay.cli import run


def test_numbered_qidian_chapters_keeps_only_chapter_titles() -> None:
    catalog = [
        {"text": "第一章 多元宇宙", "href": "https://www.qidian.com/chapter/1009711525/373910253/"},
        {"title": "第一千三百四十三章 结局", "url": "https://www.qidian.com/chapter/1009711525/465532444/"},
        {"title": "结尾感言", "url": "https://www.qidian.com/chapter/1009711525/465342796/"},
    ]

    chapters = numbered_qidian_chapters(catalog)

    assert [chapter.number for chapter in chapters] == [1, 1343]
    assert chapters[1].title == "第一千三百四十三章 结局"


def test_build_chapter_map_rows_uses_index_for_alignment_and_number_for_url() -> None:
    ranobelib_payload = {
        "data": [
            {
                "index": 1,
                "volume": "1",
                "number": "1",
                "name": "Многомерная вселенная",
                "branches": [{"branch_id": 23590}],
            },
            {
                "index": 2,
                "volume": "1",
                "number": "3",
                "name": "Душа в Пустоте",
                "branches": [{"branch_id": 21802}],
            },
        ]
    }
    qidian_catalog = [
        {"text": "第一章 多元宇宙", "href": "https://www.qidian.com/chapter/1009711525/373910253/"},
        {"text": "第二章 虚空中的灵魂", "href": "https://www.qidian.com/chapter/1009711525/374516047/"},
    ]

    rows = build_chapter_map_rows(
        ranobelib_payload,
        qidian_catalog,
        ranobelib_slug="117346--netherils-glory",
        preferred_branch_id=23590,
    )

    assert rows[0].aligned_index == 1
    assert rows[0].ru_url == "https://ranobelib.me/ru/117346--netherils-glory/read/v1/c1?bid=23590"
    assert rows[0].source_chapter_number == 1
    assert rows[1].aligned_index == 2
    assert rows[1].ru_number == "3"
    assert rows[1].ru_url == "https://ranobelib.me/ru/117346--netherils-glory/read/v1/c3?bid=21802"
    assert rows[1].source_chapter_number == 2
    assert rows[1].status == "paired-metadata"


def test_build_chapter_map_rows_aligns_qidian_by_catalog_sequence() -> None:
    ranobelib_payload = {
        "data": [
            {
                "index": 1,
                "volume": "1",
                "number": "1",
                "name": "Первая",
                "branches": [{"branch_id": 23590}],
            },
            {
                "index": 2,
                "volume": "1",
                "number": "2",
                "name": "Вторая",
                "branches": [{"branch_id": 23590}],
            },
        ]
    }
    qidian_catalog = [
        {"text": "第一章 正常", "href": "https://www.qidian.com/chapter/1009711525/1/"},
        {"text": "上架感言", "href": "https://www.qidian.com/chapter/1009711525/note/"},
        {"text": "第三章 标题编号错了", "href": "https://www.qidian.com/chapter/1009711525/2/"},
    ]

    rows = build_chapter_map_rows(
        ranobelib_payload,
        qidian_catalog,
        ranobelib_slug="117346--netherils-glory",
        preferred_branch_id=23590,
    )

    assert rows[1].source_chapter_number == 2
    assert rows[1].source_title == "第三章 标题编号错了"


def test_cli_writes_chapter_map_csv(tmp_path: Path) -> None:
    ranobelib_json = tmp_path / "ranobelib.json"
    qidian_json = tmp_path / "qidian.json"
    out_csv = tmp_path / "chapter-map.csv"
    ranobelib_json.write_text(
        """
        {
          "data": [
            {
              "index": 1,
              "volume": "1",
              "number": "1",
              "name": "Многомерная вселенная",
              "branches": [{"branch_id": 23590}]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    qidian_json.write_text(
        """
        [
          {
            "text": "第一章 多元宇宙",
            "href": "https://www.qidian.com/chapter/1009711525/373910253/"
          }
        ]
        """,
        encoding="utf-8",
    )

    exit_code = run(
        [
            "make-chapter-map",
            "--ranobelib-json",
            str(ranobelib_json),
            "--qidian-json",
            str(qidian_json),
            "--out-csv",
            str(out_csv),
            "--ranobelib-slug",
            "117346--netherils-glory",
            "--preferred-branch-id",
            "23590",
        ]
    )

    assert exit_code == 0
    with out_csv.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    assert rows == [
        {
            "aligned_index": "1",
            "ru_index": "1",
            "ru_volume": "1",
            "ru_number": "1",
            "ru_title": "Многомерная вселенная",
            "ru_branch_id": "23590",
            "ru_url": "https://ranobelib.me/ru/117346--netherils-glory/read/v1/c1?bid=23590",
            "source_chapter_number": "1",
            "source_title": "第一章 多元宇宙",
            "source_url": "https://www.qidian.com/chapter/1009711525/373910253/",
            "status": "paired-metadata",
        }
    ]
