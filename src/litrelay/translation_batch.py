from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from litrelay.pilot_tasks import build_translation_pilot_task


def write_translation_batch_tasks(
    *,
    source_dir: Path,
    context_dir: Path,
    glossary_csv: Path,
    out_jsonl: Path,
    start: int,
    end: int,
    context_window: int,
    style_guide: Path | None = None,
    recap: Path | None = None,
    glossary_subset_dir: Path | None = None,
) -> int:
    fallback_glossary_text = glossary_csv.read_text(encoding="utf-8")
    style_guide_text = style_guide.read_text(encoding="utf-8") if style_guide is not None else ""
    recap_text = recap.read_text(encoding="utf-8") if recap is not None else ""
    tasks = []
    for chapter_index in range(start, end + 1):
        chapter_id = f"{chapter_index:04d}"
        glossary_text = _read_chapter_glossary(
            chapter_id,
            fallback_glossary_text=fallback_glossary_text,
            glossary_subset_dir=glossary_subset_dir,
        )
        task = build_translation_pilot_task(
            chapter_id=chapter_id,
            source_text=(source_dir / f"{chapter_id}.txt").read_text(encoding="utf-8"),
            glossary_csv=glossary_text,
            context_chapters=_read_context_chapters(
                context_dir,
                chapter_index=chapter_index,
                context_window=context_window,
            ),
        )
        task["input"]["style_guide"] = style_guide_text
        task["input"]["recap"] = recap_text
        tasks.append(task)

    _write_jsonl(tasks, out_jsonl)
    return len(tasks)


def _read_chapter_glossary(
    chapter_id: str,
    *,
    fallback_glossary_text: str,
    glossary_subset_dir: Path | None,
) -> str:
    if glossary_subset_dir is None:
        return fallback_glossary_text
    subset_path = glossary_subset_dir / f"{chapter_id}.csv"
    if subset_path.exists():
        return subset_path.read_text(encoding="utf-8")
    return fallback_glossary_text


def _read_context_chapters(context_dir: Path, *, chapter_index: int, context_window: int) -> list[tuple[str, str]]:
    context = []
    start = max(1, chapter_index - context_window)
    for index in range(start, chapter_index):
        chapter_id = f"{index:04d}"
        path = context_dir / f"{chapter_id}.txt"
        if path.exists():
            context.append((chapter_id, path.read_text(encoding="utf-8")))
    return context


def _write_jsonl(tasks: list[dict[str, Any]], out_jsonl: Path) -> None:
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as jsonl_file:
        for task in tasks:
            jsonl_file.write(json.dumps(task, ensure_ascii=False) + "\n")
