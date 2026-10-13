import json
from pathlib import Path

import pytest

from litrelay.project_config import initialize_project
from litrelay.project_workflow import project_status, run_project


def fake_model(calls: list):
    def request(payload: dict) -> dict:
        agent = payload["metadata"]["agent"]
        user = json.loads(payload["input"][1]["content"])
        cid = user.get("chapter_id", "0001")
        calls.append((agent, user))
        if agent == "translation-agent":
            data = {
                "chapter_id": cid,
                "translation": f"Глава {int(cid)}. Свет\n\n"
                + ("Путник у моря записал каждое событие и отправился домой. " * 5),
                "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
            }
            out = json.dumps(data, ensure_ascii=False)
        elif agent == "translation-qa":
            out = json.dumps(
                {
                    "chapter_id": cid,
                    "meaning_score": 96,
                    "omission_score": 99,
                    "terminology_score": 96,
                    "style_score": 92,
                    "verdict": "pass",
                    "strengths": [],
                    "issues": [],
                    "missing_or_changed_facts": [],
                    "recommended_action": "",
                }
            )
        elif agent == "alignment-auditor":
            out = json.dumps(
                {
                    "chapter_id": cid,
                    "verdict": "aligned",
                    "confidence": 0.99,
                    "evidence": ["same events"],
                    "issues": [],
                    "recommended_action": "",
                }
            )
        else:
            out = "source,target_ru,type,note,confidence\n海,море,place,established term,0.99\n"
        return {"id": "fake", "model": "fake", "output": [{"content": [{"type": "output_text", "text": out}]}]}

    return request


def test_original_plus_translation_fills_holes_exports_and_resumes_without_llm(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    ru = tmp_path / "ru"
    ru.mkdir()
    for n in [1, 2, 3]:
        (source / f"{n}.txt").write_text(f"第{n}章 光\n\n" + ("海边的旅人记录了所有发生的事。" * 15))
    human = "Глава 1. Свет\n\n" + ("Человеческий текст сохранён без изменений. " * 5)
    (ru / "1.txt").write_text(human)
    (ru / "3.txt").write_text(human.replace("Глава 1", "Глава 3"))
    project = tmp_path / "project"
    initialize_project(project, source=source, translation=ru, title="A sea", min_chars=100)
    calls = []
    result = run_project(project, requester=fake_model(calls))
    assert result["complete"] and result["total"] == 3 and result["generated"] == 1
    assert (project / "work/accepted/0001.txt").read_text() == human.rstrip() + "\n"
    translating = [x for a, x in calls if a == "translation-agent"]
    assert len(translating) == 1 and translating[0]["chapter_id"] == "0002"
    assert any("Человеческий текст" in x["text"] for x in translating[0]["recent_target_context"])
    assert all(Path(p).exists() for p in result["outputs"].values())
    count = len(calls)
    run_project(project, requester=fake_model(calls))
    assert len(calls) == count
    assert project_status(project)["complete"]


def test_source_only_bootstraps_terms_and_never_requires_reader(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "1.txt").write_text("第1章 光\n\n" + ("海边的旅人记录了所有发生的事。" * 15))
    project = tmp_path / "project"
    c = initialize_project(project, source=source, min_chars=100)
    assert c["profile"] == "fresh" and "reader" not in c
    calls = []
    assert run_project(project, requester=fake_model(calls))["complete"]
    assert not any(a == "alignment-auditor" for a, _ in calls)


def test_init_rejects_source_gaps_and_does_not_overwrite_project(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "2.txt").write_text("第2章 光\n\n" + ("完整文本。" * 40))
    with pytest.raises(ValueError, match="Missing"):
        initialize_project(tmp_path / "project", source=source)
    (source / "1.txt").write_text("第1章 光\n\n" + ("完整文本。" * 40))
    initialize_project(tmp_path / "project", source=source)
    with pytest.raises(ValueError, match="already"):
        initialize_project(tmp_path / "project", source=source)


def test_residue_cannot_pass_even_when_model_qa_scores_are_high(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "1.txt").write_text("第1章 光\n\n" + ("完整文本。" * 40))
    project = tmp_path / "project"
    initialize_project(project, source=source)
    config = json.loads((project / "project.json").read_text())
    config["revise_attempts"] = 0
    (project / "project.json").write_text(json.dumps(config))
    calls = []
    base = fake_model(calls)

    def bad(payload):
        result = base(payload)
        if payload["metadata"]["agent"] == "translation-agent":
            data = json.loads(result["output"][0]["content"][0]["text"])
            data["translation"] += "\n安排"
            result["output"][0]["content"][0]["text"] = json.dumps(data)
        return result

    with pytest.raises(RuntimeError, match="QA blocked"):
        run_project(project, requester=bad)
    assert not (project / "output/book.zip").exists()
    assert not project_status(project)["complete"]


def test_changed_source_invalidates_generated_checkpoint(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "1.txt").write_text("第1章 光\n\n" + ("完整文本。" * 40))
    project = tmp_path / "project"
    initialize_project(project, source=source)
    calls = []
    run_project(project, requester=fake_model(calls))
    count = len(calls)
    p = project / "input/source/0001.txt"
    p.write_text(p.read_text() + "\n新的事实。")
    assert not project_status(project)["complete"]
    run_project(project, requester=fake_model(calls))
    assert len(calls) > count


def test_failed_alignment_never_marks_trusted_input_book_complete(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    translation = tmp_path / "translation"
    translation.mkdir()
    (source / "1.txt").write_text("第1章 光\n\n" + ("完整文本。" * 40))
    (translation / "1.txt").write_text("Глава 1. Свет\n\n" + ("Готовый русский перевод. " * 10))
    project = tmp_path / "project"
    initialize_project(project, source=source, translation=translation)
    calls = []
    base = fake_model(calls)

    def bad_alignment(payload):
        r = base(payload)
        if payload["metadata"]["agent"] == "alignment-auditor":
            d = json.loads(r["output"][0]["content"][0]["text"])
            d["verdict"] = "misaligned"
            r["output"][0]["content"][0]["text"] = json.dumps(d)
        return r

    with pytest.raises(RuntimeError, match="alignment failed"):
        run_project(project, requester=bad_alignment)
    assert not project_status(project)["complete"]
