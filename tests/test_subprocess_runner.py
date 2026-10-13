import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from litrelay.agent_backends import (
    _cli_argv,
    _make_subprocess_runner,
    build_cli_requester,
    make_requester,
)


def test_subprocess_runner_returns_stdout() -> None:
    run = _make_subprocess_runner(timeout=10)
    assert run(["cat"], "hello") == "hello"


def test_subprocess_runner_raises_on_nonzero_exit() -> None:
    run = _make_subprocess_runner(timeout=10)
    with pytest.raises(RuntimeError):
        run(["sh", "-c", "echo boom >&2; exit 1"], "")


def test_subprocess_runner_times_out_fast_despite_grandchild_holding_stdout() -> None:
    # grandchild inherits stdout and outlives the parent; the old capture_output
    # impl would block forever on the post-kill pipe drain.
    run = _make_subprocess_runner(timeout=1)
    start = time.monotonic()
    with pytest.raises(RuntimeError):
        run(["sh", "-c", "( sleep 30 ) & sleep 30"], "")
    assert time.monotonic() - start < 8


def test_subprocess_runner_kills_grandchild_process_group(tmp_path) -> None:
    marker = tmp_path / "marker"
    run = _make_subprocess_runner(timeout=1)
    with pytest.raises(RuntimeError):
        run(["sh", "-c", f"( sleep 3; touch {marker} ) & sleep 30"], "")
    time.sleep(4)
    assert not marker.exists()


def test_cli_argv_claude_has_model_and_headless_flags() -> None:
    argv = _cli_argv("claude", "claude-opus-4-8")
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert "--disallowedTools" in argv
    assert "--strict-mcp-config" in argv
    assert "--dangerously-skip-permissions" in argv
    assert argv[-2:] == ["--model", "claude-opus-4-8"]


def test_cli_argv_codex_has_model_and_ignores_user_config() -> None:
    argv = _cli_argv("codex", "gpt-x")
    assert argv[:3] == ["codex", "exec", "-"]
    assert "--ignore-user-config" in argv
    assert "--skip-git-repo-check" in argv
    assert "model_reasoning_effort=low" in argv
    assert argv[argv.index("-m") + 1] == "gpt-x"


def test_cli_argv_no_model_omits_model_flag() -> None:
    argv = _cli_argv("claude", None)
    assert "--model" not in argv


def test_build_cli_requester_passes_model_into_argv() -> None:
    captured: dict = {}

    def fake_runner(argv: list[str], prompt: str) -> str:
        captured["argv"] = argv
        return "{}"

    requester = build_cli_requester("claude", model="claude-opus-4-8", runner=fake_runner)
    requester({"input": [{"role": "system", "content": "s"}], "text": {"format": {"type": "text"}}})

    assert "--model" in captured["argv"]
    assert "claude-opus-4-8" in captured["argv"]


def test_make_requester_openai_returns_none() -> None:
    assert make_requester("openai", "gpt-5.4", 300) is None


def test_make_requester_claude_returns_callable() -> None:
    assert callable(make_requester("claude", "claude-opus-4-8", 900))


def test_cli_cancellation_stops_active_process_and_prevents_new_calls(tmp_path) -> None:
    marker = tmp_path / "started"
    run = _make_subprocess_runner(timeout=30)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run, ["sh", "-c", f"touch {marker}; sleep 30"], "")
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        run.cancel()
        with pytest.raises(RuntimeError):
            future.result(timeout=3)
    with pytest.raises(RuntimeError, match="canceled"):
        run(["cat"], "must not start")
