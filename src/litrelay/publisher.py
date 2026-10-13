from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

CHAPTER_NUMBER_RE = re.compile(r"^\s*Глава\s+\d+\.?")


@dataclass(frozen=True)
class PublishSummary:
    published: int
    target: str


class Publisher(Protocol):
    def publish(self, chapters_dir: Path, manifest: dict[str, Any]) -> PublishSummary: ...


def split_title_body(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    title = lines[0].strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    return title, body


def chapter_html(body: str) -> str:
    paragraphs = [_escape(line.strip()) for line in body.splitlines() if line.strip()]
    return "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)


def build_chapter_payload(text: str, *, status: str = "publish") -> dict[str, str]:
    title, body = split_title_body(text)
    return {"title": title, "content": chapter_html(body), "status": status}


def renumber_title(title: str, number: int) -> str:
    if CHAPTER_NUMBER_RE.match(title):
        return CHAPTER_NUMBER_RE.sub(f"Глава {number}.", title, count=1).strip()
    return f"Глава {number}. {title}".strip()


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass(frozen=True)
class LocalExportPublisher:
    out_dir: Path

    def publish(self, chapters_dir: Path, manifest: dict[str, Any]) -> PublishSummary:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        published = 0
        for path in sorted(chapters_dir.glob("*.txt")):
            (self.out_dir / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            published += 1
        return PublishSummary(published=published, target=str(self.out_dir))
