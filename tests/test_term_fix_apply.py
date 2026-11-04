import csv
import json
from pathlib import Path

import pytest
from test_project_workflow import fake_model

from litrelay.project_config import initialize_project
from litrelay.project_workflow import project_status, run_project
from litrelay.term_fix_apply import apply_term_fix
from litrelay.term_fix_plan import propose_term_fix

PATTERN = r"(?i)\bсовершенствующ[а-яё]+ся\b"
TEXT = "Совершенствующийся подошёл к совершенствующимся. Он был совершенствующимся."
FIXED = "Культиватор подошёл к культиваторам. Он был культиватором."


def prepared(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    for n in [1, 2]:
        (source / f"{n}.txt").write_text(f"第{n}章 修士\n\n" + "修士走向其他修士。" * 10)
    project = tmp_path / "book"
    initialize_project(project, source=source, min_chars=20)
    base = fake_model([])

    def initial(payload):
        response = base(payload)
        if payload["metadata"]["agent"] == "translation-agent":
            data = json.loads(response["output"][0]["content"][0]["text"])
            data["translation"] = f"Глава {int(data['chapter_id'])}. Начало\n\n{TEXT}\n"
            response["output"][0]["content"][0]["text"] = json.dumps(data)
        return response

    run_project(project, requester=initial)

    def editor(payload):
        items = json.loads(payload["input"][1]["content"])["matches"]
        replacements = []
        for item in items:
            word = (
                "Культиватор"
                if item["old"][0].isupper()
                else "культиватором"
                if item["left"].endswith("был ")
                else "культиваторам"
            )
            replacements.append({"id": item["id"], "replacement": word, "uncertain": False, "reason": "case"})
        return {"output_text": json.dumps({"replacements": replacements})}

    plan = propose_term_fix(project, "修士", "культиватор", PATTERN, requester=editor)
    return project, Path(plan["plan_path"])


def test_apply_updates_only_spans_glossary_and_exports_and_resumes_without_llm(tmp_path: Path) -> None:
    project, plan = prepared(tmp_path)
    old = project_status(project)
    source = (project / "input/source/0001.txt").read_bytes()
    result = apply_term_fix(project, plan)
    assert result["replacements"] == 6 and result["changed_chapters"] == [1, 2]
    for n in [1, 2]:
        assert (project / f"work/accepted/{n:04d}.txt").read_text() == f"Глава {n}. Начало\n\n{FIXED}\n"
    assert (project / "input/source/0001.txt").read_bytes() == source
    assert "культиватор" in (project / "output/book.txt").read_text()
    assert old["fingerprint"] != project_status(project)["fingerprint"]
    row = project_status(project)["chapters"]["1"]
    assert row["qa_target_sha256"] == old["chapters"]["1"]["target_sha256"]
    assert row["editorial_changes"]
    glossary = list(csv.DictReader((project / "work/glossary/active.csv").open()))
    assert next(r for r in glossary if r["source"] == "修士")["target_ru"] == "культиватор"
    calls = []
    assert run_project(project, requester=fake_model(calls))["complete"]
    assert not calls
    assert apply_term_fix(project, plan)["already_applied"]


@pytest.mark.parametrize("damage", ["uncertain", "missing", "wrong_offset", "newline", "stale", "cjk", "target"])
def test_invalid_plan_never_changes_accepted_text(tmp_path: Path, damage: str) -> None:
    project, path = prepared(tmp_path)
    before = {
        p: p.read_bytes()
        for p in [
            *project.glob("work/accepted/*.txt"),
            project / "work/progress.json",
            project / "work/glossary/active.csv",
        ]
    }
    plan = json.loads(path.read_text())
    if damage == "uncertain":
        plan["patches"][0]["uncertain"] = True
    if damage == "missing":
        plan["patches"].pop()
    if damage == "wrong_offset":
        plan["patches"][0]["start"] += 1
    if damage == "newline":
        plan["patches"][0]["replacement"] = "Культиватор\nЛишнее"
    if damage == "stale":
        plan["project_fingerprint"] = "stale"
    if damage == "cjk":
        plan["patches"][0]["replacement"] = "\U00020000"
    if damage == "target":
        plan["target"] = "знахарь"
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError):
        apply_term_fix(project, path)
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not (project / "input/term-overrides.csv").exists()


def test_export_failure_restores_every_local_file(tmp_path: Path, monkeypatch) -> None:
    from litrelay import term_fix_apply

    project, path = prepared(tmp_path)
    files = [
        *project.glob("work/accepted/*.txt"),
        *project.glob("output/*"),
        project / "work/progress.json",
        project / "work/glossary/active.csv",
    ]
    before = {p: p.read_bytes() for p in files}

    def fail(project, **kwargs):
        (project / "output/book.txt").write_text("Broken export")
        raise OSError("Disk error")

    monkeypatch.setattr(term_fix_apply, "export_project", fail)
    with pytest.raises(OSError, match="Disk error"):
        apply_term_fix(project, path)
    assert all(p.read_bytes() == data for p, data in before.items())
    assert not (project / "input/term-overrides.csv").exists()
    assert project_status(project)["complete"]


def test_interrupted_transaction_blocks_normal_run_and_another_apply(tmp_path: Path) -> None:
    project, path = prepared(tmp_path)
    (path.parent / "transaction.json").write_text('{"status":"applying"}')
    (project / "input/term-overrides.csv").write_text(
        "source,target_ru,type,note,confidence\n修士,культиватор,term,,1\n"
    )
    calls = []
    with pytest.raises(RuntimeError, match="Unfinished term-fix"):
        run_project(project, requester=fake_model(calls))
    with pytest.raises(RuntimeError, match="Unfinished term-fix"):
        apply_term_fix(project, path)
    assert not calls


def test_preference_is_applied_again_after_source_bootstrap(tmp_path: Path) -> None:
    project, plan = prepared(tmp_path)
    apply_term_fix(project, plan)
    config = json.loads((project / "project.json").read_text())
    config["title"] = "Changed title"
    (project / "project.json").write_text(json.dumps(config))
    calls = []
    run_project(project, requester=fake_model(calls))
    translations = [data for agent, data in calls if agent == "translation-agent"]
    assert translations and all("культиватор" in data["glossary_csv"] for data in translations)
