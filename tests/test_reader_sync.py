from pathlib import Path

import pytest

from litrelay.integrations.reader_sync import sync_chapters


def service():
    rows = {}
    calls = []
    queue = {}
    lose = [True]

    def call(method, path, data=None):
        calls.append((method, path, data))
        if method == "GET" and path.endswith("/chapters"):
            return list(rows.values())
        if method == "POST" and path.endswith("/chapters"):
            cid = len(rows) + 10
            row = {**data, "id": cid, "book": 1}
            rows[cid] = row
            if lose[0]:
                lose[0] = False
                raise OSError("response lost after server create")
            return row
        if method == "GET" and "/audio-status/" in path:
            return {
                "ready": False,
                "timed": False,
                "state": "queued" if path.split("/")[-1] in queue else "none",
                "position": 1 if path.split("/")[-1] in queue else 0,
            }
        if method == "POST" and "/audio-enqueue/" in path:
            queue[path.split("/")[-1]] = True
            return {"queued": True}
        if method == "GET" and "/chapters/" in path:
            return rows[int(path.split("/")[-1])]
        if method == "PATCH" and path == "/books/1":
            return {"chapter_ids": data["chapter_ids"]}
        raise AssertionError((method, path, data))

    return call, rows, calls


def test_sync_reconciles_unknown_create_and_repeated_run_never_duplicates(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "0001.txt").write_text("Глава 1. Начало\n\nПолный текст.")
    call, rows, calls = service()
    assert sync_chapters(chapters, book_id=1, call=call, checkpoint=tmp_path / "state.json", audio=True)["total"] == 1
    sync_chapters(chapters, book_id=1, call=call, checkpoint=tmp_path / "state.json", audio=True)
    assert len(rows) == 1
    assert len([x for x in calls if x[0] == "POST" and x[1].endswith("/chapters")]) == 1
    jobs = [x[2] for x in calls if "/audio-enqueue/" in x[1]]
    assert jobs and all("ttl_seconds" not in x and "ttl" not in x for x in jobs)


def test_changed_text_with_cached_audio_requires_explicit_archive(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "0001.txt").write_text("Глава 1. Начало\n\nНовый полный текст.")

    def call(method, path, data=None):
        if path.endswith("/chapters"):
            return [
                {
                    "id": 10,
                    "title": "Глава 1. Начало",
                    "content": "<p>Старый текст.</p>",
                    "book": 1,
                    "status": "publish",
                }
            ]
        if "audio-status" in path:
            return {"ready": True, "state": "ready", "timed": True, "position": 0}
        raise AssertionError("Mutation must not happen")

    with pytest.raises(ValueError, match="archive"):
        sync_chapters(chapters, book_id=1, call=call, checkpoint=tmp_path / "state.json")
