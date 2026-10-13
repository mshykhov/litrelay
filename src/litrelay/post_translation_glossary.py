from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from litrelay.glossary_subset import read_chapter_glossary
from litrelay.llm_agent_inputs import GLOSSARY_EXTRACTOR_SYSTEM


def write_post_translation_glossary_tasks(
    *,
    source_dir: Path,
    translation_results_jsonl: Path,
    glossary_csv: Path,
    out_jsonl: Path,
    glossary_subset_dir: Path | None = None,
) -> int:
    fallback_glossary = glossary_csv.read_text(encoding="utf-8")
    tasks = []
    for result in _read_jsonl(translation_results_jsonl):
        if result.get("status") != "completed":
            continue
        output = _parse_translation_output(str(result.get("output", "")))
        if output is None:
            continue
        chapter_id = str(output["chapter_id"])
        source_text = (source_dir / f"{chapter_id}.txt").read_text(encoding="utf-8")
        tasks.append(
            _build_post_translation_glossary_task(
                chapter_id=chapter_id,
                source_text=source_text,
                generated_translation=str(output["translation"]),
                current_glossary=read_chapter_glossary(
                    chapter_id, glossary_subset_dir=glossary_subset_dir, fallback_text=fallback_glossary
                ),
            )
        )

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as jsonl_file:
        for task in tasks:
            jsonl_file.write(json.dumps(task, ensure_ascii=False) + "\n")
    return len(tasks)


def _build_post_translation_glossary_task(
    *,
    chapter_id: str,
    source_text: str,
    generated_translation: str,
    current_glossary: str,
) -> dict[str, Any]:
    prompt = f"""Extract glossary candidates after translating chapter {chapter_id}.

Goal: find terms that should be added to the next glossary version or terms whose generated Russian translation conflicts with the current glossary.

Rules:
- focus on new named entities, places, ranks, magic schools, spells, artifacts, and recurring concepts;
- include a term if it is absent from current glossary but appears important;
- include a term if the generated translation uses a Russian variant that conflicts with current glossary;
- skip terms already handled correctly by current glossary;
- do not use commas inside CSV fields; replace internal commas with semicolons.

Return CSV only:
source,target_ru,type,note,confidence

<CURRENT_GLOSSARY>
{current_glossary.strip()}
</CURRENT_GLOSSARY>

<SOURCE_CHAPTER>
{source_text.strip()}
</SOURCE_CHAPTER>

<GENERATED_RUSSIAN_TRANSLATION>
{generated_translation.strip()}
</GENERATED_RUSSIAN_TRANSLATION>
"""
    return {
        "custom_id": f"post-glossary-{chapter_id}",
        "agent": "glossary-extractor",
        "system": GLOSSARY_EXTRACTOR_SYSTEM,
        "input": {
            "chapter_id": chapter_id,
            "prompt": prompt,
        },
        "expected_output": {
            "format": "csv",
            "header": "source,target_ru,type,note,confidence",
        },
    }


def _parse_translation_output(output: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if not isinstance(parsed.get("chapter_id"), str):
        return None
    if not isinstance(parsed.get("translation"), str):
        return None
    return parsed


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            if line.strip():
                rows.append(json.loads(line))
    return rows
