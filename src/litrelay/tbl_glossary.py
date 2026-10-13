from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _GlossaryRow:
    source_term: str
    translated_term: str
    category: str
    confidence: float
    order: int


def write_tbl_glossary_csv(glossary_csv: Path, out_csv: Path) -> int:
    rows_by_source: dict[str, _GlossaryRow] = {}

    with glossary_csv.open(encoding="utf-8", newline="") as glossary_file:
        reader = csv.DictReader(glossary_file)
        for order, row in enumerate(reader):
            source_term = (row.get("source") or row.get("source_term") or "").strip()
            translated_term = (row.get("target_ru") or row.get("translated_term") or "").strip()
            if not source_term or not translated_term:
                continue

            candidate = _GlossaryRow(
                source_term=source_term,
                translated_term=translated_term,
                category=(row.get("type") or row.get("category") or "").strip(),
                confidence=_parse_confidence(row.get("confidence")),
                order=order,
            )
            current = rows_by_source.get(source_term)
            if current is None or candidate.confidence > current.confidence:
                rows_by_source[source_term] = candidate

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows_by_source.values(), key=lambda item: item.order)
    with out_csv.open("w", encoding="utf-8", newline="") as out_file:
        writer = csv.DictWriter(out_file, fieldnames=["source_term", "translated_term", "category"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "source_term": row.source_term,
                    "translated_term": row.translated_term,
                    "category": row.category,
                }
            )
    return len(rows)


def _parse_confidence(value: str | None) -> float:
    if value is None or not value.strip():
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0
