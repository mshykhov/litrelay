import json
from pathlib import Path

import pytest

from litrelay.project_config import initialize_project
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
    assert trace["provider_calls"] == len(calls) == 3
    assert trace["usage_complete"] and trace["tokens"]["total_tokens"] == 360
    assert trace["qa_checks_passed"] == 1
    assert trace["stages"]["qa"]["tokens"]["input_tokens"] == 100
    events = [json.loads(line) for line in Path(trace["journal"]).read_text().splitlines()]
    assert {e["stage"] for e in events if e["event"] == "stage_started"} == {"translation", "glossary_update", "qa"}
    assert any(e["event"] == "export_finished" and e["formats"] == ["txt", "epub", "zip"] for e in events)
    assert "QA 0001 pass" in capsys.readouterr().err
    result = run_project(project, requester=measured, debug=True)
    assert len(calls) == 3
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
