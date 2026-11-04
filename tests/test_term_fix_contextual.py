import json
from pathlib import Path

import pytest
from test_project_workflow import _revision_project

from litrelay.project_storage import digest
from litrelay.term_fix_plan import propose_term_fix, validate_replacement


def project_with_paragraphs(tmp_path: Path) -> Path:
    project = _revision_project(tmp_path)
    chapter = project / "work/accepted/0002.txt"
    chapter.write_text(
        "Глава 2. Пример\n\nВ комнате сработало построение.\n\nОно исчезло.\n\n"
        + "Другие события продолжались. " * 12
        + "\n\nДругое построение сияло.\n\n"
        + "Длинное завершение главы. " * 12
        + "\n"
    )
    progress_path = project / "work/progress.json"
    state = json.loads(progress_path.read_text())
    state["chapters"]["2"]["target_sha256"] = digest(chapter.read_text())
    progress_path.write_text(json.dumps(state))
    return project


def test_uncertain_match_expands_only_local_paragraph_and_reviewer_repairs(tmp_path: Path):
    project = project_with_paragraphs(tmp_path)
    calls = []

    def model(payload):
        agent = payload["metadata"]["agent"]
        data = json.loads(payload["input"][1]["content"])
        calls.append((agent, data))
        result = []
        for item in data["matches"]:
            text = item["old"]
            if "\n" in text:
                assert "сработало формация" in item["draft_replacement"]
                replacement = (
                    item["draft_replacement"]
                    .replace("сработало формация", "сработала формация")
                    .replace("Оно исчезло", "Она исчезла")
                )
                uncertain = False
            else:
                replacement = "формация"
                uncertain = "сработало " in item["left"]
            result.append({"id": item["id"], "replacement": replacement, "uncertain": uncertain, "reason": ""})
        return {"output_text": json.dumps({"replacements": result}, ensure_ascii=False)}

    plan = propose_term_fix(project, "海", "формация", "построение", requester=model)
    assert plan["span_mode"] == "context" and plan["span_limit"] == 1200 and plan["match_pattern"] == "построение"
    assert len(plan["patches"]) == 2
    wide, narrow = plan["patches"]
    assert "сработала формация" in wide["replacement"] and "Она исчезла" in wide["replacement"]
    assert narrow["old"] == "построение"
    assert all(not p["uncertain"] for p in plan["patches"])
    assert len(calls) == 3 and calls[2][0] == "terminology-reviewer"
    assert calls[2][1]["previous_target"] == "море"
    assert all(len(p["old"]) <= 1200 for p in plan["patches"])
    assert (project / "work/accepted/0002.txt").read_text().find("сработало построение") >= 0


def test_context_replacement_limits_and_word_default():
    validate_replacement("Первая строка\n\nВторая строка", "ru", span_mode="context", span_limit=1200)
    with pytest.raises(ValueError):
        validate_replacement("я" * 1201, "ru", span_mode="context", span_limit=1200)
    with pytest.raises(ValueError):
        validate_replacement("слово\nслово", "ru")


def test_context_over_1200_rejected_before_context_requests(tmp_path: Path):
    project = project_with_paragraphs(tmp_path)
    chapter = project / "work/accepted/0002.txt"
    chapter.write_text("Глава 2. Пример\n\n" + "Долгое предложение без границы " * 50 + "построение." + "\n")
    progress_path = project / "work/progress.json"
    state = json.loads(progress_path.read_text())
    state["chapters"]["2"]["target_sha256"] = digest(chapter.read_text())
    progress_path.write_text(json.dumps(state))
    calls = []

    def fake(payload):
        data = json.loads(payload["input"][1]["content"])
        calls.append(data)
        return {
            "output_text": json.dumps(
                {
                    "replacements": [
                        {"id": item["id"], "replacement": "формация", "uncertain": True, "reason": "agreement"}
                        for item in data["matches"]
                    ]
                }
            )
        }

    with pytest.raises(ValueError, match="1200"):
        propose_term_fix(project, "海", "формация", "построение", requester=fake)
    assert len(calls) == 2


def test_second_context_pass_reuses_first_without_new_editor(tmp_path: Path):
    project = project_with_paragraphs(tmp_path)
    calls = []

    def fake(payload):
        data = json.loads(payload["input"][1]["content"])
        calls.append(payload["metadata"]["agent"])
        reviews = calls.count("terminology-reviewer")
        rows = []
        for index, item in enumerate(data["matches"]):
            if payload["metadata"]["agent"] == "terminology-editor":
                value = "формация"
                uncertain = index == 0
            elif reviews == 1:
                value = item["draft_replacement"]
                uncertain = index == 0
            elif reviews == 2:
                value = item["draft_replacement"]
                uncertain = index == 1
            else:
                value = item["draft_replacement"]
                uncertain = False
            rows.append({"id": item["id"], "replacement": value, "uncertain": uncertain, "reason": ""})
        return {"output_text": json.dumps({"replacements": rows}, ensure_ascii=False)}

    result = propose_term_fix(project, "海", "формация", "построение", requester=fake)
    assert result["context_pass"] == 2 and all(not item["uncertain"] for item in result["patches"])
    assert calls == ["terminology-editor", "terminology-reviewer", "terminology-reviewer", "terminology-reviewer"]


def test_source_review_sends_only_uncertain_and_preserves_clear_patch(tmp_path: Path):
    from litrelay.term_fix_plan import review_term_fix

    project = project_with_paragraphs(tmp_path)

    def first(payload):
        data = json.loads(payload["input"][1]["content"])
        return {
            "output_text": json.dumps(
                {
                    "replacements": [
                        {"id": item["id"], "replacement": "формация", "uncertain": i == 0, "reason": "referent"}
                        for i, item in enumerate(data["matches"])
                    ]
                },
                ensure_ascii=False,
            )
        }

    draft = propose_term_fix(project, "海", "формация", "построение", requester=first, allow_contextual_fallback=False)
    calls = []

    def resolve(payload):
        data = json.loads(payload["input"][1]["content"])
        calls.append(data)
        return {
            "output_text": json.dumps(
                {
                    "replacements": [
                        {"id": item["id"], "replacement": "формация", "uncertain": False, "reason": "source clarified"}
                        for item in data["matches"]
                    ]
                },
                ensure_ascii=False,
            ),
            "usage": {"input_tokens": 20},
        }

    result = review_term_fix(project, Path(draft["plan_path"]), requester=resolve, source_for_uncertain=True)
    assert len(calls) == 1 and len(calls[0]["matches"]) == 1
    assert calls[0]["matches"][0]["source_evidence"] == (project / "input/source/0002.txt").read_text()
    assert result["patches"][1] == draft["patches"][1]
    assert all(not item["uncertain"] for item in result["patches"])
    assert result["source_review"] and result["source_review_usage"] == [{"input_tokens": 20}]
    draft["patches"][1]["replacement"] = "Непроверенная подмена"
    Path(draft["plan_path"]).write_text(json.dumps(draft))
    calls.clear()
    with pytest.raises(ValueError, match="unchanged independently reviewed"):
        review_term_fix(project, Path(draft["plan_path"]), requester=resolve, source_for_uncertain=True)
    assert not calls
