from __future__ import annotations

import base64
import html
import json
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from litrelay.book_inputs import heading_number
from litrelay.project_storage import write_json
from litrelay.publisher import build_chapter_payload

ApiCall = Callable[[str, str, dict | None], Any]


def reader_client(base_url: str, username: str, password: str) -> ApiCall:
    if urlparse(base_url).scheme != "https":
        raise ValueError("Reader base URL must use HTTPS")
    token = base64.b64encode(f"{username}:{password}".encode()).decode()

    def call(method: str, path: str, data: dict | None = None) -> Any:
        request = urllib.request.Request(
            base_url.rstrip("/") + path,
            data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "Authorization": "Basic " + token,
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    return call


def _norm(text: str) -> str:
    return (
        re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]*>", "", text)))
        .strip()
        .replace("…", "...")
        .replace(" – ", " - ")
        .replace(" — ", " - ")
        .replace("“", '"')
        .replace("”", '"')
    )


def sync_chapters(
    chapters: Path,
    *,
    book_id: int,
    call: ApiCall,
    checkpoint: Path,
    audio: bool = False,
    archive_book_id: int | None = None,
    status: str = "publish",
) -> dict:
    if book_id < 1 or (archive_book_id is not None and (archive_book_id < 1 or archive_book_id == book_id)):
        raise ValueError("Invalid book/archive IDs")
    files = {int(p.stem): p for p in chapters.glob("*.txt") if p.stem.isdigit()}
    if not files or set(files) != set(range(1, max(files) + 1)):
        raise ValueError("Reader sync needs the complete numbered book")

    def inventory() -> dict[int, dict]:
        rows = {}
        for row in call("GET", f"/books/{book_id}/chapters", None):
            n = heading_number(row["title"])
            if n is None or n in rows or n not in files:
                raise ValueError("Destination has ambiguous, duplicate or unrelated chapter numbers")
            rows[n] = row
        return rows

    current = inventory()
    result = {"book_id": book_id, "total": len(files), "chapters": {}}
    for n, path in sorted(files.items()):
        payload = build_chapter_payload(path.read_text(encoding="utf-8"), status=status)
        if heading_number(payload["title"]) != n:
            raise ValueError(f"Chapter {n}: Reader needs a numbered heading")
        row = current.get(n)
        if row and (
            _norm(row["content"]) != _norm(payload["content"])
            or _norm(row["title"]) != _norm(payload["title"])
            or row["status"] != status
        ):
            cached = call("GET", f"/audio-status/{row['id']}", None)
            if _norm(row["content"]) != _norm(payload["content"]) and (
                cached["ready"] or cached["state"] == "generating"
            ):
                if archive_book_id is None:
                    raise ValueError(
                        f"Chapter {n} has cached audio; provide an archive book ID before replacing its text"
                    )
                write_json(checkpoint.parent / f"backup-{row['id']}.json", row)
                call("PATCH", f"/chapters/{row['id']}", {"book": archive_book_id, "status": "draft"})
                row = None
            else:
                row = call("PATCH", f"/chapters/{row['id']}", payload)
        if row is None:
            try:
                row = call("POST", f"/books/{book_id}/chapters", {**payload, "position": len(current)})
            except (OSError, ValueError):
                recovered = inventory().get(n)
                if recovered is None or _norm(recovered["content"]) != _norm(payload["content"]):
                    raise
                row = recovered
        current[n] = row
        live = call("GET", f"/chapters/{row['id']}", None)
        if (
            live["book"] != book_id
            or live["status"] != status
            or _norm(live["content"]) != _norm(payload["content"])
            or _norm(live["title"]) != _norm(payload["title"])
        ):
            raise RuntimeError(f"Live chapter mismatch {n}")
        record = {"id": row["id"], "live_content_matches": True}
        if audio:
            s = call("GET", f"/audio-status/{row['id']}", None)
            if not (s["ready"] and s["timed"]):
                call("POST", f"/audio-enqueue/{row['id']}", {"priority": "high" if n == 1 else "low"})
                s = call("GET", f"/audio-status/{row['id']}", None)
            if not ((s["ready"] and s["timed"]) or s["state"] == "generating" or s["position"] > 0):
                raise RuntimeError(f"Audio job missing for chapter {n}")
            record["audio"] = {"state": s["state"], "persistent": True}
        result["chapters"][str(n)] = record
        write_json(checkpoint, result)
    ids = [current[n]["id"] for n in sorted(files)]
    book = call("PATCH", f"/books/{book_id}", {"chapter_ids": ids, "status": status})
    if book["chapter_ids"] != ids:
        raise RuntimeError("Reader order mismatch")
    result.update({"complete": True, "order_matches": True, "audio_started": audio})
    write_json(checkpoint, result)
    return result
