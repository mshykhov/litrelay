from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

CANDIDATE_COLUMNS = ("source", "target_ru", "type", "note", "confidence", "chapter_id")


@dataclass(frozen=True)
class GlossaryFeedbackSummary:
    candidates_written: int
    rows_parsed: int
    rows_skipped: int


def write_glossary_candidates(results_jsonl: Path, out_csv: Path) -> GlossaryFeedbackSummary:
    seen: dict[tuple[str, str], dict[str, str]] = {}
    rows_parsed = 0
    rows_skipped = 0
    for result in _read_jsonl(results_jsonl):
        if result.get("status") != "completed":
            continue
        chapter_id = str(result.get("custom_id", "")).split("-")[-1].strip()
        for row in _parse_csv_output(str(result.get("output", ""))):
            source = (row.get("source") or "").strip()
            target = (row.get("target_ru") or "").strip()
            if not source or not target:
                rows_skipped += 1
                continue
            rows_parsed += 1
            key = (source, target)
            if key in seen:
                continue
            seen[key] = {
                "source": source,
                "target_ru": target,
                "type": (row.get("type") or "").strip(),
                "note": (row.get("note") or "").strip(),
                "confidence": (row.get("confidence") or "").strip(),
                "chapter_id": chapter_id,
            }

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(CANDIDATE_COLUMNS))
        writer.writeheader()
        writer.writerows(seen.values())

    return GlossaryFeedbackSummary(
        candidates_written=len(seen),
        rows_parsed=rows_parsed,
        rows_skipped=rows_skipped,
    )


def _parse_csv_output(output: str) -> list[dict[str, str]]:
    text = output.strip()
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "source" not in reader.fieldnames:
        return []
    return list(reader)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            if line.strip():
                rows.append(json.loads(line))
    return rows
