from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def project_lock(project: Path) -> Iterator[None]:
    path = project / "work/run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            pid = int(path.read_text())
            os.kill(pid, 0)
        except ProcessLookupError:
            path.unlink()
        except (ValueError, PermissionError):
            raise RuntimeError(f"Project lock needs inspection: {path}") from None
        else:
            raise RuntimeError(f"Project is already running (PID {pid})")
    try:
        with path.open("x") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError("Project is already running") from None
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
