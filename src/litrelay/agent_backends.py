from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
from collections.abc import Callable
from threading import Event, Lock
from typing import Any

CliRunner = Callable[[list[str], str], str]

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9]*\n?|\n?```$")


class BackendError(RuntimeError):
    def __init__(self, message: str, *, code: str, usage: dict | None = None, cost: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.usage = usage or {}
        self.reported_cost_usd = cost


def _cli_argv(backend: str, model: str | None) -> list[str]:
    if backend == "claude":
        # --max-turns 1 + --disallowedTools stop the agentic loop that otherwise hangs
        # on evaluation-style prompts. Empty --mcp-config disables MCP servers. --bare is
        # avoided because it forces ANTHROPIC_API_KEY auth, which OAuth users do not have.
        argv = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--max-turns",
            "1",
            "--disallowedTools",
            "*",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--dangerously-skip-permissions",
        ]
        return argv + (["--model", model] if model else [])
    if backend == "codex":
        argv = [
            "codex",
            "exec",
            "-",
            "--json",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "-c",
            "model_reasoning_effort=low",
        ]
        return argv + (["-m", model] if model else [])
    raise KeyError(backend)


def make_requester(backend: str, model: str | None, timeout: int) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
    if backend == "openai":
        return None
    return build_cli_requester(backend, model=model, timeout=timeout)


def build_cli_requester(
    backend: str,
    *,
    model: str | None = None,
    command: list[str] | None = None,
    timeout: int = 900,
    runner: CliRunner | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    argv = command or _cli_argv(backend, model)
    run = runner or _make_subprocess_runner(timeout)

    def requester(payload: dict[str, Any]) -> dict[str, Any]:
        prompt = _build_prompt(payload)
        raw = run(argv, prompt)
        cost = None
        if backend == "codex":
            answer, usage = _parse_codex_jsonl(raw)
        else:
            answer, usage = raw, {}
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                result = None
            if isinstance(result, dict) and result.get("type") == "result":
                usage = result.get("usage") or {}
                cost = result.get("total_cost_usd")
                if result.get("is_error"):
                    raise BackendError(
                        f"Claude CLI error: {result.get('result', result.get('subtype', 'unknown'))}",
                        code="claude_result_error",
                        usage=usage,
                        cost=cost,
                    )
                answer = result.get("result", "")
        text = _extract_output(answer, payload)
        return {
            "id": f"cli-{backend}",
            "model": payload.get("model", model or backend),
            "output": [{"content": [{"type": "output_text", "text": text}]}],
            "usage": usage,
            "reported_cost_usd": cost,
        }

    requester.cancel = getattr(run, "cancel", lambda: None)
    return requester


def _parse_codex_jsonl(raw: str) -> tuple[str, dict[str, Any]]:
    parts: list[str] = []
    usage: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        elif event.get("type") == "turn.completed":
            event_usage = event.get("usage")
            if isinstance(event_usage, dict):
                usage = event_usage
    return "\n".join(parts), usage


def _build_prompt(payload: dict[str, Any]) -> str:
    messages = payload.get("input", [])
    system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    instruction = _format_instruction(payload.get("text", {}).get("format", {}))
    return f"{system}\n\n{user}\n\n{instruction}".strip()


def _format_instruction(fmt: dict[str, Any]) -> str:
    if fmt.get("type") == "json_schema":
        schema = json.dumps(fmt.get("schema", {}), ensure_ascii=False)
        return (
            "Output ONLY one raw JSON object that conforms to this JSON schema. "
            "No markdown, no code fences, no commentary before or after.\n"
            f"Schema: {schema}"
        )
    return "Output ONLY the requested content with no markdown code fences and no commentary."


def _extract_output(raw: str, payload: dict[str, Any]) -> str:
    text = _strip_fences(raw.strip())
    if payload.get("text", {}).get("format", {}).get("type") == "json_schema":
        return _extract_json_object(text)
    return text


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", _FENCE_RE.sub("", text)).strip()


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _make_subprocess_runner(timeout: int) -> CliRunner:
    active: set[subprocess.Popen] = set()
    lock = Lock()
    canceled = Event()

    def cancel() -> None:
        with lock:
            canceled.set()
            processes = list(active)
        for process in processes:
            _kill_group(process)

    def run(argv: list[str], prompt: str) -> str:
        with (
            tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out,
            tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as err,
        ):
            with lock:
                if canceled.is_set():
                    raise BackendError("CLI request canceled", code="cli_canceled")
                process = subprocess.Popen(
                    argv, stdin=subprocess.PIPE, stdout=out, stderr=err, text=True, start_new_session=True
                )
                active.add(process)
            try:
                process.communicate(input=prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(process)
                raise BackendError(f"CLI backend {argv[0]} timed out after {timeout}s", code="cli_timeout") from None
            except BaseException:
                _kill_group(process)
                raise
            finally:
                with lock:
                    active.discard(process)
            out.seek(0)
            err.seek(0)
            if process.returncode != 0:
                raise BackendError(
                    f"CLI backend {argv[0]} failed: {err.read().strip()[:500]}",
                    code=f"cli_exit_{abs(process.returncode)}",
                )
            return out.read()

    run.cancel = cancel
    return run


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
