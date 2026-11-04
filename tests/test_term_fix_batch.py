import json
from pathlib import Path

import pytest
from test_term_fix_apply import PATTERN, prepared

from litrelay import term_fix_batch
from litrelay.project_workflow import project_status
from litrelay.term_fix_batch import TermFixBatchError, fix_terms

RULES = [
    {"source_term": "修士", "target": "культиватор", "pattern": PATTERN},
    {"source_term": "修士走", "target": "адепт", "pattern": r"(?i)\bкультиватор[а-яё]*\b"},
]


def editor(calls, *, fail_second=False):
    def request(payload):
        data = json.loads(payload["input"][1]["content"])
        calls.append((payload["metadata"]["agent"], data["source_term"]))
        matches = data["matches"]
        replacements = []
        for item in matches:
            if data["source_term"] == "修士":
                word = (
                    "Культиватор"
                    if item["old"][0].isupper()
                    else "культиватором"
                    if item["left"].endswith("был ")
                    else "культиваторам"
                )
            else:
                word = "Адепт" if item["old"][0].isupper() else "адепт"
            replacements.append(
                {
                    "id": item["id"],
                    "replacement": word,
                    "uncertain": fail_second and data["source_term"] == "修士走",
                    "reason": "",
                }
            )
        return {"output_text": json.dumps({"replacements": replacements}, ensure_ascii=False)}

    return request


def test_sequential_apply_plans_second_after_first_changes_fingerprint(tmp_path: Path, monkeypatch):
    project, _ = prepared(tmp_path)
    actual_plan, actual_apply = term_fix_batch.propose_term_fix, term_fix_batch.apply_term_fix
    sequence = []

    def plan(*args, **kwargs):
        result = actual_plan(*args, **kwargs)
        sequence.append(("plan", result["source_term"], result["project_fingerprint"]))
        return result

    def apply(*args, **kwargs):
        result = actual_apply(*args, **kwargs)
        sequence.append(("apply", result["source_term"], result["after_fingerprint"]))
        return result

    monkeypatch.setattr(term_fix_batch, "propose_term_fix", plan)
    monkeypatch.setattr(term_fix_batch, "apply_term_fix", apply)
    calls = []
    result = fix_terms(project, RULES, apply=True, requester=editor(calls))
    assert [item[:2] for item in sequence] == [
        ("plan", "修士"),
        ("apply", "修士"),
        ("plan", "修士走"),
        ("apply", "修士走"),
    ]
    assert sequence[1][2] == sequence[2][2] and sequence[0][2] != sequence[2][2]
    assert result["completed_source_terms"] == ["修士", "修士走"]
    assert all(item["reviewed"] and item["applied"] and "patches" not in item for item in result["plans"])
    assert project_status(project)["complete"] and "адепт" in (project / "output/book.txt").read_text().lower()
    assert [agent for agent, _ in calls] == ["terminology-editor", "terminology-reviewer"] * 2


@pytest.mark.parametrize("bad", ["[", "(?=x)", "", "duplicate", "absent"])
def test_invalid_rule_two_rejects_before_any_request(tmp_path: Path, bad: str):
    project, _ = prepared(tmp_path)
    before = project_status(project)["fingerprint"]
    rules = [dict(rule) for rule in RULES]
    if bad == "duplicate":
        rules[1]["source_term"] = rules[0]["source_term"]
    elif bad == "absent":
        rules[1]["source_term"] = "不存在源詞"
    else:
        rules[1]["pattern"] = bad
    calls = []
    with pytest.raises(ValueError):
        fix_terms(project, rules, apply=True, requester=editor(calls))
    assert calls == [] and project_status(project)["fingerprint"] == before


def test_second_failure_keeps_first_and_reports_completed(tmp_path: Path):
    project, _ = prepared(tmp_path)
    with pytest.raises(TermFixBatchError) as error:
        fix_terms(project, RULES, apply=True, requester=editor([], fail_second=True))
    assert error.value.completed_source_terms == ["修士"]
    assert error.value.source_term == "修士走" and "修士" in str(error.value)
    assert len(error.value.plans) == 2 and error.value.plans[0]["applied"]
    assert error.value.plans[1]["uncertain"] > 0
    assert "культиватор" in (project / "output/book.txt").read_text().lower()
    assert project_status(project)["complete"]
