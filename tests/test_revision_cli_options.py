import json
from pathlib import Path

import pytest
from test_project_workflow import _revision_project, fake_model

from litrelay import project_cli, project_revision
from litrelay.cli import run
from litrelay.project_config import initialize_project
from litrelay.project_workflow import project_status


def test_range_revises_each_chapter_and_preserves_project(tmp_path, monkeypatch, capsys):
    project = _revision_project(tmp_path)
    config = (project / "project.json").read_bytes()
    before = project_status(project)
    original = {n: (project / f"work/accepted/{n:04d}.txt").read_text() for n in (1, 2, 3)}
    calls = []
    stage_profiles = []
    real_stage = project_revision._run_stage

    def stage(cfg, tasks, results, profile):
        stage_profiles.append((profile == cfg.translation_profile, profile.reasoning_effort))
        return real_stage(cfg, tasks, results, profile)

    real_revise = project_cli.revise_project_chapter
    monkeypatch.setattr(project_revision, "_run_stage", stage)
    monkeypatch.setattr(
        project_cli, "revise_project_chapter", lambda *a, **kw: real_revise(*a, **kw, requester=fake_model(calls))
    )
    assert (
        run(
            [
                "revise",
                "book",
                "--workspace",
                str(tmp_path),
                "--chapters",
                "1-2",
                "--from-scratch",
                "--reasoning-effort",
                "high",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["revised_chapters"] == [1, 2]
    assert all(
        json.loads((Path(item["revision_dir"]) / "request.json").read_text())["reasoning_effort"] == "high"
        for item in result["revisions"]
    )
    assert [Path(item["previous_version"]).read_text() for item in result["revisions"]] == [original[1], original[2]]
    assert [user["chapter_id"] for agent, user in calls if agent == "translation-agent"] == ["0001", "0002"]
    assert [user["chapter_id"] for agent, user in calls if agent == "translation-qa"] == ["0001", "0002"]
    assert stage_profiles == [(True, "high"), (False, None)] * 2
    assert (project / "project.json").read_bytes() == config
    assert project_status(project)["chapters"]["3"] == before["chapters"]["3"]
    assert (project / "work/accepted/0003.txt").read_text() == original[3]


def test_range_failure_keeps_prior_result_and_stops(tmp_path, monkeypatch, capsys):
    project = _revision_project(tmp_path)
    calls = []
    base = fake_model(calls)

    def fail_second(payload):
        data = json.loads(payload["input"][1]["content"])
        if data.get("chapter_id") == "0002":
            raise RuntimeError("provider failed")
        result = base(payload)
        if payload["metadata"]["agent"] == "translation-agent":
            content = result["output"][0]["content"][0]
            translation = json.loads(content["text"])
            translation["translation"] += "\nНовая версия."
            content["text"] = json.dumps(translation, ensure_ascii=False)
        return result

    original = (project / "work/accepted/0002.txt").read_bytes()
    real = project_cli.revise_project_chapter
    monkeypatch.setattr(project_cli, "revise_project_chapter", lambda *a, **kw: real(*a, **kw, requester=fail_second))
    assert run(["revise", "book", "--workspace", str(tmp_path), "--chapters", "1-3", "--from-scratch"]) == 1
    output = capsys.readouterr().out
    assert "Chapter 2 failed" in output and "[1]" in output
    assert "Новая версия." in (project / "work/accepted/0001.txt").read_text()
    assert (project / "work/accepted/0002.txt").read_bytes() == original
    assert not list((project / "work/revisions/0003").glob("*"))


@pytest.mark.parametrize("value", ["0-2", "3-2", "1", "1-2-3", "-1-2"])
def test_invalid_ranges_are_rejected(tmp_path, capsys, value):
    assert run(["revise", "book", "--workspace", str(tmp_path), f"--chapters={value}", "--from-scratch"]) == 1
    assert "positive ascending range" in capsys.readouterr().out


def test_init_reasoning_options_and_defaults(tmp_path, capsys):
    source = tmp_path / "source"
    source.mkdir()
    (source / "1.txt").write_text("第一章\n" + "文字" * 100)
    assert (
        run(
            [
                "init",
                "chosen",
                "--workspace",
                str(tmp_path),
                "--source",
                str(source),
                "--reasoning-effort",
                "high",
                "--support-reasoning-effort",
                "low",
            ]
        )
        == 0
    )
    config = json.loads((tmp_path / "chosen/project.json").read_text())
    assert config["translation"]["reasoning_effort"] == "high"
    assert config["support"]["reasoning_effort"] == "low"
    config = initialize_project(tmp_path / "defaults", source=source)
    assert "reasoning_effort" not in config["translation"] and "reasoning_effort" not in config["support"]
    capsys.readouterr()


def test_chapter_options_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as error:
        run(["revise", "book", "--workspace", str(tmp_path), "--chapter", "1", "--chapters", "1-2", "--from-scratch"])
    assert error.value.code == 2
