from __future__ import annotations

import json
import math
import os
import platform
import re
import sys
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Event, Lock, Thread
from typing import TextIO

from litrelay.project_storage import write_json

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
)
ALLOWED_FIELDS = {
    "event",
    "stage",
    "stage_id",
    "task_id",
    "attempt",
    "chapter",
    "backend",
    "model",
    "agent",
    "status",
    "valid_output",
    "duration_ms",
    "total",
    "accepted",
    "existing",
    "missing",
    "generated",
    "samples",
    "tasks",
    "completed",
    "failed",
    "skipped",
    "concurrency",
    "usage",
    "input_chars",
    "output_chars",
    "response_id",
    "error",
    "error_type",
    "error_code",
    "scores",
    "failed_metrics",
    "issue_count",
    "reported_cost_usd",
    "result_path",
    "reason",
    "source_language",
    "target_language",
    "profile",
    "translation",
    "support",
    "bootstrap_ready",
    "formats",
    "count",
}


def normalize_usage(usage: dict) -> dict[str, int | None]:
    def integer(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    input_tokens = integer(usage.get("input_tokens", usage.get("prompt_tokens")))
    output_tokens = integer(usage.get("output_tokens", usage.get("completion_tokens")))
    cached = integer(usage.get("cached_input_tokens"))
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    details = details if isinstance(details, dict) else {}
    if cached is None:
        cached = integer(details.get("cached_tokens"))
    written = integer(usage.get("cache_creation_input_tokens"))
    if "cache_read_input_tokens" in usage or written is not None:
        cached = integer(usage.get("cache_read_input_tokens"))
        if input_tokens is not None:
            input_tokens += (cached or 0) + (written or 0)
    reasoning = integer(usage.get("reasoning_output_tokens"))
    if reasoning is None:
        details = usage.get("output_tokens_details") or {}
        reasoning = integer(details.get("reasoning_tokens")) if isinstance(details, dict) else None
    total = integer(usage.get("total_tokens"))
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return dict(zip(TOKEN_FIELDS, [input_tokens, output_tokens, cached, written, reasoning, total], strict=True))


def redact(text: str) -> str:
    text = re.sub(r'(\b(?:Bearer|Basic)\s+)[^\s;,\'"]+', r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r'(?i)(\b(?:api[_-]?key|password|access_token|token)\s*[=:]\s*)[^\s;,\'"]+', r"\1[REDACTED]", text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)", "[REDACTED]", text)
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)[:1000]


class RunTrace:
    def __init__(
        self,
        project: Path,
        *,
        log_file: Path | None = None,
        stream: TextIO | None = None,
        heartbeat_seconds: float = 15,
    ) -> None:
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        self.started = time.monotonic()
        self.started_at = datetime.now(UTC).isoformat()
        self.stream = stream or sys.stderr
        self.lock = Lock()
        self.stop = Event()
        self.closed = False
        directory = project.resolve() / "work/logs"
        if (
            log_file
            and log_file.resolve().is_relative_to(project.resolve())
            and not log_file.resolve().is_relative_to(directory)
        ):
            raise ValueError("Custom journals inside a project must stay in project logs (work/logs)")
        directory.mkdir(parents=True, exist_ok=True)
        self.journal = log_file.resolve() if log_file else directory / f"run-{self.run_id}.jsonl"
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path = directory / f"run-{self.run_id}.summary.json"
        existed = self.journal.exists()
        self.handle = self.journal.open("a", encoding="utf-8")
        if not existed:
            self.journal.chmod(0o600)
        self.active = {}
        self.provider_calls = 0
        self.cache_hits = 0
        self.retries = 0
        self.errors = 0
        self.timeouts = 0
        self.invalid_outputs = 0
        self.reported = 0
        self.reported_cost = 0.0
        self.cost_coverage = 0
        self.qa_passed = self.qa_failed = 0
        self.models = set()
        self.token_sums = defaultdict(int)
        self.token_coverage = defaultdict(int)
        self.stages = defaultdict(
            lambda: {
                "runs": 0,
                "duration_ms": 0,
                "provider_calls": 0,
                "errors": 0,
                "task_timeouts": 0,
                "cache_hits": 0,
                "usage_reported_calls": 0,
                "tokens": defaultdict(int),
                "token_coverage": defaultdict(int),
            }
        )
        self.thread = (
            Thread(target=self._heartbeat, args=(heartbeat_seconds,), daemon=True) if heartbeat_seconds > 0 else None
        )
        if self.thread:
            self.thread.start()
        self.emit({"event": "run_started"})

    def emit(self, event: dict) -> None:
        row = {k: v for k, v in event.items() if k in ALLOWED_FIELDS}
        for field in ["error_type", "error_code"]:
            value = row.get(field)
            if value is not None and (
                not isinstance(value, str) or not re.fullmatch(r"[\w]{1,80}", value, flags=re.ASCII)
            ):
                row[field] = None
        if row.get("error"):
            row["error"] = row.get("error_code") or row.get("error_type") or "stage_error"
        row = self._sanitize(row)
        if event.get("event") == "task_finished":
            raw_usage = event.get("usage")
            row["usage"] = normalize_usage(raw_usage if isinstance(raw_usage, dict) else {})
        with self.lock:
            if self.closed:
                return
            kind = row["event"]
            stage = row.get("stage", "run")
            sid = row.get("stage_id", stage)
            row.update(
                {
                    "run_id": self.run_id,
                    "time_utc": datetime.now(UTC).isoformat(),
                    "elapsed_seconds": round(time.monotonic() - self.started, 3),
                }
            )
            if kind == "stage_started":
                self.active[sid] = (stage, time.monotonic())
                self.stages[stage]["runs"] += 1
            elif kind in {"stage_finished", "stage_failed"}:
                self.active.pop(sid, None)
                self.stages[stage]["duration_ms"] += row.get("duration_ms", 0)
            elif kind == "task_started":
                self.provider_calls += 1
                self.stages[stage]["provider_calls"] += 1
                self.retries += int(row.get("attempt", 1) > 1)
                self.models.add((row.get("backend"), row.get("model")))
            elif kind == "cache_hit":
                count = row.get("count", 1)
                self.cache_hits += count
                self.stages[stage]["cache_hits"] += count
            elif kind == "task_finished":
                usage = row["usage"]
                self.reported += int(usage["input_tokens"] is not None and usage["output_tokens"] is not None)
                self.stages[stage]["usage_reported_calls"] += int(
                    usage["input_tokens"] is not None and usage["output_tokens"] is not None
                )
                for field, value in usage.items():
                    if value is not None:
                        self.token_sums[field] += value
                        self.token_coverage[field] += 1
                        self.stages[stage]["tokens"][field] += value
                        self.stages[stage]["token_coverage"][field] += 1
                cost = row.get("reported_cost_usd")
                if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
                    self.reported_cost += cost
                    self.cost_coverage += 1
                if row.get("status") == "error":
                    self.errors += 1
                    self.stages[stage]["errors"] += 1
                elif row.get("valid_output") is False:
                    self.invalid_outputs += 1
            elif kind == "qa_result":
                self.qa_passed += int(row.get("status") == "pass")
                self.qa_failed += int(row.get("status") != "pass")
            elif kind == "task_timeout":
                self.timeouts += 1
                self.stages[stage]["task_timeouts"] += 1
            self.handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.handle.flush()
            message = self._message(row)
            if message:
                print(f"[+{row['elapsed_seconds']:.1f}s] {message}", file=self.stream, flush=True)

    def _sanitize(self, value):
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, list):
            return [self._sanitize(x) for x in value[:30]]
        if isinstance(value, dict):
            return {k: self._sanitize(v) for k, v in value.items()}
        return value

    def _message(self, row: dict) -> str:
        kind = row["event"]
        stage = row.get("stage", "run")
        task = row.get("task_id", "")
        if kind == "run_started":
            return f"Debug journal: {self.journal}"
        if kind == "stage_started":
            return f"{stage} started: tasks={row.get('tasks', '-')} concurrency={row.get('concurrency', '-')} model={row.get('model', '-')}"
        if kind == "task_started":
            return f"{stage} {task} attempt={row.get('attempt', 1)} started"
        if kind == "task_finished":
            usage = row["usage"]
            tokens = (
                "usage=unknown"
                if usage["input_tokens"] is None
                else f"tokens in={usage['input_tokens']} out={usage['output_tokens']} cached={usage['cached_input_tokens']} reasoning={usage['reasoning_tokens']}"
            )
            return f"{stage} {task} {row.get('status')} {row.get('duration_ms', 0) / 1000:.2f}s {tokens}" + (
                f" error={row['error']}" if row.get("error") else ""
            )
        if kind == "cache_hit":
            return f"{stage} cache hit: {task or row.get('count', 1)}"
        if kind in {"stage_finished", "stage_failed"}:
            return f"{stage} {kind.removeprefix('stage_')} {row.get('duration_ms', 0) / 1000:.2f}s completed={row.get('completed', '-')} failed={row.get('failed', '-')} skipped={row.get('skipped', '-')}"
        if kind == "task_timeout":
            return f"{stage} {task} timed out; waiting for active requests to stop"
        if kind == "qa_result":
            return f"QA {row.get('chapter')} {row.get('status')}: {row.get('scores')} failed={row.get('failed_metrics', [])}"
        if kind in {
            "inputs_validated",
            "chapter_accepted",
            "run_failed",
            "run_finished",
            "export_started",
            "export_finished",
            "bootstrap_ready",
            "bootstrap_started",
        }:
            return f"{kind}: " + json.dumps(
                {k: v for k, v in row.items() if k not in {"event", "run_id", "time_utc", "elapsed_seconds"}},
                ensure_ascii=False,
            )
        return ""

    def _heartbeat(self, interval: float) -> None:
        while not self.stop.wait(interval):
            with self.lock:
                if self.closed:
                    return
                for stage, started in self.active.values():
                    print(
                        f"[+{time.monotonic() - self.started:.1f}s] {stage} still running ({time.monotonic() - started:.1f}s); calls={self.provider_calls} cache_hits={self.cache_hits}",
                        file=self.stream,
                        flush=True,
                    )

    def close(self, *, status: str, error: BaseException | None = None) -> dict:
        error_type = type(error).__name__ if error else None
        self.emit(
            {
                "event": "run_failed" if status in {"failed", "interrupted"} else "run_finished",
                "status": status,
                "error": error_type,
                "error_type": error_type,
            }
        )
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=1)
        with self.lock:
            self.closed = True
            self.handle.close()
            tokens = {
                k: self.token_sums[k] if self.token_coverage[k] == self.provider_calls else None for k in TOKEN_FIELDS
            }
            try:
                package_version = version("litrelay")
            except PackageNotFoundError:
                package_version = "uninstalled"
            summary = {
                "version": 1,
                "run_id": self.run_id,
                "status": status,
                "error": error_type,
                "litrelay_version": package_version,
                "python_version": platform.python_version(),
                "platform": platform.system(),
                "process_id": os.getpid(),
                "started_at_utc": self.started_at,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "duration_seconds": round(time.monotonic() - self.started, 3),
                "provider_calls": self.provider_calls,
                "cache_hits": self.cache_hits,
                "retry_attempts": self.retries,
                "errors": self.errors,
                "task_timeouts": self.timeouts,
                "invalid_outputs": self.invalid_outputs,
                "usage_reported_calls": self.reported,
                "usage_missing_calls": self.provider_calls - self.reported,
                "usage_complete": self.reported == self.provider_calls,
                "tokens": tokens,
                "known_tokens": {k: self.token_sums[k] for k in TOKEN_FIELDS},
                "token_coverage": dict(self.token_coverage),
                "stages": dict(self.stages),
                "models": [{"backend": b, "model": m} for b, m in sorted(self.models, key=str)],
                "qa_checks_passed": self.qa_passed,
                "qa_checks_failed": self.qa_failed,
                "provider_reported_cost_usd": round(self.reported_cost, 8)
                if self.cost_coverage == self.provider_calls
                else None,
                "known_provider_reported_cost_usd": round(self.reported_cost, 8),
                "cost_reported_calls": self.cost_coverage,
                "cost_complete": self.cost_coverage == self.provider_calls,
                "journal": str(self.journal),
                "summary": str(self.summary_path),
            }
            for stage in summary["stages"].values():
                stage["known_tokens"] = {k: stage["tokens"][k] for k in TOKEN_FIELDS}
                stage["tokens"] = {
                    k: stage["tokens"][k] if stage["token_coverage"][k] == stage["provider_calls"] else None
                    for k in TOKEN_FIELDS
                }
            write_json(self.summary_path, summary)
            self.summary_path.chmod(0o600)
        return summary


def latest_summary(project: Path) -> dict:
    directory = (project / "work/logs").resolve()
    files = list(directory.glob("run-*.summary.json"))
    if not files:
        raise ValueError("No debug runs yet; run with --debug first")
    path = max(files, key=lambda p: p.stat().st_mtime)
    if not path.resolve().is_relative_to(directory):
        raise ValueError("Telemetry summary must stay in project logs")
    return json.loads(path.read_text(encoding="utf-8"))
