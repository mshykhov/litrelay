import json
from pathlib import Path
from typing import Any

ALIGNMENT_AUDITOR_SYSTEM = """You are a professional Chinese-to-Russian literary translation auditor.

Goal: verify whether a Chinese source chapter and an existing Russian translation chapter are the same narrative chapter.

You must act like a senior web-novel translator and editor:
- compare events, entities, scene progression, character names, places, artifacts, magic terms, and chapter-title meaning;
- do not rely only on chapter numbers;
- allow natural localization and title adaptation;
- flag likely off-by-one, missing, duplicated, or wrong-source chapters;
- verify your own conclusion before returning.

Return JSON only. Do not include markdown."""


GLOSSARY_EXTRACTOR_SYSTEM = """You are a professional web-novel translation terminologist.

Goal: extract stable Chinese -> Russian glossary terms from aligned chapters so future chapters can be translated consistently.

You must act like a senior Chinese-to-Russian fantasy translator:
- extract only terms that must remain consistent across chapters;
- prefer names, places, organizations, races, artifacts, spells, ranks, cosmology, and recurring concepts;
- skip ordinary words and one-off phrasing;
- verify that the Russian term is actually supported by the provided translation;
- keep notes short and practical;
- do not use commas inside CSV fields; replace internal commas with semicolons.

Return CSV only with the requested header. Do not include markdown."""


def build_alignment_task(
    *,
    chapter_id: str,
    source_title: str,
    ru_title: str,
    source_text: str,
    ru_text: str,
) -> dict[str, Any]:
    return {
        "custom_id": f"alignment-{chapter_id}",
        "agent": "alignment-auditor",
        "system": ALIGNMENT_AUDITOR_SYSTEM,
        "input": {
            "chapter_id": chapter_id,
            "source_title": source_title,
            "ru_title": ru_title,
            "source_text": source_text,
            "ru_text": ru_text,
        },
        "expected_output": {
            "format": "json",
            "required_fields": [
                "chapter_id",
                "verdict",
                "confidence",
                "evidence",
                "issues",
                "recommended_action",
            ],
            "verdict_values": ["aligned", "misaligned", "uncertain"],
        },
    }


def build_glossary_task(*, chapter_id: str, prompt: str) -> dict[str, Any]:
    return {
        "custom_id": f"glossary-{chapter_id}",
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


def write_jsonl(tasks: list[dict[str, Any]], out_jsonl: Path) -> None:
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as jsonl_file:
        for task in tasks:
            jsonl_file.write(json.dumps(task, ensure_ascii=False) + "\n")
