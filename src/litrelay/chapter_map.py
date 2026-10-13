import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CSV_FIELDS = [
    "aligned_index",
    "ru_index",
    "ru_volume",
    "ru_number",
    "ru_title",
    "ru_branch_id",
    "ru_url",
    "source_chapter_number",
    "source_title",
    "source_url",
    "status",
]


@dataclass(frozen=True)
class QidianChapter:
    number: int
    title: str
    url: str


@dataclass(frozen=True)
class ChapterMapRow:
    aligned_index: int
    ru_index: int
    ru_volume: str
    ru_number: str
    ru_title: str
    ru_branch_id: int | None
    ru_url: str
    source_chapter_number: int | None
    source_title: str
    source_url: str
    status: str

    def as_csv_row(self) -> dict[str, str]:
        return {
            "aligned_index": str(self.aligned_index),
            "ru_index": str(self.ru_index),
            "ru_volume": self.ru_volume,
            "ru_number": self.ru_number,
            "ru_title": self.ru_title,
            "ru_branch_id": "" if self.ru_branch_id is None else str(self.ru_branch_id),
            "ru_url": self.ru_url,
            "source_chapter_number": "" if self.source_chapter_number is None else str(self.source_chapter_number),
            "source_title": self.source_title,
            "source_url": self.source_url,
            "status": self.status,
        }


def numbered_qidian_chapters(catalog_payload: Any) -> list[QidianChapter]:
    chapters_by_number: dict[int, QidianChapter] = {}

    for entry in _payload_entries(catalog_payload):
        title = _entry_text(entry)
        url = _entry_url(entry)
        number = _qidian_chapter_number(title)
        if number is None or number in chapters_by_number:
            continue
        chapters_by_number[number] = QidianChapter(number=number, title=title, url=url)

    return [chapters_by_number[number] for number in sorted(chapters_by_number)]


def build_chapter_map_rows(
    ranobelib_payload: Any,
    qidian_catalog_payload: Any,
    *,
    ranobelib_slug: str,
    preferred_branch_id: int | None = None,
    ranobelib_base_url: str = "https://ranobelib.me/ru",
) -> list[ChapterMapRow]:
    source_chapters = {
        chapter.number: chapter for chapter in _qidian_chapters_by_catalog_sequence(qidian_catalog_payload)
    }
    rows: list[ChapterMapRow] = []

    for chapter in _ranobelib_chapters(ranobelib_payload):
        ru_index = _required_int(chapter, "index")
        ru_volume = str(chapter.get("volume", "")).strip()
        ru_number = str(chapter.get("number", "")).strip()
        ru_title = str(chapter.get("name", "")).strip()
        ru_branch_id = _select_branch_id(chapter.get("branches"), preferred_branch_id)
        source_chapter = source_chapters.get(ru_index)

        rows.append(
            ChapterMapRow(
                aligned_index=ru_index,
                ru_index=ru_index,
                ru_volume=ru_volume,
                ru_number=ru_number,
                ru_title=ru_title,
                ru_branch_id=ru_branch_id,
                ru_url=_ranobelib_chapter_url(
                    base_url=ranobelib_base_url,
                    slug=ranobelib_slug,
                    volume=ru_volume,
                    number=ru_number,
                    branch_id=ru_branch_id,
                ),
                source_chapter_number=None if source_chapter is None else source_chapter.number,
                source_title="" if source_chapter is None else source_chapter.title,
                source_url="" if source_chapter is None else source_chapter.url,
                status="missing-original-metadata" if source_chapter is None else "paired-metadata",
            )
        )

    return rows


def _qidian_chapters_by_catalog_sequence(catalog_payload: Any) -> list[QidianChapter]:
    chapters: list[QidianChapter] = []

    for entry in _payload_entries(catalog_payload):
        title = _entry_text(entry)
        if _qidian_chapter_number(title) is None:
            continue
        chapters.append(QidianChapter(number=len(chapters) + 1, title=title, url=_entry_url(entry)))

    return chapters


def write_chapter_map_csv(rows: list[ChapterMapRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv_row())


def _payload_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [_ensure_entry(entry) for entry in payload]
    if isinstance(payload, dict):
        for key in ("entries", "chapters", "data", "items", "catalog"):
            value = payload.get(key)
            if isinstance(value, list):
                return [_ensure_entry(entry) for entry in value]
    raise ValueError("Expected catalog payload to be a list or a dict with entries")


def _ensure_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError("Expected catalog entry to be an object")
    return entry


def _entry_text(entry: dict[str, Any]) -> str:
    return str(entry.get("title") or entry.get("text") or entry.get("name") or "").strip()


def _entry_url(entry: dict[str, Any]) -> str:
    return str(entry.get("url") or entry.get("href") or entry.get("link") or "").strip()


def _qidian_chapter_number(title: str) -> int | None:
    match = re.match(r"^第([0-9一二三四五六七八九十百千万零〇两]+)章", title)
    if not match:
        return None

    raw_number = match.group(1)
    if raw_number.isdigit():
        return int(raw_number)
    return _chinese_number_to_int(raw_number)


def _chinese_number_to_int(raw_number: str) -> int:
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000}

    total = 0
    section = 0
    current_digit = 0
    for char in raw_number:
        if char in digits:
            current_digit = digits[char]
            continue
        if char in units:
            section += (current_digit or 1) * units[char]
            current_digit = 0
            continue
        if char == "万":
            total += (section + current_digit) * 10000
            section = 0
            current_digit = 0
            continue
        raise ValueError(f"Unsupported Chinese chapter number character: {char}")

    return total + section + current_digit


def _ranobelib_chapters(payload: Any) -> list[dict[str, Any]]:
    entries = _payload_entries(payload)
    return sorted(entries, key=lambda entry: _required_int(entry, "index"))


def _required_int(entry: dict[str, Any], key: str) -> int:
    value = entry.get(key)
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Expected integer field {key}") from error


def _select_branch_id(branches: Any, preferred_branch_id: int | None) -> int | None:
    if not isinstance(branches, list) or not branches:
        return None

    parsed_branch_ids = [_branch_id(branch) for branch in branches]
    if preferred_branch_id in parsed_branch_ids:
        return preferred_branch_id
    return parsed_branch_ids[0]


def _branch_id(branch: Any) -> int | None:
    if not isinstance(branch, dict):
        return None
    value = branch.get("branch_id")
    if value is None:
        return None
    return int(value)


def _ranobelib_chapter_url(
    *,
    base_url: str,
    slug: str,
    volume: str,
    number: str,
    branch_id: int | None,
) -> str:
    url = f"{base_url.rstrip('/')}/{slug}/read/v{volume}/c{number}"
    if branch_id is None:
        return url
    return f"{url}?bid={branch_id}"
