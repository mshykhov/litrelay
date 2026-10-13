import json
from pathlib import Path

from litrelay.revision import (
    apply_revisions,
    build_revision_task,
    write_revision_tasks,
)


def _tr_line(chapter_id, translation, scores=None):
    qa = {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []}
    out = {"chapter_id": chapter_id, "translation": translation, "qa": qa}
    return json.dumps(
        {
            "custom_id": f"translate-{chapter_id}",
            "agent": "translation-agent",
            "status": "completed",
            "output": json.dumps(out, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


def _qa_line(chapter_id, m, t, s, o, issues=None):
    out = {
        "chapter_id": chapter_id,
        "meaning_score": m,
        "terminology_score": t,
        "style_score": s,
        "omission_score": o,
        "verdict": "needs_revision",
        "strengths": [],
        "issues": issues or ["term drift"],
        "missing_or_changed_facts": [],
        "recommended_action": "fix terms",
    }
    return json.dumps(
        {
            "custom_id": f"translation-qa-{chapter_id}",
            "agent": "translation-qa",
            "status": "completed",
            "output": json.dumps(out, ensure_ascii=False),
        },
        ensure_ascii=False,
    )


def test_build_revision_task_includes_previous_and_issues() -> None:
    task = build_revision_task(
        chapter_id="0674",
        source_text="第674章",
        previous_translation="Глава 674 старый",
        qa={"issues": ["term drift"], "missing_or_changed_facts": [], "recommended_action": "fix", "meaning_score": 80},
        glossary_csv="source,target_ru\n",
    )
    assert task["custom_id"] == "translate-0674"
    assert task["agent"] == "translation-agent"
    assert task["expected_output"]["format"] == "translation_json"
    assert task["input"]["previous_translation"] == "Глава 674 старый"
    assert task["input"]["qa_issues"] == ["term drift"]


def test_write_revision_tasks_only_for_failed(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "0674.txt").write_text("第674章", encoding="utf-8")
    (src / "0675.txt").write_text("第675章", encoding="utf-8")
    tr = tmp_path / "tr.jsonl"
    tr.write_text(_tr_line("0674", "old674") + "\n" + _tr_line("0675", "old675") + "\n", encoding="utf-8")
    qa = tmp_path / "qa.jsonl"
    qa.write_text(_qa_line("0674", 80, 72, 74, 90) + "\n" + _qa_line("0675", 92, 90, 85, 95) + "\n", encoding="utf-8")
    gl = tmp_path / "g.csv"
    gl.write_text("source,target_ru\n", encoding="utf-8")
    out = tmp_path / "rev.tasks.jsonl"

    n = write_revision_tasks(
        source_dir=src,
        translation_results_jsonl=tr,
        qa_results_jsonl=qa,
        failed_chapter_ids=["0674"],
        glossary_csv=gl,
        out_jsonl=out,
    )

    assert n == 1
    task = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert task["input"]["chapter_id"] == "0674"
    assert task["input"]["previous_translation"] == "old674"


def test_apply_revisions_keeps_better(tmp_path: Path) -> None:
    tr = tmp_path / "tr.jsonl"
    tr.write_text(_tr_line("0674", "old674") + "\n" + _tr_line("0675", "old675") + "\n", encoding="utf-8")
    qa = tmp_path / "qa.jsonl"
    qa.write_text(_qa_line("0674", 80, 72, 74, 90) + "\n" + _qa_line("0675", 80, 72, 74, 90) + "\n", encoding="utf-8")
    rev = tmp_path / "rev.jsonl"
    rev.write_text(_tr_line("0674", "new674") + "\n" + _tr_line("0675", "new675") + "\n", encoding="utf-8")
    # 0674 revised improves; 0675 revised is worse
    revqa = tmp_path / "revqa.jsonl"
    revqa.write_text(
        _qa_line("0674", 92, 90, 85, 95) + "\n" + _qa_line("0675", 60, 60, 60, 60) + "\n", encoding="utf-8"
    )

    keep = apply_revisions(
        translation_results_jsonl=tr, qa_results_jsonl=qa, revised_results_jsonl=rev, revised_qa_jsonl=revqa
    )

    assert keep["0674"] is True
    assert keep.get("0675", False) is False
    trs = {
        json.loads(json.loads(line)["output"])["chapter_id"]: json.loads(json.loads(line)["output"])["translation"]
        for line in tr.read_text(encoding="utf-8").splitlines()
    }
    assert trs["0674"] == "new674"  # improved -> replaced
    assert trs["0675"] == "old675"  # worse -> kept original


def test_passing_revision_beats_higher_average_that_fails_one_required_metric(tmp_path: Path) -> None:
    tr = tmp_path / "tr.jsonl"
    qa = tmp_path / "qa.jsonl"
    rev = tmp_path / "rev.jsonl"
    revqa = tmp_path / "revqa.jsonl"
    for p, output, custom in [
        (tr, {"chapter_id": "0001", "translation": "old"}, "translate-0001"),
        (rev, {"chapter_id": "0001", "translation": "new"}, "translate-0001"),
        (
            qa,
            {
                "chapter_id": "0001",
                "meaning_score": 100,
                "terminology_score": 100,
                "style_score": 74,
                "omission_score": 100,
            },
            "translation-qa-0001",
        ),
        (
            revqa,
            {
                "chapter_id": "0001",
                "meaning_score": 91,
                "terminology_score": 90,
                "style_score": 80,
                "omission_score": 96,
            },
            "translation-qa-0001",
        ),
    ]:
        p.write_text(json.dumps({"custom_id": custom, "status": "completed", "output": json.dumps(output)}) + "\n")
    keep = apply_revisions(
        translation_results_jsonl=tr,
        qa_results_jsonl=qa,
        revised_results_jsonl=rev,
        revised_qa_jsonl=revqa,
        thresholds={"meaning_score": 90, "terminology_score": 85, "style_score": 75, "omission_score": 95},
    )
    assert keep["0001"]
