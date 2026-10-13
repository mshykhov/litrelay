import json
from pathlib import Path

from litrelay.qa_gate import evaluate_qa_results, format_qa_gate_report


def _qa_line(chapter_id: str, meaning: float, terminology: float, style: float, omission: float) -> str:
    output = {
        "chapter_id": chapter_id,
        "meaning_score": meaning,
        "terminology_score": terminology,
        "style_score": style,
        "omission_score": omission,
        "verdict": "needs_revision",
        "strengths": [],
        "issues": [],
        "missing_or_changed_facts": [],
        "recommended_action": "",
    }
    return json.dumps(
        {
            "custom_id": f"qa-{chapter_id}",
            "agent": "translation-qa",
            "status": "completed",
            "output": json.dumps(output, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


def test_evaluate_qa_results_passes_on_scores_despite_llm_verdict(tmp_path: Path) -> None:
    results = tmp_path / "qa.results.jsonl"
    results.write_text(
        _qa_line("0652", 93, 91, 86, 94) + "\n" + _qa_line("0653", 80, 70, 60, 75) + "\n",
        encoding="utf-8",
    )

    report = evaluate_qa_results(results)

    assert report.passed == 1
    assert report.failed == 1
    assert not report.ok
    decisions = {d.chapter_id: d for d in report.decisions}
    assert decisions["0652"].verdict == "pass"
    assert decisions["0653"].verdict == "needs_revision"
    assert decisions["0653"].failed_metrics == ["meaning_score", "terminology_score", "style_score", "omission_score"]
    assert "ok=false" in format_qa_gate_report(report)


def test_evaluate_qa_results_normalizes_zero_to_one_scale(tmp_path: Path) -> None:
    results = tmp_path / "qa.results.jsonl"
    results.write_text(_qa_line("0653", 0.92, 0.91, 0.86, 0.94) + "\n", encoding="utf-8")

    report = evaluate_qa_results(results)

    assert report.passed == 1
    assert report.decisions[0].verdict == "pass"
    assert report.decisions[0].meaning_score == 92.0


def test_expected_qa_cannot_silently_skip_missing_or_failed_results(tmp_path: Path) -> None:
    results = tmp_path / "qa.jsonl"
    results.write_text(
        _qa_line("0001", 95, 95, 95, 95)
        + "\n"
        + json.dumps({"custom_id": "translation-qa-0002", "status": "failed", "output": None})
        + "\n"
    )
    report = evaluate_qa_results(results, expected_chapter_ids={"0001", "0002", "0003"})
    assert not report.ok
    assert report.failed == 2
    assert {d.chapter_id for d in report.decisions if d.verdict != "pass"} == {"0002", "0003"}


def test_nonfinite_scores_and_empty_results_cannot_pass(tmp_path: Path) -> None:
    results = tmp_path / "qa.jsonl"
    results.write_text("")
    assert not evaluate_qa_results(results).ok
    results.write_text(_qa_line("0001", float("nan"), 95, 95, 95) + "\n")
    assert not evaluate_qa_results(results).ok


def test_swapped_chapter_ids_cannot_satisfy_expected_qa_coverage(tmp_path: Path) -> None:
    results = tmp_path / "qa.jsonl"
    rows = []
    for actual, claimed in [("0001", "0002"), ("0002", "0001")]:
        row = json.loads(_qa_line(claimed, 95, 95, 95, 95))
        row["custom_id"] = "translation-qa-" + actual
        rows.append(json.dumps(row))
    results.write_text("\n".join(rows))
    assert not evaluate_qa_results(results, expected_chapter_ids={"0001", "0002"}).ok
