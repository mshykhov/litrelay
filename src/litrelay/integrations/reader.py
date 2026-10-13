from __future__ import annotations

import base64
import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from litrelay.publisher import PublishSummary, build_chapter_payload, renumber_title

ChapterPoster = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class ReaderApiPublisher:
    base_url: str
    book_id: int
    username: str
    app_password: str
    status: str = "publish"
    renumber_from: int | None = None
    poster: ChapterPoster | None = None

    def publish(self, chapters_dir: Path, manifest: dict[str, Any]) -> PublishSummary:
        post = self.poster or self._post
        url = f"{self.base_url.rstrip('/')}/books/{self.book_id}/chapters"
        published = 0
        for index, path in enumerate(sorted(chapters_dir.glob("*.txt"))):
            payload = build_chapter_payload(path.read_text(encoding="utf-8"), status=self.status)
            if self.renumber_from is not None:
                payload["title"] = renumber_title(payload["title"], self.renumber_from + index)
            post(url, payload)
            published += 1
        return PublishSummary(published=published, target=url)

    def _post(self, url: str, payload: dict[str, Any]) -> None:
        token = base64.b64encode(f"{self.username}:{self.app_password}".encode()).decode()
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
                "Authorization": f"Basic {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()
