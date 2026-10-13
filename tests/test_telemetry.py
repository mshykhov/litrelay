import io
import json
import threading
from pathlib import Path

import pytest

from litrelay.agent_executor import run_agent_tasks
from litrelay.telemetry import RunTrace, normalize_usage


def test_usage_never_double_counts_cached_input_or_reasoning() -> None:
    assert normalize_usage(
        {"input_tokens": 100, "cached_input_tokens": 60, "output_tokens": 20, "reasoning_output_tokens": 5}
    ) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_input_tokens": 60,
        "cache_write_tokens": None,
        "reasoning_tokens": 5,
        "total_tokens": 120,
    }
    usage = normalize_usage(
        {"input_tokens": 10, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 30, "output_tokens": 20}
    )
    assert usage["input_tokens"] == 90 and usage["cached_input_tokens"] == 50 and usage["total_tokens"] == 110
    assert normalize_usage({})["input_tokens"] is None


def test_trace_counts_attempts_redacts_secrets_and_excludes_payloads(tmp_path: Path) -> None:
    stream = io.StringIO()
    trace = RunTrace(tmp_path, stream=stream, heartbeat_seconds=0)
    trace.emit({"event": "task_started", "stage": "translation", "task_id": "translate-0001", "attempt": 1})
    trace.emit(
        {
            "event": "task_finished",
            "stage": "translation",
            "task_id": "translate-0001",
            "attempt": 1,
            "status": "error",
            "usage": {},
            "duration_ms": 42,
            "error": "Authorization: Bearer abc-secret-value; api_key=sk-secret-value; private source body",
            "prompt": "private source body",
        }
    )
    trace.emit({"event": "cache_hit", "stage": "qa", "task_id": "qa-0002"})
    paths = trace.close(status="failed")
    journal = Path(paths["journal"]).read_text()
    summary = json.loads(Path(paths["summary"]).read_text())
    assert (
        "abc-secret-value" not in journal and "sk-secret-value" not in journal and "private source body" not in journal
    )
    assert "abc-secret-value" not in stream.getvalue()
    assert summary["provider_calls"] == 1 and summary["cache_hits"] == 1 and summary["usage_missing_calls"] == 1
    assert summary["tokens"]["input_tokens"] is None


def test_every_retry_attempt_is_reported_and_cache_skip_spends_no_new_tokens(tmp_path: Path) -> None:
    task = {
        "custom_id": "align-0001",
        "agent": "alignment-auditor",
        "system": "x",
        "input": {"chapter_id": "0001"},
        "expected_output": {"format": "json"},
    }
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps(task) + "\n")
    results = tmp_path / "results.jsonl"
    events = []
    counter = [0]

    def requester(payload):
        counter[0] += 1
        text = (
            "bad JSON"
            if counter[0] == 1
            else json.dumps(
                {
                    "chapter_id": "0001",
                    "verdict": "aligned",
                    "confidence": 1,
                    "evidence": [],
                    "issues": [],
                    "recommended_action": "",
                }
            )
        )
        return {
            "id": "x",
            "model": "fake",
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "output": [{"content": [{"type": "output_text", "text": text}]}],
        }

    run_agent_tasks(tasks, results, model="fake", requester=requester, max_retries=1, event_handler=events.append)
    finished = [x for x in events if x["event"] == "task_finished"]
    assert len(finished) == 2 and sum(x["usage"]["input_tokens"] for x in finished) == 200
    assert json.loads(results.read_text())["attempts"] == 2
    events.clear()
    run_agent_tasks(tasks, results, model="fake", requester=requester, event_handler=events.append)
    assert counter[0] == 2 and any(x["event"] == "cache_hit" for x in events)


def test_partial_usage_and_provider_cost_stay_explicit(tmp_path: Path) -> None:
    trace = RunTrace(tmp_path, stream=io.StringIO(), heartbeat_seconds=0)
    for usage, cost in [({"input_tokens": 100, "output_tokens": 20}, 0.01), ({}, None)]:
        trace.emit({"event": "task_started", "stage": "qa"})
        trace.emit({"event": "task_finished", "stage": "qa", "usage": usage, "reported_cost_usd": cost})
    summary = trace.close(status="complete")
    assert summary["tokens"]["total_tokens"] is None
    assert summary["known_tokens"]["total_tokens"] == 120
    assert summary["usage_missing_calls"] == 1 and not summary["usage_complete"]
    assert summary["stages"]["qa"]["usage_reported_calls"] == 1
    assert summary["cost_reported_calls"] == 1 and not summary["cost_complete"]
    assert summary["provider_reported_cost_usd"] is None
    assert summary["known_provider_reported_cost_usd"] == 0.01


def test_trace_closes_heartbeat_and_rejects_logging_over_project_inputs(tmp_path: Path) -> None:
    trace = RunTrace(tmp_path, stream=io.StringIO(), heartbeat_seconds=0.01)
    trace.emit({"event": "stage_started", "stage": "qa"})
    trace.close(status="interrupted")
    assert trace.thread is not None and not trace.thread.is_alive()
    trace.emit({"event": "task_finished", "usage": {"input_tokens": 50}})
    path = tmp_path / "input/source/tasks.jsonl"
    with pytest.raises(ValueError, match="project logs"):
        RunTrace(tmp_path, log_file=path)
    assert not path.exists()


def test_timed_out_worker_finishes_before_return_and_usage_is_not_lost(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        "".join(
            json.dumps(
                {"custom_id": f"t-{n}", "agent": "x", "system": "s", "input": {}, "expected_output": {"format": "text"}}
            )
            + "\n"
            for n in range(2)
        )
    )
    release = threading.Event()
    finished = threading.Event()
    timer = threading.Timer(0.1, release.set)
    events = []

    def request(payload):
        if payload["metadata"]["custom_id"] == "t-0":
            release.wait(timeout=1)
            finished.set()
        return {"usage": {"input_tokens": 10, "output_tokens": 2}, "output_text": "ok"}

    timer.start()
    try:
        result = run_agent_tasks(
            tasks,
            tmp_path / "results.jsonl",
            model="fake",
            requester=request,
            concurrency=2,
            task_timeout=0.02,
            event_handler=events.append,
        )
    finally:
        release.set()
        timer.join()
    assert result.completed == 2 and finished.is_set()
    done = [e for e in events if e["event"] == "task_finished"]
    assert len(done) == 2 and sum(e["usage"]["input_tokens"] for e in done) == 20
    late = json.loads((tmp_path / "results.jsonl").read_text().splitlines()[0])
    assert late["deadline_exceeded"] and late["status"] == "completed"
    resumed = run_agent_tasks(tasks, tmp_path / "results.jsonl", model="fake", requester=request)
    assert resumed.skipped == 2
