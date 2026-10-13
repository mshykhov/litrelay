from __future__ import annotations

import csv
import re
from pathlib import Path

DEFAULT_ALWAYS_INCLUDE_TYPES = {"character", "rank", "magic_school", "cosmology"}
TRANSLATION_GLOSSARY_COLUMNS = ["source", "target_ru", "type", "note", "confidence"]
HAN_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]+")
WHITESPACE_RE = re.compile(r"\s+")


def write_glossary_subset(
    glossary_csv: Path,
    source_chapter: Path,
    out_csv: Path,
    *,
    always_include_types: set[str] | None = None,
) -> int:
    source_text = source_chapter.read_text(encoding="utf-8")
    core_types = always_include_types if always_include_types is not None else DEFAULT_ALWAYS_INCLUDE_TYPES
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    kept_rows = []
    with glossary_csv.open(encoding="utf-8", newline="") as glossary_file:
        reader = csv.DictReader(glossary_file)
        for row in reader:
            source_term = row.get("source", "")
            term_type = row.get("type", "")
            if source_term and (source_term in source_text or term_type in core_types):
                kept_rows.append(_clean_translation_row(row))

    with out_csv.open("w", encoding="utf-8", newline="") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=TRANSLATION_GLOSSARY_COLUMNS)
        writer.writeheader()
        writer.writerows(kept_rows)
    return len(kept_rows)


def write_glossary_subsets(
    glossary_csv: Path,
    source_dir: Path,
    out_dir: Path,
    *,
    start: int,
    end: int,
    always_include_types: set[str] | None = None,
) -> dict[str, int]:
    summary = {}
    for index in range(start, end + 1):
        chapter_id = f"{index:04d}"
        summary[chapter_id] = write_glossary_subset(
            glossary_csv,
            source_dir / f"{chapter_id}.txt",
            out_dir / f"{chapter_id}.csv",
            always_include_types=always_include_types,
        )
    return summary


def read_chapter_glossary(
    chapter_id: str,
    *,
    glossary_subset_dir: Path | None,
    fallback_text: str,
) -> str:
    if glossary_subset_dir is None:
        return fallback_text
    subset_path = glossary_subset_dir / f"{chapter_id}.csv"
    if subset_path.exists():
        return subset_path.read_text(encoding="utf-8")
    return fallback_text


def _clean_translation_row(row: dict[str, str]) -> dict[str, str]:
    cleaned = {column: row.get(column, "").strip() for column in TRANSLATION_GLOSSARY_COLUMNS}
    cleaned["note"] = _sanitize_note(cleaned["note"])
    return cleaned


def _sanitize_note(note: str) -> str:
    without_han = HAN_RE.sub("", note)
    without_empty_quotes = without_han.replace("«»", "").replace("“”", "").replace("()", "")
    return WHITESPACE_RE.sub(" ", without_empty_quotes).strip(" ;,")
