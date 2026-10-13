from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

UNSUPPORTED_MARKERS = ("не подтверждён", "не подтвержден", "unsupported", "не уверен")


@dataclass(frozen=True)
class ReconcileFlag:
    source: str
    current_target: str
    reasons: list[str]


def flag_glossary_terms(
    glossary_csv: Path,
    published_ru_dir: Path,
    *,
    confidence_threshold: float = 0.80,
    unsupported_markers: tuple[str, ...] = UNSUPPORTED_MARKERS,
) -> list[ReconcileFlag]:
    corpus = _load_corpus(published_ru_dir)
    flags: list[ReconcileFlag] = []
    for row in _read_rows(glossary_csv):
        source = (row.get("source") or "").strip()
        target = (row.get("target_ru") or "").strip()
        if not source or not target:
            continue
        strong: list[str] = []
        if _confidence(row.get("confidence", "")) < confidence_threshold:
            strong.append("low_confidence")
        if any(marker in row.get("note", "").lower() for marker in unsupported_markers):
            strong.append("unsupported_note")
        if not strong:
            continue
        reasons = list(strong)
        if target not in corpus:
            reasons.append("absent_from_reference")
        flags.append(ReconcileFlag(source=source, current_target=target, reasons=reasons))
    return flags


def _load_corpus(published_ru_dir: Path) -> str:
    parts = [path.read_text(encoding="utf-8") for path in sorted(published_ru_dir.glob("*.txt"))]
    return "\n".join(parts)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _confidence(value: str) -> float:
    try:
        return float(value.strip())
    except ValueError:
        return 0.0


OVERRIDE_COLUMNS = ("source", "target_ru", "type", "note", "confidence")


RECONCILE_SYSTEM = """You are a Chinese-to-Russian terminology reconciler.

You receive an established Russian translation reference (recent published chapters) and a list of glossary terms flagged as possibly mistranslated.
For each flagged source term, find the established Russian term the reference actually uses for that concept and prefer it over the current mapping.
Only propose a term you can support from the reference. If the reference does not establish a term, repeat the current target and lower the confidence.
Do not use commas inside CSV fields; replace internal commas with semicolons.

Return CSV only. Do not include markdown.
source,target_ru,type,note,confidence"""


def build_reconcile_batch_task(
    flags: list[ReconcileFlag],
    published_ru_dir: Path,
    *,
    reference_chapters: int = 15,
) -> dict:
    flagged = [
        {"source": flag.source, "current_target": flag.current_target, "reasons": flag.reasons} for flag in flags
    ]
    return {
        "custom_id": "reconcile-batch",
        "agent": "glossary-extractor",
        "system": RECONCILE_SYSTEM,
        "input": {
            "established_reference": _recent_reference(published_ru_dir, reference_chapters),
            "flagged_terms": flagged,
        },
        "expected_output": {"format": "csv", "header": ",".join(OVERRIDE_COLUMNS)},
    }


def _recent_reference(published_ru_dir: Path, reference_chapters: int) -> str:
    paths = sorted(published_ru_dir.glob("*.txt"))[-reference_chapters:]
    return "\n\n".join(path.read_text(encoding="utf-8") for path in paths)


def write_reconcile_overrides(results_jsonl: Path, out_csv: Path) -> int:
    rows: list[dict[str, str]] = []
    for result in _read_jsonl(results_jsonl):
        if result.get("status") != "completed":
            continue
        reader = csv.DictReader(io.StringIO(str(result.get("output", "")).strip()))
        if reader.fieldnames is None or "source" not in reader.fieldnames:
            continue
        for row in reader:
            source = (row.get("source") or "").strip()
            target = (row.get("target_ru") or "").strip()
            if not source or not target:
                continue
            rows.append({column: (row.get(column) or "").strip() for column in OVERRIDE_COLUMNS})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(OVERRIDE_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            if line.strip():
                rows.append(json.loads(line))
    return rows
