from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Requester = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AgentRunSummary:
    completed: int
    failed: int
    skipped: int


ALIGNMENT_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "chapter_id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["aligned", "misaligned", "uncertain"]},
        "confidence": {"type": "number"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {"type": "string"},
    },
    "required": [
        "chapter_id",
        "verdict",
        "confidence",
        "evidence",
        "issues",
        "recommended_action",
    ],
    "additionalProperties": False,
}


TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "chapter_id": {"type": "string"},
        "translation": {"type": "string"},
        "qa": {
            "type": "object",
            "properties": {
                "terminology_checked": {"type": "boolean"},
                "omission_risk": {"type": "string", "enum": ["low", "medium", "high"]},
                "style_match": {"type": "string", "enum": ["good", "mixed", "poor"]},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["terminology_checked", "omission_risk", "style_match", "issues"],
            "additionalProperties": False,
        },
    },
    "required": ["chapter_id", "translation", "qa"],
    "additionalProperties": False,
}


TRANSLATION_QA_SCHEMA = {
    "type": "object",
    "properties": {
        "chapter_id": {"type": "string"},
        "meaning_score": {"type": "number"},
        "terminology_score": {"type": "number"},
        "style_score": {"type": "number"},
        "omission_score": {"type": "number"},
        "verdict": {"type": "string", "enum": ["pass", "needs_revision", "fail"]},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": {"type": "string"}},
        "missing_or_changed_facts": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {"type": "string"},
    },
    "required": [
        "chapter_id",
        "meaning_score",
        "terminology_score",
        "style_score",
        "omission_score",
        "verdict",
        "strengths",
        "issues",
        "missing_or_changed_facts",
        "recommended_action",
    ],
    "additionalProperties": False,
}


def build_responses_payload(
    task: dict[str, Any],
    *,
    model: str,
    max_output_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "store": False,
        "input": [
            {"role": "system", "content": task["system"]},
            {"role": "user", "content": json.dumps(task["input"], ensure_ascii=False)},
        ],
        "metadata": {
            "custom_id": task["custom_id"],
            "agent": task["agent"],
        },
        "text": {"format": _format_for_task(task)},
    }
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    if reasoning_effort is not None:
        payload["reasoning"] = {"effort": reasoning_effort}
    return payload


def extract_response_text(response: dict[str, Any]) -> str:
    texts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content_part in item.get("content", []):
            if isinstance(content_part, dict) and content_part.get("type") == "output_text":
                texts.append(str(content_part.get("text", "")))
    if texts:
        return "".join(texts)
    return str(response.get("output_text", ""))


def run_agent_tasks(
    input_jsonl: Path,
    output_jsonl: Path,
    *,
    model: str,
    max_output_tokens: int | None = None,
    limit: int | None = None,
    resume: bool = True,
    requester: Requester | None = None,
    api_key: str | None = None,
    reasoning_effort: str | None = None,
    concurrency: int = 1,
    max_retries: int = 0,
    task_timeout: float | None = None,
) -> AgentRunSummary:
    existing_ids = _read_completed_ids(output_jsonl) if resume else set()
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    if requester is None:
        resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when no requester is provided")

        def requester(payload: dict[str, Any]) -> dict[str, Any]:
            return call_openai_responses(payload, api_key=resolved_api_key)

    pending: list[dict[str, Any]] = []
    skipped = 0
    with input_jsonl.open(encoding="utf-8") as input_file:
        for line in input_file:
            if not line.strip():
                continue
            if limit is not None and len(pending) >= limit:
                break
            task = json.loads(line)
            if task["custom_id"] in existing_ids:
                skipped += 1
                continue
            pending.append(task)

    def run_one(task: dict[str, Any]) -> dict[str, Any]:
        payload = build_responses_payload(
            task,
            model=model,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
        )
        result = _run_single_task(task, payload, requester)
        attempts = 0
        while (
            attempts < max_retries and result["status"] == "completed" and not _is_valid_output(task, result["output"])
        ):
            attempts += 1
            result = _run_single_task(task, payload, requester)
        return result

    completed = 0
    failed = 0
    mode = "a" if resume else "w"
    with output_jsonl.open(mode, encoding="utf-8") as output_file:

        def record(result: dict[str, Any]) -> None:
            nonlocal completed, failed
            if result["status"] == "completed":
                completed += 1
            else:
                failed += 1
            output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
            output_file.flush()

        if concurrency > 1 and len(pending) > 1:
            executor = ThreadPoolExecutor(max_workers=concurrency)
            try:
                futures = {executor.submit(run_one, task): task for task in pending}
                for future, task in futures.items():
                    if task_timeout is None:
                        record(future.result())
                        continue
                    try:
                        record(future.result(timeout=task_timeout))
                    except FuturesTimeoutError:
                        future.cancel()
                        record(_timeout_result(task, task_timeout))
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            for task in pending:
                record(run_one(task))

    return AgentRunSummary(completed=completed, failed=failed, skipped=skipped)


def call_openai_responses(
    payload: dict[str, Any],
    *,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI Responses API error {error.code}: {body}") from error


def _is_valid_output(task: dict[str, Any], output: str) -> bool:
    fmt = task.get("expected_output", {}).get("format")
    if fmt == "translation_json":
        try:
            parsed = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return False
        return (
            isinstance(parsed, dict)
            and isinstance(parsed.get("chapter_id"), str)
            and isinstance(parsed.get("translation"), str)
            and bool(parsed["translation"].strip())
            and isinstance(parsed.get("qa"), dict)
        )
    if fmt in ("json", "translation_qa_json"):
        try:
            json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return False
        return True
    if fmt == "csv":
        return bool(output.strip()) and "," in output
    return True


def _run_single_task(task: dict[str, Any], payload: dict[str, Any], requester: Requester) -> dict[str, Any]:
    start = time.monotonic()
    try:
        response = requester(payload)
        return {
            "custom_id": task["custom_id"],
            "agent": task["agent"],
            "status": "completed",
            "response_id": response.get("id"),
            "model": response.get("model"),
            "service_tier": response.get("service_tier"),
            "usage": response.get("usage", {}),
            "output": extract_response_text(response),
            "duration_ms": int((time.monotonic() - start) * 1000),
            "error": None,
        }
    except Exception as error:
        return {
            "custom_id": task["custom_id"],
            "agent": task["agent"],
            "status": "error",
            "response_id": None,
            "model": payload.get("model"),
            "service_tier": None,
            "usage": {},
            "output": "",
            "duration_ms": int((time.monotonic() - start) * 1000),
            "error": str(error),
        }


def _timeout_result(task: dict[str, Any], timeout: float) -> dict[str, Any]:
    return {
        "custom_id": task["custom_id"],
        "agent": task["agent"],
        "status": "error",
        "response_id": None,
        "model": None,
        "service_tier": None,
        "usage": {},
        "output": "",
        "duration_ms": int(timeout * 1000),
        "error": f"task timed out after {timeout}s",
    }


def _format_for_task(task: dict[str, Any]) -> dict[str, Any]:
    expected_output = task.get("expected_output", {})
    output_format = expected_output.get("format")
    if output_format == "json":
        return {
            "type": "json_schema",
            "name": "alignment_audit",
            "strict": True,
            "schema": ALIGNMENT_AUDIT_SCHEMA,
        }
    if output_format == "translation_json":
        return {
            "type": "json_schema",
            "name": "chapter_translation",
            "strict": True,
            "schema": TRANSLATION_SCHEMA,
        }
    if output_format == "translation_qa_json":
        return {
            "type": "json_schema",
            "name": "translation_quality_audit",
            "strict": True,
            "schema": TRANSLATION_QA_SCHEMA,
        }
    return {"type": "text"}


def _read_completed_ids(output_jsonl: Path) -> set[str]:
    if not output_jsonl.exists():
        return set()

    ids = set()
    with output_jsonl.open(encoding="utf-8") as result_file:
        for line in result_file:
            if not line.strip():
                continue
            result = json.loads(line)
            if result.get("status") == "completed":
                ids.add(result["custom_id"])
    return ids
