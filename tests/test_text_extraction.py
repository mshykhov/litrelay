from pathlib import Path

from litrelay.cli import run
from litrelay.text_extraction import extract_qidian_page_text, extract_ranobelib_text


def test_extract_ranobelib_text_from_prosemirror_doc() -> None:
    payload = {
        "data": {
            "content": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Глава 1. Мультивселенная"}]},
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Первый абзац."},
                            {"type": "hardBreak"},
                            {"type": "text", "text": "Вторая строка."},
                        ],
                    },
                ],
            }
        }
    }

    assert extract_ranobelib_text(payload) == "Глава 1. Мультивселенная\n\nПервый абзац.\nВторая строка."


def test_prosemirror_text_wraps_are_spaces_but_explicit_hard_breaks_survive() -> None:
    payload = {
        "data": {
            "content": {
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "На\nпервом\u00a0этаже."},
                            {"type": "hardBreak"},
                            {"type": "text", "text": "Другая\r\nстрока."},
                        ],
                    },
                    {"type": "paragraph", "content": [{"type": "text", "text": "Новый абзац."}]},
                ]
            }
        }
    }
    assert extract_ranobelib_text(payload) == "На первом этаже.\nДругая строка.\n\nНовый абзац."


def test_extract_qidian_page_text_from_paragraph_dump() -> None:
    payload = {
        "title": "第一章 多元宇宙 42",
        "paragraphs": ["第一段。", "31", "第二段。", ""],
    }

    assert extract_qidian_page_text(payload) == "第一章 多元宇宙\n\n第一段。\n\n第二段。"


def test_cli_extracts_texts_from_directory(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    out_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "0001.json").write_text(
        """
        {
          "data": {
            "content": {
              "type": "doc",
              "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Глава 1"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Текст главы."}]}
              ]
            }
          }
        }
        """,
        encoding="utf-8",
    )

    exit_code = run(
        [
            "extract-texts",
            "--format",
            "ranobelib-api",
            "--input-dir",
            str(input_dir),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    assert (out_dir / "0001.txt").read_text(encoding="utf-8") == "Глава 1\n\nТекст главы."
