import json
from pathlib import Path

from litrelay.agent_results import merge_glossary_results, validate_agent_results


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_validate_alignment_results_flags_uncertain_verdict(tmp_path: Path) -> None:
    tasks_jsonl = tmp_path / "tasks.jsonl"
    results_jsonl = tmp_path / "results.jsonl"
    _write_jsonl(
        tasks_jsonl,
        [
            {"custom_id": "alignment-0001"},
            {"custom_id": "alignment-0002"},
        ],
    )
    _write_jsonl(
        results_jsonl,
        [
            {
                "custom_id": "alignment-0001",
                "status": "completed",
                "output": json.dumps(
                    {
                        "chapter_id": "0001",
                        "verdict": "aligned",
                        "confidence": 0.98,
                        "evidence": ["same event"],
                        "issues": [],
                        "recommended_action": "use",
                    }
                ),
            },
            {
                "custom_id": "alignment-0002",
                "status": "completed",
                "output": json.dumps(
                    {
                        "chapter_id": "0002",
                        "verdict": "uncertain",
                        "confidence": 0.52,
                        "evidence": ["weak match"],
                        "issues": ["title mismatch"],
                        "recommended_action": "recheck source",
                    }
                ),
            },
        ],
    )

    report = validate_agent_results(tasks_jsonl, results_jsonl, kind="alignment")

    assert report.expected == 2
    assert report.present == 2
    assert report.invalid_outputs == 0
    assert report.verdict_counts == {"aligned": 1, "misaligned": 0, "uncertain": 1}
    assert report.non_aligned == 1
    assert not report.ok


def test_validate_and_merge_glossary_results(tmp_path: Path) -> None:
    tasks_jsonl = tmp_path / "tasks.jsonl"
    results_jsonl = tmp_path / "results.jsonl"
    out_csv = tmp_path / "glossary.csv"
    _write_jsonl(tasks_jsonl, [{"custom_id": "glossary-0001"}])
    _write_jsonl(
        results_jsonl,
        [
            {
                "custom_id": "glossary-0001",
                "status": "completed",
                "output": "source,target_ru,type,note,confidence\n耐瑟瑞尔,Нетерил,place,,0.99\n",
            }
        ],
    )

    report = validate_agent_results(tasks_jsonl, results_jsonl, kind="glossary")
    merge_count = merge_glossary_results(results_jsonl, out_csv)

    assert report.ok
    assert report.invalid_outputs == 0
    assert merge_count == 1
    assert out_csv.read_text(encoding="utf-8") == (
        "chapter_id,source,target_ru,type,note,confidence\n0001,耐瑟瑞尔,Нетерил,place,,0.99\n"
    )


def test_glossary_results_allow_recoverable_commas_in_note(tmp_path: Path) -> None:
    tasks_jsonl = tmp_path / "tasks.jsonl"
    results_jsonl = tmp_path / "results.jsonl"
    out_csv = tmp_path / "glossary.csv"
    _write_jsonl(tasks_jsonl, [{"custom_id": "glossary-0003"}])
    _write_jsonl(
        results_jsonl,
        [
            {
                "custom_id": "glossary-0003",
                "status": "completed",
                "output": (
                    "source,target_ru,type,note,confidence\n"
                    "紫色宇宙,фиолетовая вселенная,cosmology,Опасная вселенная, через которую проходит герой,0.99\n"
                ),
            }
        ],
    )

    report = validate_agent_results(tasks_jsonl, results_jsonl, kind="glossary")
    merge_count = merge_glossary_results(results_jsonl, out_csv)

    assert report.ok
    assert merge_count == 1
    assert "Опасная вселенная; через которую проходит герой" in out_csv.read_text(encoding="utf-8")
