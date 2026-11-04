import json
from pathlib import Path

import pytest
from test_project_workflow import _revision_project

from litrelay.project_storage import digest
from litrelay.term_fix_plan import propose_term_fix, review_term_fix


def project_with_matches(tmp_path: Path) -> Path:
    project = _revision_project(tmp_path)
    chapter = project / "work/accepted/0002.txt"
    chapter.write_text(
        "Глава 2. Свет\n\n" + "Здесь обычный текст. " * 35 + "Старец пошёл к Старцу. " + "Дальше обычный текст. " * 35
    )
    path = project / "work/progress.json"
    progress = json.loads(path.read_text())
    progress["chapters"]["2"]["target_sha256"] = digest(chapter.read_text())
    path.write_text(json.dumps(progress))
    return project


def requester(calls, mode="ok"):
    def fake(payload):
        calls.append(payload)
        content = json.loads(payload["input"][1]["content"])
        rows = []
        for match in content["matches"]:
            replacement = "Мудрецу" if match["old"] == "Старцу" else "Мудрец"
            rows.append(
                {"id": match["id"], "replacement": replacement, "uncertain": mode == "uncertain", "reason": "контекст"}
            )
        if mode == "missing":
            rows.pop()
        if mode == "extra":
            rows.append({"id": "unknown", "replacement": "Ошибка", "uncertain": False, "reason": ""})
        if mode == "duplicate":
            rows.append(rows[0])
        if mode == "invalid":
            rows[0]["replacement"] = "汉字"
        return {"output_text": json.dumps({"replacements": rows}, ensure_ascii=False), "usage": {"input_tokens": 10}}

    return fake


def test_plan_uses_only_short_context_and_inflected_replacements(tmp_path: Path):
    project = project_with_matches(tmp_path)
    chapter = project / "work/accepted/0002.txt"
    original = chapter.read_bytes()
    config = (project / "project.json").read_bytes()
    glossary = (project / "work/glossary/active.csv").read_bytes()
    calls = []
    plan = propose_term_fix(
        project,
        "老人",
        "Мудрец",
        r"Старец|Старцу",
        requester=requester(calls),
        model="fake-model",
        reasoning_effort="medium",
    )
    assert [row["replacement"] for row in plan["patches"]] == ["Мудрец", "Мудрецу"]
    assert plan["chapter_sha256"]["2"] == digest(original.decode())
    assert all(original.decode()[row["start"] : row["end"]] == row["old"] for row in plan["patches"])
    assert json.loads(Path(plan["plan_path"]).read_text()) == plan
    assert len(calls) == 2 and calls[0]["model"] == "fake-model" and calls[0]["reasoning"]["effort"] == "medium"
    data = json.loads(calls[0]["input"][1]["content"])
    assert all(len(x["left"]) <= 160 and len(x["right"]) <= 160 for x in data["matches"])
    assert original.decode() not in json.dumps(calls[0], ensure_ascii=False)
    assert chapter.read_bytes() == original and (project / "project.json").read_bytes() == config
    assert (project / "work/glossary/active.csv").read_bytes() == glossary


@pytest.mark.parametrize("mode", ["missing", "extra", "duplicate", "invalid"])
def test_invalid_responses_rejected_without_mutation(tmp_path: Path, mode: str):
    project = project_with_matches(tmp_path)
    before = (project / "work/accepted/0002.txt").read_bytes()
    with pytest.raises(ValueError):
        propose_term_fix(project, "老人", "Мудрец", r"Старец|Старцу", requester=requester([], mode))
    assert (project / "work/accepted/0002.txt").read_bytes() == before
    assert not list(project.glob("work/term-fixes/*/plan.json"))


def test_uncertain_result_is_preserved(tmp_path: Path):
    project = project_with_matches(tmp_path)
    plan = propose_term_fix(
        project, "老人", "Мудрец", "Старец", requester=requester([], "uncertain"), allow_contextual_fallback=False
    )
    assert plan["patches"][0]["uncertain"] is True


def test_changed_chapter_during_request_refuses_plan(tmp_path: Path):
    project = project_with_matches(tmp_path)
    chapter = project / "work/accepted/0002.txt"
    base = requester([])

    def mutate(payload):
        chapter.write_text(chapter.read_text() + "Изменено.")
        return base(payload)

    with pytest.raises(RuntimeError, match="changed"):
        propose_term_fix(project, "老人", "Мудрец", "Старец", requester=mutate)
    assert not list(project.glob("work/term-fixes/*/plan.json"))


def test_empty_match_is_rejected_and_stale_chapter_ignored(tmp_path: Path):
    project = project_with_matches(tmp_path)
    with pytest.raises(ValueError, match="empty"):
        propose_term_fix(project, "老人", "Мудрец", r"(?=Старец)", requester=requester([]))
    chapter = project / "work/accepted/0002.txt"
    chapter.write_text(chapter.read_text() + "Посторонняя правка")
    calls = []
    plan = propose_term_fix(project, "老人", "Мудрец", "Старец", requester=requester(calls))
    assert not plan["patches"] and "2" not in plan["chapter_sha256"] and not calls


def test_oversized_match_is_rejected_before_request(tmp_path: Path):
    project = project_with_matches(tmp_path)
    calls = []
    with pytest.raises(ValueError, match="at most 120"):
        propose_term_fix(project, "老人", "Мудрец", ".{150}", requester=requester(calls))
    assert not calls


def test_batches_split_into_at_most_64_matches(tmp_path: Path):
    project = project_with_matches(tmp_path)
    chapter = project / "work/accepted/0002.txt"
    chapter.write_text("Глава 2. Свет\n\n" + ("Старец " * 70))
    progress_path = project / "work/progress.json"
    progress = json.loads(progress_path.read_text())
    progress["chapters"]["2"]["target_sha256"] = digest(chapter.read_text())
    progress_path.write_text(json.dumps(progress))
    calls = []
    plan = propose_term_fix(project, "老人", "Мудрец", "Старец", requester=requester(calls))
    assert len(plan["patches"]) == 70
    assert [len(json.loads(call["input"][1]["content"])["matches"]) for call in calls] == [64, 6, 64, 6]


def test_reviewer_repairs_draft_and_preserves_unresolved(tmp_path: Path):
    project = project_with_matches(tmp_path)
    calls = []

    def respond(payload):
        calls.append(payload)
        data = json.loads(payload["input"][1]["content"])
        is_review = payload["metadata"]["agent"] == "terminology-reviewer"
        rows = []
        for index, item in enumerate(data["matches"]):
            if is_review:
                assert item["draft_replacement"] == "Чужая лемма"
            rows.append(
                {
                    "id": item["id"],
                    "replacement": ("Мудрец" if index == 0 else "Мудрецу") if is_review else "Чужая лемма",
                    "uncertain": is_review and index == 1,
                    "reason": "needs outside span" if is_review and index == 1 else "",
                }
            )
        return {"output_text": json.dumps({"replacements": rows}, ensure_ascii=False), "usage": {"input_tokens": 10}}

    plan = propose_term_fix(
        project,
        "老人",
        "Мудрец",
        r"Старец|Старцу",
        requester=respond,
        model="draft-model",
        review_model="review-model",
        review_reasoning_effort="high",
        allow_contextual_fallback=False,
    )
    assert [p["replacement"] for p in plan["patches"]] == ["Мудрец", "Мудрецу"]
    assert [p["uncertain"] for p in plan["patches"]] == [False, True]
    assert (
        plan["reviewed"] and plan["review_model"] == "review-model" and plan["review_usage"] == [{"input_tokens": 10}]
    )
    assert plan["reviewed_patch_sha256"] == digest(json.dumps(plan["patches"], ensure_ascii=False, sort_keys=True))
    assert calls[1]["model"] == "review-model" and calls[1]["reasoning"]["effort"] == "high"
    draft = Path(plan["plan_path"]).parent / "draft-plan.json"
    assert json.loads(draft.read_text())["patches"][0]["replacement"] == "Чужая лемма"
    assert list(draft.parent.glob("review-*.tasks.jsonl")) and list(draft.parent.glob("review-*.results.jsonl"))


def test_review_existing_draft_without_repeating_draft_request(tmp_path: Path):
    project = project_with_matches(tmp_path)
    first = propose_term_fix(project, "老人", "Мудрец", "Старец", requester=requester([]))
    draft = Path(first["plan_path"]).parent / "draft-plan.json"
    calls = []
    reviewed = review_term_fix(project, draft, requester=requester(calls), model="reviewer")
    assert len(calls) == 1 and calls[0]["metadata"]["agent"] == "terminology-reviewer"
    assert Path(reviewed["plan_path"]).name == "plan.reviewed.json"
    assert reviewed["reviewed"] and reviewed["review_model"] == "reviewer"
    chapter = project / "work/accepted/0002.txt"
    chapter.write_text(chapter.read_text() + "Изменение")
    with pytest.raises(ValueError, match="Stale"):
        review_term_fix(project, draft, requester=requester(calls))
    assert len(calls) == 1
