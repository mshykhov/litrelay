import pytest

from litrelay.ranobelib_repair import (
    index_reader_chapters,
    index_source_chapters,
    render_ranobelib_content,
)


def test_render_prosemirror_as_safe_paragraphs_without_duplicate_heading() -> None:
    payload = {
        "data": {
            "content": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Глава 284: Сущность Искажения"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Текст & <опасный>."}],
                    },
                ],
            }
        }
    }

    content = render_ranobelib_content(
        payload,
        chapter_number=284,
        reader_title="Глава 284. Сущность Искажения",
    )

    assert content == "<p>Текст &amp; &lt;опасный&gt;.</p>"


def test_render_existing_html_preserves_text_and_removes_service_attributes() -> None:
    payload = {
        "data": {
            "content": '<p data-paragraph-index="1">Первый.</p><p>Второй.</p>',
        }
    }

    content = render_ranobelib_content(
        payload,
        chapter_number=1,
        reader_title="Глава 1. Начало",
    )

    assert content == "<p>Первый.</p><p>Второй.</p>"


def test_render_html_collapses_soft_wraps_without_changing_blocks_or_attributes() -> None:
    payload = {
        "data": {
            "content": '<p title="x > y">На\nпервом\r\nэтаже <em>магазина\nНина</em> сидела.</p><p>Она\u00a0\u202fждала.</p>'
        }
    }
    result = render_ranobelib_content(payload, chapter_number=186, reader_title="Глава 186")
    assert result == '<p title="x > y">На первом этаже <em>магазина Нина</em> сидела.</p><p>Она ждала.</p>'


def test_render_preserves_numbered_first_paragraph_when_title_differs() -> None:
    payload = {
        "data": {
            "content": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Глава 1. Важный первый абзац"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Второй абзац."}],
                    },
                ],
            }
        }
    }

    content = render_ranobelib_content(
        payload,
        chapter_number=1,
        reader_title="Глава 1. Другое название",
    )

    assert content == "<p>Глава 1. Важный первый абзац</p><p>Второй абзац.</p>"


def test_render_preserves_body_paragraph_ending_with_reader_title() -> None:
    payload = {
        "data": {
            "content": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Сегодня обсуждали Другое название"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Второй абзац."}],
                    },
                ],
            }
        }
    }

    content = render_ranobelib_content(
        payload,
        chapter_number=1,
        reader_title="Глава 1. Другое название",
    )

    assert content == "<p>Сегодня обсуждали Другое название</p><p>Второй абзац.</p>"


@pytest.mark.parametrize(
    "content",
    [
        "",
        "<p>{'type': 'doc', 'content': []}</p>",
    ],
)
def test_render_rejects_empty_or_raw_object_text(content: str) -> None:
    payload = {"data": {"content": content}}

    with pytest.raises(ValueError):
        render_ranobelib_content(
            payload,
            chapter_number=1,
            reader_title="Глава 1",
        )


def test_index_complete_source_and_reader_inventory() -> None:
    source = [{"number": str(number)} for number in range(1, 4)]
    reader = [{"id": 100 + number, "title": f"Глава {number}. Тест"} for number in range(1, 4)]

    assert sorted(index_source_chapters(source, expected_end=3)) == [1, 2, 3]
    assert sorted(index_reader_chapters(reader, expected_end=3)) == [1, 2, 3]


@pytest.mark.parametrize(
    "items",
    [
        [{"number": "1"}, {"number": "1"}, {"number": "2"}],
        [{"number": "1"}, {"number": "3"}],
    ],
)
def test_source_inventory_rejects_duplicates_and_gaps(items: list[dict]) -> None:
    with pytest.raises(ValueError):
        index_source_chapters(items, expected_end=3)


def test_reader_inventory_rejects_unnumbered_titles() -> None:
    with pytest.raises(ValueError, match="no numeric title"):
        index_reader_chapters(
            [{"id": 101, "title": "Пролог"}],
            expected_end=1,
        )
