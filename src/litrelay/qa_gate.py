from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLDS: dict[str, float] = {
    "meaning_score": 85.0,
    "terminology_score": 85.0,
    "style_score": 75.0,
    "omission_score": 88.0,
}


@dataclass(frozen=True)
class QaDecision:
    chapter_id: str
    verdict: str
    meaning_score: float
    terminology_score: float
    style_score: float
    omission_score: float
    failed_metrics: list[str]


@dataclass(frozen=True)
class QaGateReport:
    results_jsonl: Path
    decisions: list[QaDecision]
    passed: int
    failed: int

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.passed > 0


def evaluate_qa_results(
    results_jsonl: Path,
    *,
    thresholds: dict[str, float] | None = None,
    expected_chapter_ids: set[str] | None = None,
) -> QaGateReport:
    limits = thresholds or DEFAULT_THRESHOLDS
    decisions: list[QaDecision] = []
    for result in _read_jsonl(results_jsonl):
        if result.get("status") != "completed":
            continue
        try:
            output = json.loads(str(result.get("output", "")))
        except json.JSONDecodeError:
            continue
        if not isinstance(output, dict):
            continue
        chapter_id = str(output.get("chapter_id", ""))
        if expected_chapter_ids is not None and result.get("custom_id") not in {
            f"translation-qa-{chapter_id}",
            f"qa-{chapter_id}",
        }:
            continue
        scores = normalized_scores(output, limits)
        failed_metrics = [metric for metric, limit in limits.items() if scores[metric] < limit]
        decisions.append(
            QaDecision(
                chapter_id=str(output.get("chapter_id", "")),
                verdict="pass" if not failed_metrics else "needs_revision",
                meaning_score=scores["meaning_score"],
                terminology_score=scores["terminology_score"],
                style_score=scores["style_score"],
                omission_score=scores["omission_score"],
                failed_metrics=failed_metrics,
            )
        )
    if expected_chapter_ids is not None:
        counts = {cid: sum(d.chapter_id == cid for d in decisions) for cid in expected_chapter_ids}
        decisions = [d for d in decisions if counts.get(d.chapter_id) == 1]
        for chapter_id, count in sorted(counts.items()):
            if count != 1:
                decisions.append(QaDecision(chapter_id, "needs_revision", 0, 0, 0, 0, ["missing_or_duplicate_result"]))
    passed = sum(1 for d in decisions if d.verdict == "pass")
    return QaGateReport(
        results_jsonl=results_jsonl,
        decisions=decisions,
        passed=passed,
        failed=len(decisions) - passed,
    )


def normalized_scores(output: dict, limits: dict[str, float]) -> dict[str, float]:
    scores = {}
    for metric in limits:
        try:
            value = float(output.get(metric, 0))
        except (TypeError, ValueError):
            value = 0
        scores[metric] = value if math.isfinite(value) and 0 <= value <= 100 else 0
    if scores and max(scores.values()) <= 1:
        scores = {metric: value * 100 for metric, value in scores.items()}
    return scores


def scores_pass_qa(output: dict, thresholds: dict[str, float] | None = None) -> bool:
    limits = thresholds or DEFAULT_THRESHOLDS
    scores = normalized_scores(output, limits)
    return all(scores[metric] >= limit for metric, limit in limits.items())


def format_qa_gate_report(report: QaGateReport) -> str:
    lines = [
        f"results_jsonl={report.results_jsonl}",
        f"passed={report.passed}",
        f"failed={report.failed}",
        f"ok={str(report.ok).lower()}",
    ]
    for decision in report.decisions:
        lines.append(
            f"{decision.chapter_id}: verdict={decision.verdict} failed={','.join(decision.failed_metrics) or '-'}"
        )
    return "\n".join(lines)


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            if line.strip():
                rows.append(json.loads(line))
    return rows
