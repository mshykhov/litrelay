import html
import re
from typing import Any

from litrelay.publisher import chapter_html
from litrelay.text_extraction import extract_ranobelib_text
from litrelay.text_normalization import normalize_html_whitespace

RAW_OBJECT_MARKERS = ("{'type': 'doc'", '"type": "doc"', '"type":"doc"')
SERVICE_ATTRIBUTE_RE = re.compile(
    r"\s+data-paragraph-index=(?:\"\d+\"|'\d+')",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
READER_CHAPTER_NUMBER_RE = re.compile(r"^\s*Глава\s+(\d+)(?:\.|\s|$)")


def index_source_chapters(
    chapters: list[dict[str, Any]],
    *,
    expected_end: int,
) -> dict[int, dict[str, Any]]:
    numbers = [int(chapter["number"]) for chapter in chapters]
    return _index_unique(chapters, numbers, expected_end, "source")


def index_reader_chapters(
    chapters: list[dict[str, Any]],
    *,
    expected_end: int,
) -> dict[int, dict[str, Any]]:
    numbers: list[int] = []
    for chapter in chapters:
        match = READER_CHAPTER_NUMBER_RE.match(str(chapter.get("title", "")))
        if not match:
            raise ValueError(f"Reader chapter has no numeric title: {chapter.get('title')!r}")
        numbers.append(int(match.group(1)))
    return _index_unique(chapters, numbers, expected_end, "reader")


def render_ranobelib_content(
    payload: Any,
    *,
    chapter_number: int,
    reader_title: str,
) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise ValueError("RanobeLib payload does not contain data")

    content = payload["data"].get("content")
    if isinstance(content, dict):
        paragraphs = [part.strip() for part in extract_ranobelib_text(payload).split("\n\n") if part.strip()]
        if paragraphs and _duplicates_title(paragraphs[0], chapter_number, reader_title):
            paragraphs.pop(0)
        rendered = chapter_html("\n\n".join(paragraphs))
    elif isinstance(content, str):
        rendered = normalize_html_whitespace(SERVICE_ATTRIBUTE_RE.sub("", content)).strip()
    else:
        raise ValueError("RanobeLib data.content must be HTML or ProseMirror JSON")

    plain_text = html.unescape(TAG_RE.sub("", rendered)).strip()
    if not plain_text or any(marker in rendered for marker in RAW_OBJECT_MARKERS):
        raise ValueError("Rendered chapter is empty or contains a raw object")
    return rendered


def _duplicates_title(first: str, chapter_number: int, reader_title: str) -> bool:
    normalized = _normalize_title(first)
    title = _normalize_title(reader_title)
    suffix = re.sub(
        rf"^глава\s+{chapter_number}\s*",
        "",
        title,
    ).strip()
    chapter_prefix = f"глава {chapter_number} "
    return (
        normalized == title
        or normalized == suffix
        or bool(suffix and normalized.startswith(chapter_prefix) and normalized.endswith(f" {suffix}"))
    )


def _normalize_title(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", " ", value.casefold()).strip()


def _index_unique(
    chapters: list[dict[str, Any]],
    numbers: list[int],
    expected_end: int,
    label: str,
) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    duplicates: set[int] = set()
    for number, chapter in zip(numbers, chapters, strict=True):
        if number in indexed:
            duplicates.add(number)
        indexed[number] = chapter

    expected = set(range(1, expected_end + 1))
    actual = set(indexed)
    if duplicates or actual != expected or len(chapters) != expected_end:
        raise ValueError(
            f"Invalid {label} inventory: duplicates={sorted(duplicates)}, "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}, "
            f"count={len(chapters)}"
        )
    return indexed
