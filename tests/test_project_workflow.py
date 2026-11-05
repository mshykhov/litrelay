import json
from pathlib import Path

import pytest

from litrelay.project_config import initialize_project
from litrelay.project_revision import revise_project_chapter
from litrelay.project_workflow import project_status, run_project
from litrelay.telemetry import latest_summary


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


def test_debug_tracks_real_stages_and_cache_resume_without_recounting_usage(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "1.txt").write_text("第1章 光\n\n" + ("完整文本。" * 40))
    project = tmp_path / "project"
    initialize_project(project, source=source)
    calls = []
    base = fake_model(calls)

    def measured(payload):
        response = base(payload)
        response["usage"] = {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 20}
        return response

    result = run_project(project, requester=measured, debug=True)
    trace = result["telemetry"]
    assert trace["provider_calls"] == len(calls) == 5
    assert trace["usage_complete"] and trace["tokens"]["total_tokens"] == 600
    assert trace["qa_checks_passed"] == 1
    assert trace["stages"]["qa"]["tokens"]["input_tokens"] == 100
    events = [json.loads(line) for line in Path(trace["journal"]).read_text().splitlines()]
    assert {e["stage"] for e in events if e["event"] == "stage_started"} == {
        "translation",
        "glossary_update",
        "qa",
        "glossary_bootstrap",
    }
    assert any(e["event"] == "export_finished" and e["formats"] == ["txt", "epub", "zip"] for e in events)
    assert "QA 0001 pass" in capsys.readouterr().err
    result = run_project(project, requester=measured, debug=True)
    assert len(calls) == 5
    cached = latest_summary(project)
    assert cached["run_id"] == result["telemetry"]["run_id"]
    assert cached["provider_calls"] == 0 and cached["tokens"]["total_tokens"] == 0
    assert cached["cache_hits"] == 2 and cached["usage_complete"]


def test_debug_failure_persists_summary_and_does_not_export(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "1.txt").write_text("第1章 光\n\n" + ("完整文本。" * 40))
    project = tmp_path / "project"
    initialize_project(project, source=source)
    config = json.loads((project / "project.json").read_text())
    config["revise_attempts"] = 0
    (project / "project.json").write_text(json.dumps(config))
    base = fake_model([])

    def failing(payload):
        response = base(payload)
        if payload["metadata"]["agent"] == "translation-qa":
            data = json.loads(response["output"][0]["content"][0]["text"])
            data["meaning_score"] = 5
            response["output"][0]["content"][0]["text"] = json.dumps(data)
        return response

    with pytest.raises(RuntimeError, match="QA blocked"):
        run_project(project, requester=failing, debug=True)
    summary = latest_summary(project)
    assert summary["status"] == "failed" and summary["qa_checks_failed"] == 1
    assert summary["usage_missing_calls"] == summary["provider_calls"] > 0
    assert summary["tokens"]["input_tokens"] is None
    assert not (project / "output/book.zip").exists()
    assert not (project / "work/run.lock").exists()


def test_debug_cli_preserves_json_stdout_and_stats_never_calls_model(tmp_path: Path, capsys, monkeypatch) -> None:
    from litrelay import project_cli
    from litrelay.cli import run

    source = tmp_path / "source"
    source.mkdir()
    (source / "1.txt").write_text("第1章 光\n\n" + ("完整文本。" * 40))
    initialize_project(tmp_path / "book", source=source)
    calls = []
    real_run = project_cli.run_project
    monkeypatch.setattr(project_cli, "run_project", lambda *a, **kw: real_run(*a, **kw, requester=fake_model(calls)))
    log_file = tmp_path / "events.jsonl"
    assert run(["run", "book", "--workspace", str(tmp_path), "--log-file", str(log_file)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["telemetry"]["journal"] == str(log_file)
    assert "translation started" in output.err
    count = len(calls)
    assert run(["stats", "book", "--workspace", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["provider_calls"] == count
    assert len(calls) == count


def _revision_project(tmp_path: Path, *, max_chapters: int | None = None, revise_attempts: int = 0) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    translation = tmp_path / "translation"
    translation.mkdir()
    for n in [1, 2, 3]:
        (source / f"{n}.txt").write_text(f"第{n}章 光\n\n" + "海边的旅人记录了所有发生的事。" * 15)
    (translation / "1.txt").write_text("Глава 1. Свет\n\n" + "Существующий перевод первой главы. " * 10)
    project = tmp_path / "book"
    initialize_project(project, source=source, translation=translation)
    config = json.loads((project / "project.json").read_text())
    config["revise_attempts"] = revise_attempts
    (project / "project.json").write_text(json.dumps(config))
    run_project(project, requester=fake_model([]), max_chapters=max_chapters)
    return project


@pytest.mark.parametrize("chapter", [1, 2])
def test_revision_changes_only_selected_chapter_and_survives_resume(tmp_path: Path, chapter: int) -> None:
    project = _revision_project(tmp_path)
    before = project_status(project)
    files = [project / "project.json", *project.glob("input/**/*.txt"), project / "work/glossary/active.csv"]
    unchanged = {p: p.read_bytes() for p in files}
    previous = (project / f"work/accepted/{chapter:04d}.txt").read_text()
    calls = []
    base = fake_model(calls)

    def revise(payload):
        result = base(payload)
        if payload["metadata"]["agent"] == "translation-agent":
            data = json.loads(result["output"][0]["content"][0]["text"])
            data["translation"] += "\nПовествование стало яснее."
            result["output"][0]["content"][0]["text"] = json.dumps(data)
        return result

    result = revise_project_chapter(project, chapter=chapter, feedback="Сделай действия понятнее", requester=revise)
    assert result["complete"] and result["revised_chapter"] == chapter
    assert Path(result["previous_version"]).read_text() == previous
    after = project_status(project)
    for n in before["chapters"]:
        if int(n) != chapter:
            assert before["chapters"][n] == after["chapters"][n]
    assert all(p.read_bytes() == original for p, original in unchanged.items())
    assert len(calls) == 3
    assert all(user["chapter_id"] == f"{chapter:04d}" for _, user in calls)
    assert all(
        user["reader_feedback"] == "Сделай действия понятнее"
        for agent, user in calls
        if agent in {"translation-agent", "translation-qa"}
    )
    assert calls[0][1]["previous_translation"] == previous
    assert "Повествование стало яснее" in (project / "output/book.txt").read_text()
    progress = (project / "work/progress.json").read_bytes()
    run_project(project, requester=fake_model(calls))
    assert len(calls) == 3
    assert (project / "work/progress.json").read_bytes() == progress
    assert project_status(project)["complete"]


def test_from_scratch_bypasses_previous_translation_and_cached_attempts(tmp_path: Path) -> None:
    project = _revision_project(tmp_path)
    calls = []
    first = revise_project_chapter(project, chapter=2, from_scratch=True, requester=fake_model(calls))
    second = revise_project_chapter(project, chapter=2, from_scratch=True, requester=fake_model(calls))
    assert len(calls) == 6
    assert first["revision_dir"] != second["revision_dir"]
    assert all("previous_translation" not in user for agent, user in calls if agent == "translation-agent")


@pytest.mark.parametrize("failure", ["qa", "residue", "provider", "missing_qa", "interrupted"])
def test_failed_revision_keeps_accepted_text_checkpoint_and_exports(tmp_path: Path, failure: str) -> None:
    project = _revision_project(tmp_path)
    paths = [*project.glob("work/accepted/*.txt"), project / "work/progress.json", *project.glob("output/*")]
    before = {p: p.read_bytes() for p in paths}
    base = fake_model([])

    def fail(payload):
        if failure == "provider":
            raise RuntimeError("Provider unavailable")
        if failure == "interrupted":
            raise KeyboardInterrupt
        result = base(payload)
        agent = payload["metadata"]["agent"]
        if failure == "missing_qa" and agent == "translation-qa":
            raise RuntimeError("QA provider unavailable")
        data = json.loads(result["output"][0]["content"][0]["text"])
        if failure == "qa" and agent == "translation-qa":
            data["meaning_score"] = 1
        if failure == "residue" and agent == "translation-agent":
            data["translation"] += "\n安排"
        result["output"][0]["content"][0]["text"] = json.dumps(data)
        return result

    with pytest.raises(KeyboardInterrupt if failure == "interrupted" else RuntimeError):
        revise_project_chapter(project, chapter=2, feedback="Исправь стиль", requester=fail, debug=True)
    assert all(p.read_bytes() == original for p, original in before.items())
    assert project_status(project)["complete"]
    assert not (project / "work/run.lock").exists()
    backups = list(project.glob("work/revisions/0002/*/previous.txt"))
    assert len(backups) == 1 and backups[0].read_bytes() == before[project / "work/accepted/0002.txt"]
    assert latest_summary(project)["status"] == ("interrupted" if failure == "interrupted" else "failed")


def test_reader_feedback_survives_automatic_revision_and_qa(tmp_path: Path) -> None:
    project = _revision_project(tmp_path, revise_attempts=2)
    calls = []
    base = fake_model(calls)
    checks = 0

    def repair(payload):
        nonlocal checks
        result = base(payload)
        if payload["metadata"]["agent"] == "translation-qa":
            checks += 1
            if checks == 1:
                data = json.loads(result["output"][0]["content"][0]["text"])
                data.update(style_score=10, issues=["Действия неясны"], recommended_action="Уточни действия")
                result["output"][0]["content"][0]["text"] = json.dumps(data)
        return result

    result = revise_project_chapter(project, chapter=2, feedback="Уточни действия", requester=repair, debug=True)
    assert result["complete"] and len(calls) == 5
    assert all(
        user["reader_feedback"] == "Уточни действия"
        for agent, user in calls
        if agent in {"translation-agent", "translation-qa"}
    )
    assert calls[3][1]["qa_issues"] == ["Действия неясны"]
    assert result["telemetry"]["provider_calls"] == 5


def test_revision_of_partial_book_is_used_as_context_for_continuation(tmp_path: Path) -> None:
    project = _revision_project(tmp_path, max_chapters=1)
    assert project_status(project)["missing"] == [3]
    revise_project_chapter(project, chapter=2, feedback="Исправь стиль", requester=fake_model([]))
    assert not (project / "output/book.zip").exists()
    calls = []
    run_project(project, requester=fake_model(calls))
    translated = [user for agent, user in calls if agent == "translation-agent"]
    assert len(translated) == 1 and translated[0]["chapter_id"] == "0003"
    assert any(
        c["text"] == (project / "work/accepted/0002.txt").read_text() for c in translated[0]["recent_target_context"]
    )


def test_revision_rejects_stale_chapter_missing_feedback_and_project_lock(tmp_path: Path) -> None:
    from litrelay.project_storage import project_lock

    project = _revision_project(tmp_path, max_chapters=1)
    with pytest.raises(ValueError, match="feedback"):
        revise_project_chapter(project, chapter=2, requester=fake_model([]))
    with pytest.raises(ValueError, match="accepted"):
        revise_project_chapter(project, chapter=3, from_scratch=True, requester=fake_model([]))
    with project_lock(project), pytest.raises(RuntimeError, match="already running"):
        revise_project_chapter(project, chapter=2, from_scratch=True, requester=fake_model([]))
    chapter = project / "work/accepted/0002.txt"
    chapter.write_text(chapter.read_text() + "\nРучная правка вне пайплайна.")
    with pytest.raises(ValueError, match="accepted"):
        revise_project_chapter(project, chapter=2, from_scratch=True, requester=fake_model([]))


def test_revision_cli_reads_feedback_file(tmp_path: Path, capsys, monkeypatch) -> None:
    from litrelay import project_cli
    from litrelay.cli import run

    project = _revision_project(tmp_path)
    calls = []
    real_revise = project_cli.revise_project_chapter
    monkeypatch.setattr(
        project_cli, "revise_project_chapter", lambda *a, **kw: real_revise(*a, **kw, requester=fake_model(calls))
    )
    feedback = tmp_path / "feedback.txt"
    feedback.write_text("Сделай диалог естественнее", encoding="utf-8")
    assert (
        run(["revise", "book", "--workspace", str(tmp_path), "--chapter", "2", "--feedback-file", str(feedback)]) == 0
    )
    assert json.loads(capsys.readouterr().out)["revised_chapter"] == 2
    assert calls[0][1]["reader_feedback"] == feedback.read_text()
    assert project_status(project)["complete"]


def test_checkpoint_write_failure_rolls_back_revision(tmp_path: Path, monkeypatch) -> None:
    from litrelay import project_revision

    project = _revision_project(tmp_path)
    paths = [*project.glob("work/accepted/*.txt"), project / "work/progress.json", *project.glob("output/*")]
    before = {p: p.read_bytes() for p in paths}
    original_write = project_revision.write_json
    failed = False

    def fail_checkpoint(path, data):
        nonlocal failed
        if path == project / "work/progress.json" and not failed:
            failed = True
            raise OSError("Checkpoint write failed")
        return original_write(path, data)

    monkeypatch.setattr(project_revision, "write_json", fail_checkpoint)
    with pytest.raises(OSError, match="Checkpoint write failed"):
        revise_project_chapter(project, chapter=1, feedback="Исправь стиль", requester=fake_model([]))
    assert failed and all(p.read_bytes() == original for p, original in before.items())
    assert project_status(project)["complete"]


def test_source_change_during_revision_prevents_acceptance(tmp_path: Path) -> None:
    project = _revision_project(tmp_path)
    accepted = project / "work/accepted/0002.txt"
    previous = accepted.read_bytes()
    progress = (project / "work/progress.json").read_bytes()
    base = fake_model([])

    def change_source(payload):
        result = base(payload)
        if payload["metadata"]["agent"] == "translation-agent":
            source = project / "input/source/0002.txt"
            source.write_text(source.read_text() + "\n新的事实。")
        return result

    with pytest.raises(RuntimeError, match="Project changed"):
        revise_project_chapter(project, chapter=2, feedback="Исправь стиль", requester=change_source)
    assert accepted.read_bytes() == previous
    assert (project / "work/progress.json").read_bytes() == progress


def test_measurement_profile_renders_custom_units_before_qa_and_export(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "1.txt").write_text(
        "Chapter 1. Light\n\nThe traveler crossed two to three leagues in a few breaths.", encoding="utf-8"
    )
    project = tmp_path / "project"
    initialize_project(
        project,
        source=source,
        source_language="en",
        min_chars=20,
        measurements={"league": {"source": "league", "factor": "5", "symbol": "км", "approximate": True}},
    )
    calls = []
    fake = fake_model(calls)

    def request(payload: dict) -> dict:
        response = fake(payload)
        if payload["metadata"]["agent"] == "translation-agent":
            assert "[[measure:ID:NUMBER]]" in payload["input"][0]["content"]
            content = response["output"][0]["content"][0]
            output = json.loads(content["text"])
            output["translation"] = (
                "Глава 1. Свет\n\nПутник преодолел две-три лиги[[measure:league:2-3]] за несколько вдохов."
            )
            content["text"] = json.dumps(output)
        return response

    result = run_project(project, requester=request)
    expected = "две-три лиги [≈10–15 км] за несколько вдохов"
    assert expected in Path(result["outputs"]["txt"]).read_text()
    assert expected in next(data["generated_translation"] for agent, data in calls if agent == "translation-qa")
    assert "[[measure:" not in Path(result["outputs"]["txt"]).read_text()
