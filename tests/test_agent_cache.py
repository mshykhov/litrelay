import json
from pathlib import Path

import pytest

from litrelay.agent_executor import run_agent_tasks


def task():
    return {
        "custom_id": "one",
        "agent": "translator",
        "system": "Translate",
        "input": {"text": "original"},
        "expected_output": {"format": "text"},
    }


def write_task(path, item):
    path.write_text(json.dumps(item) + "\n")


def response(payload):
    return {"id": "fake", "model": payload["model"], "output_text": "valid result"}


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_identical_request_skips_and_changed_payload_reruns(tmp_path: Path):
    source, result = tmp_path / "tasks", tmp_path / "results"
    item = task()
    write_task(source, item)
    calls = []

    def request(payload):
        calls.append(payload)
        return response(payload)

    def run(model="model", reasoning=None):
        return run_agent_tasks(source, result, model=model, reasoning_effort=reasoning, requester=request)

    assert run().completed == 1
    first = rows(result)[0]
    assert len(first["request_sha256"]) == 64
    assert run().skipped == 1
    item["input"]["text"] = "changed"
    write_task(source, item)
    assert run().completed == 1
    assert run(model="other").completed == 1
    assert run(model="other", reasoning="high").completed == 1
    assert run(model="other", reasoning="high").skipped == 1
    assert len(calls) == 4
    assert len(rows(result)) == 1
    archives = list(tmp_path.glob("results.archive-*"))
    assert len(archives) == 3
    assert any(json.loads(path.read_text()) == first for path in archives)


def test_legacy_and_invalid_results_are_not_cached(tmp_path: Path):
    source, result = tmp_path / "tasks", tmp_path / "results"
    item = task()
    item["expected_output"] = {"format": "json"}
    write_task(source, item)
    legacy = {"custom_id": "one", "status": "completed", "output": "{}"}
    result.write_text(json.dumps(legacy) + "\n")
    calls = []

    def request(payload):
        calls.append(payload)
        return {"output_text": "{}"}

    assert run_agent_tasks(source, result, model="m", requester=request).completed == 1
    assert json.loads(next(tmp_path.glob("results.archive-*")).read_text()) == legacy
    current = rows(result)[0]
    current["output"] = "not json"
    result.write_text(json.dumps(current) + "\n")
    assert run_agent_tasks(source, result, model="m", requester=request).completed == 1
    assert len(calls) == 2 and len(rows(result)) == 1


def test_latest_matching_valid_duplicate_is_selected(tmp_path: Path):
    source, result = tmp_path / "tasks", tmp_path / "results"
    write_task(source, task())
    run_agent_tasks(source, result, model="m", requester=response)
    first = rows(result)[0]
    second = {**first, "output": "latest"}
    result.write_text("".join(json.dumps(x) + "\n" for x in [first, second, {**second, "status": "error"}]))
    assert run_agent_tasks(source, result, model="m", requester=response).skipped == 1
    assert rows(result) == [second]
    assert len(list(tmp_path.glob("results.archive-*"))) == 1


@pytest.mark.parametrize("field", ["system", "expected_output"])
def test_system_and_schema_changes_invalidate(tmp_path: Path, field: str):
    source, result = tmp_path / "tasks", tmp_path / "results"
    item = task()
    write_task(source, item)
    run_agent_tasks(source, result, model="m", requester=response)
    item[field] = "new system" if field == "system" else {"format": "json"}
    write_task(source, item)
    summary = run_agent_tasks(source, result, model="m", requester=lambda p: {"output_text": "{}"})
    assert summary.completed == 1 and summary.skipped == 0
    assert len(rows(result)) == 1
