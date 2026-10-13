import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SplitSummary:
    chapter_count: int


def split_numbered_chinese_txt(source_path: Path, out_dir: Path, *, encoding: str = "utf-8") -> SplitSummary:
    text = source_path.read_text(encoding=encoding)
    matches = list(re.finditer(r"(?m)^第([0-9一二三四五六七八九十百千万零〇两]+)章[^\n\r]*", text))
    out_dir.mkdir(parents=True, exist_ok=True)

    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapter_text = text[match.start() : next_start].strip()
        (out_dir / f"{index + 1:04d}.txt").write_text(chapter_text, encoding="utf-8")

    return SplitSummary(chapter_count=len(matches))
