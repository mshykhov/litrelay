import json
import threading
from pathlib import Path

from litrelay.agent_executor import run_agent_tasks


def test_run_agent_tasks_concurrency_writes_all_results(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    out = tmp_path / "out.jsonl"
    lines = [
        json.dumps(
            {
                "custom_id": f"t-{i}",
                "agent": "x",
                "system": "s",
                "input": {"i": i},
                "expected_output": {"format": "text"},
            }
        )
        for i in range(5)
    ]
    tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def fake_requester(payload: dict) -> dict:
        cid = payload["metadata"]["custom_id"]
        return {"id": cid, "model": "f", "output": [{"content": [{"type": "output_text", "text": cid}]}]}

    summary = run_agent_tasks(tasks, out, model="m", requester=fake_requester, concurrency=3)

    assert summary.completed == 5
    assert summary.failed == 0
    written = {json.loads(line)["custom_id"] for line in out.read_text(encoding="utf-8").splitlines()}
    assert written == {"t-0", "t-1", "t-2", "t-3", "t-4"}


def test_run_agent_tasks_retries_invalid_output(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    out = tmp_path / "out.jsonl"
    tasks.write_text(
        json.dumps(
            {
                "custom_id": "translate-0001",
                "agent": "x",
                "system": "s",
                "input": {},
                "expected_output": {"format": "translation_json"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls = {"n": 0}

    def flaky(payload: dict) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            text = "garbage not json"
        else:
            text = json.dumps(
                {
                    "chapter_id": "0001",
                    "translation": "T",
                    "qa": {"terminology_checked": True, "omission_risk": "low", "style_match": "good", "issues": []},
                },
                ensure_ascii=False,
            )
        return {"output": [{"content": [{"type": "output_text", "text": text}]}]}

    summary = run_agent_tasks(tasks, out, model="m", requester=flaky, max_retries=2)

    assert calls["n"] == 2
    assert summary.completed == 1
    written = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert json.loads(written["output"])["translation"] == "T"


def test_run_agent_tasks_records_duration_ms(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    out = tmp_path / "out.jsonl"
    tasks.write_text(
        json.dumps(
            {"custom_id": "t-0", "agent": "x", "system": "s", "input": {}, "expected_output": {"format": "text"}}
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_requester(payload: dict) -> dict:
        return {"id": "r", "output": [{"content": [{"type": "output_text", "text": "ok"}]}]}

    run_agent_tasks(tasks, out, model="m", requester=fake_requester)
    result = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert "duration_ms" in result
    assert isinstance(result["duration_ms"], int) and result["duration_ms"] >= 0


def test_run_agent_tasks_task_deadline_preserves_completed_late_response(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    out = tmp_path / "out.jsonl"
    lines = [
        json.dumps(
            {
                "custom_id": f"t-{i}",
                "agent": "x",
                "system": "s",
                "input": {"i": i},
                "expected_output": {"format": "text"},
            }
        )
        for i in range(3)
    ]
    tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
    release = threading.Event()

    def req(payload: dict) -> dict:
        cid = payload["metadata"]["custom_id"]
        if cid == "t-1":
            release.wait(timeout=5)
        return {"id": cid, "output": [{"content": [{"type": "output_text", "text": cid}]}]}

    timer = threading.Timer(0.1, release.set)
    timer.start()
    try:
        summary = run_agent_tasks(tasks, out, model="m", requester=req, concurrency=3, task_timeout=0.02)
    finally:
        release.set()
        timer.join()

    assert summary.completed == 3
    assert summary.failed == 0
    statuses = {json.loads(line)["custom_id"]: json.loads(line)["status"] for line in out.read_text().splitlines()}
    assert statuses["t-1"] == "completed"
