from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GLOSSARY_HEADER = ["source", "target_ru", "type", "note", "confidence"]
ALIGNMENT_REQUIRED_FIELDS = {
    "chapter_id",
    "verdict",
    "confidence",
    "evidence",
    "issues",
    "recommended_action",
}
ALIGNMENT_VERDICTS = ("aligned", "misaligned", "uncertain")


@dataclass(frozen=True)
class AgentResultReport:
    kind: str
    expected: int
    present: int
    completed: int
    errors: int
    missing: int
    invalid_outputs: int
    verdict_counts: dict[str, int] = field(default_factory=dict)
    non_aligned: int = 0

    @property
    def ok(self) -> bool:
        return self.missing == 0 and self.errors == 0 and self.invalid_outputs == 0 and self.non_aligned == 0


def validate_agent_results(tasks_jsonl: Path, results_jsonl: Path, *, kind: str) -> AgentResultReport:
    expected_ids = _read_task_ids(tasks_jsonl)
    results = _read_results(results_jsonl)
    present_ids = {str(result.get("custom_id")) for result in results}
    completed = 0
    errors = 0
    invalid_outputs = 0
    verdict_counts = {verdict: 0 for verdict in ALIGNMENT_VERDICTS} if kind == "alignment" else {}

    for result in results:
        if result.get("status") != "completed":
            errors += 1
            continue
        completed += 1
        output = str(result.get("output", ""))
        if kind == "alignment":
            audit = _parse_alignment_output(output)
            if audit is None:
                invalid_outputs += 1
                continue
            verdict_counts[str(audit["verdict"])] += 1
        elif kind == "glossary":
            if _parse_glossary_output(output) is None:
                invalid_outputs += 1
        else:
            raise ValueError(f"Unsupported result kind: {kind}")

    non_aligned = verdict_counts.get("misaligned", 0) + verdict_counts.get("uncertain", 0)
    return AgentResultReport(
        kind=kind,
        expected=len(expected_ids),
        present=len(present_ids),
        completed=completed,
        errors=errors,
        missing=len(expected_ids - present_ids),
        invalid_outputs=invalid_outputs,
        verdict_counts=verdict_counts,
        non_aligned=non_aligned,
    )


def format_agent_result_report(report: AgentResultReport) -> str:
    lines = [
        f"kind={report.kind}",
        f"expected={report.expected}",
        f"present={report.present}",
        f"completed={report.completed}",
        f"errors={report.errors}",
        f"missing={report.missing}",
        f"invalid_outputs={report.invalid_outputs}",
    ]
    if report.kind == "alignment":
        lines.append("verdicts=" + ",".join(f"{verdict}:{count}" for verdict, count in report.verdict_counts.items()))
        lines.append(f"non_aligned={report.non_aligned}")
    lines.append(f"ok={str(report.ok).lower()}")
    return "\n".join(lines)


def merge_glossary_results(results_jsonl: Path, out_csv: Path) -> int:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_csv.open("w", encoding="utf-8", newline="") as out_file:
        writer = csv.writer(out_file)
        writer.writerow(["chapter_id", *GLOSSARY_HEADER])
        for result in _read_results(results_jsonl):
            if result.get("status") != "completed":
                continue
            chapter_id = _chapter_id_from_custom_id(str(result.get("custom_id", "")))
            rows = _parse_glossary_output(str(result.get("output", "")))
            if rows is None:
                continue
            for row in rows:
                writer.writerow([chapter_id, *row])
                written += 1
    return written


def _read_task_ids(tasks_jsonl: Path) -> set[str]:
    return {str(row["custom_id"]) for row in _read_jsonl(tasks_jsonl)}


def _read_results(results_jsonl: Path) -> list[dict[str, Any]]:
    if not results_jsonl.exists():
        return []
    return _read_jsonl(results_jsonl)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _parse_alignment_output(output: str) -> dict[str, Any] | None:
    try:
        audit = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(audit, dict):
        return None
    if set(audit) != ALIGNMENT_REQUIRED_FIELDS:
        return None
    if audit["verdict"] not in ALIGNMENT_VERDICTS:
        return None
    if not isinstance(audit["confidence"], int | float):
        return None
    if not isinstance(audit["evidence"], list) or not isinstance(audit["issues"], list):
        return None
    return audit


def _parse_glossary_output(output: str) -> list[list[str]] | None:
    rows = list(csv.reader(io.StringIO(output)))
    if not rows or rows[0] != GLOSSARY_HEADER:
        return None
    normalized_rows = []
    for row in rows[1:]:
        if not row or all(not cell.strip() for cell in row):
            continue
        normalized = _normalize_glossary_row(row)
        if normalized is None:
            return None
        normalized_rows.append(normalized)
    return normalized_rows


def _normalize_glossary_row(row: list[str]) -> list[str] | None:
    if len(row) == len(GLOSSARY_HEADER):
        return [cell.strip() for cell in row]
    if len(row) > len(GLOSSARY_HEADER):
        source = row[0].strip()
        target_ru = row[1].strip()
        term_type = row[2].strip()
        note = "; ".join(part.strip() for part in row[3:-1] if part.strip())
        confidence = row[-1].strip()
        return [source, target_ru, term_type, note, confidence]
    return None


def _chapter_id_from_custom_id(custom_id: str) -> str:
    return custom_id.rsplit("-", 1)[-1]
