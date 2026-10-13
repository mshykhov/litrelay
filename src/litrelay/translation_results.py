from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TranslationResultReport:
    expected: int
    present: int
    completed: int
    errors: int
    missing: int
    invalid_outputs: int

    @property
    def ok(self) -> bool:
        return self.missing == 0 and self.errors == 0 and self.invalid_outputs == 0


def validate_translation_results(tasks_jsonl: Path, results_jsonl: Path) -> TranslationResultReport:
    expected_ids = _read_ids(tasks_jsonl)
    results = _read_jsonl(results_jsonl) if results_jsonl.exists() else []
    present_ids = {str(row.get("custom_id")) for row in results}
    completed = 0
    errors = 0
    invalid_outputs = 0

    for result in results:
        if result.get("status") != "completed":
            errors += 1
            continue
        completed += 1
        output = _parse_translation_output(str(result.get("output", "")))
        if output is None or str(result.get("custom_id")) != f"translate-{output['chapter_id']}":
            invalid_outputs += 1

    return TranslationResultReport(
        expected=len(expected_ids),
        present=len(present_ids),
        completed=completed,
        errors=errors,
        missing=len(expected_ids - present_ids),
        invalid_outputs=invalid_outputs,
    )


def format_translation_result_report(report: TranslationResultReport) -> str:
    return "\n".join(
        [
            f"expected={report.expected}",
            f"present={report.present}",
            f"completed={report.completed}",
            f"errors={report.errors}",
            f"missing={report.missing}",
            f"invalid_outputs={report.invalid_outputs}",
            f"ok={str(report.ok).lower()}",
        ]
    )


def export_translation_results(results_jsonl: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for result in _read_jsonl(results_jsonl):
        if result.get("status") != "completed":
            continue
        output = _parse_translation_output(str(result.get("output", "")))
        if output is None:
            continue
        chapter_id = str(output["chapter_id"])
        translation = str(output["translation"]).rstrip() + "\n"
        (out_dir / f"{chapter_id}.txt").write_text(translation, encoding="utf-8")
        count += 1
    return count


def _parse_translation_output(output: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if not isinstance(parsed.get("chapter_id"), str) or not re.fullmatch(r"[0-9]{4,8}", parsed["chapter_id"]):
        return None
    if not isinstance(parsed.get("translation"), str) or not parsed["translation"].strip():
        return None
    qa = parsed.get("qa")
    if not isinstance(qa, dict):
        return None
    required_qa = {
        "terminology_checked": bool,
        "omission_risk": str,
        "style_match": str,
        "issues": list,
    }
    for key, expected_type in required_qa.items():
        if not isinstance(qa.get(key), expected_type):
            return None
    return parsed


def _read_ids(path: Path) -> set[str]:
    return {str(row["custom_id"]) for row in _read_jsonl(path)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8", errors="replace") as jsonl_file:
        for line in jsonl_file:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
