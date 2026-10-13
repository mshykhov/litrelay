from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from litrelay.glossary_subset import read_chapter_glossary

TRANSLATION_AGENT_SYSTEM = """You are a professional Chinese-to-Russian fantasy web-novel translator.

Goal: translate the provided Chinese chapter into Russian while matching the established Russian translation style.

Use the provided glossary and recent Russian context. Do not use or infer from any reference translation for the target chapter.
Preserve scene order, facts, names, ranks, spell terminology, and tone.
Use glossary target terms, not rejected alternatives or source terms from glossary notes.
After translating, self-check for omissions, mistranslations, terminology drift, source residue, mixed-script names, near-miss name typos, pronoun/name consistency, and style drift.

Return JSON only. Do not include markdown."""


TRANSLATION_QUALITY_GATES = [
    "No source residue: do not leave Chinese characters or untranslated source terms in the Russian translation.",
    "No mixed Latin/Cyrillic proper names; do not place Latin letters inside Cyrillic names.",
    "No near-miss name typos: keep glossary character and proper-name targets recognizable when inflected; do not substitute similar-looking letters or vowels.",
    "Use glossary target_ru terms; do not copy alternatives, notes, or rejected variants into the translation.",
    "Keep character names, ranks, spell names, organizations, places, and cosmology terms consistent across the chapter.",
    "Use natural Russian web-novel prose; avoid literal Chinese syntax and heavy calques.",
    "Preserve all source facts, numbers, dialogue turns, and scene order without adding invented details.",
]


TRANSLATION_QA_SYSTEM = """You are a senior Chinese-to-Russian literary translation QA editor.

Goal: compare a model-generated Russian translation against the Chinese source and an existing Russian reference translation.

Use the reference translation only for quality evaluation. Judge meaning, omissions, terminology, style, and chapter-level coherence.
Be strict and concrete. Do not rewrite the full chapter.

Return JSON only. Do not include markdown."""


def build_translation_pilot_task(
    *,
    chapter_id: str,
    source_text: str,
    glossary_csv: str,
    context_chapters: list[tuple[str, str]],
) -> dict[str, Any]:
    return {
        "custom_id": f"translate-{chapter_id}",
        "agent": "translation-agent",
        "system": TRANSLATION_AGENT_SYSTEM,
        "input": {
            "chapter_id": chapter_id,
            "source_text": source_text,
            "glossary_csv": glossary_csv,
            "recent_russian_context": [
                {"chapter_id": context_id, "text": text} for context_id, text in context_chapters
            ],
            "quality_gates": TRANSLATION_QUALITY_GATES,
        },
        "expected_output": {"format": "translation_json"},
    }


def build_translation_qa_task(
    *,
    chapter_id: str,
    source_text: str,
    generated_translation: str,
    reference_translation: str,
    glossary_csv: str,
) -> dict[str, Any]:
    return {
        "custom_id": f"translation-qa-{chapter_id}",
        "agent": "translation-qa",
        "system": TRANSLATION_QA_SYSTEM,
        "input": {
            "chapter_id": chapter_id,
            "source_text": source_text,
            "generated_translation": generated_translation,
            "reference_translation": reference_translation,
            "glossary_csv": glossary_csv,
        },
        "expected_output": {"format": "translation_qa_json"},
    }


def write_translation_pilot_task(
    *,
    chapter_id: str,
    source_dir: Path,
    ru_dir: Path,
    glossary_csv: Path,
    out_jsonl: Path,
    context_start: int,
    context_end: int,
) -> None:
    task = build_translation_pilot_task(
        chapter_id=chapter_id,
        source_text=(source_dir / f"{chapter_id}.txt").read_text(encoding="utf-8"),
        glossary_csv=glossary_csv.read_text(encoding="utf-8"),
        context_chapters=[
            (f"{index:04d}", (ru_dir / f"{index:04d}.txt").read_text(encoding="utf-8"))
            for index in range(context_start, context_end + 1)
        ],
    )
    _write_single_jsonl(task, out_jsonl)


def write_translation_qa_task(
    *,
    chapter_id: str,
    source_dir: Path,
    ru_dir: Path,
    glossary_csv: Path,
    translation_results_jsonl: Path,
    out_jsonl: Path,
) -> None:
    task = build_translation_qa_task(
        chapter_id=chapter_id,
        source_text=(source_dir / f"{chapter_id}.txt").read_text(encoding="utf-8"),
        generated_translation=_read_generated_translation(translation_results_jsonl, chapter_id),
        reference_translation=(ru_dir / f"{chapter_id}.txt").read_text(encoding="utf-8"),
        glossary_csv=glossary_csv.read_text(encoding="utf-8"),
    )
    _write_single_jsonl(task, out_jsonl)


def _read_generated_translation(results_jsonl: Path, chapter_id: str) -> str:
    custom_id = f"translate-{chapter_id}"
    with results_jsonl.open(encoding="utf-8") as results_file:
        for line in results_file:
            if not line.strip():
                continue
            result = json.loads(line)
            if result.get("custom_id") != custom_id or result.get("status") != "completed":
                continue
            output = json.loads(str(result["output"]))
            return str(output["translation"])
    raise ValueError(f"No completed translation result found for {custom_id}")


def _write_single_jsonl(task: dict[str, Any], out_jsonl: Path) -> None:
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_jsonl.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")


TRANSLATION_QA_NO_REFERENCE_SYSTEM = """You are a senior Chinese-to-Russian literary translation QA editor.

Goal: compare a generated Russian translation against the Chinese source and the project glossary.
There is no reference translation for these chapters. Judge meaning, omissions, terminology, style, and chapter-level coherence against the source and glossary.
Score meaning_score, terminology_score, style_score, and omission_score each as an integer from 0 to 100.
Be strict and concrete. Do not rewrite the full chapter.

Return JSON only. Do not include markdown."""


def build_translation_qa_no_reference_task(
    *,
    chapter_id: str,
    source_text: str,
    generated_translation: str,
    glossary_csv: str,
) -> dict[str, Any]:
    return {
        "custom_id": f"translation-qa-{chapter_id}",
        "agent": "translation-qa",
        "system": TRANSLATION_QA_NO_REFERENCE_SYSTEM,
        "input": {
            "chapter_id": chapter_id,
            "source_text": source_text,
            "generated_translation": generated_translation,
            "glossary_csv": glossary_csv,
        },
        "expected_output": {"format": "translation_qa_json"},
    }


def write_translation_qa_no_reference_tasks(
    *,
    source_dir: Path,
    translation_results_jsonl: Path,
    glossary_csv: Path,
    out_jsonl: Path,
    glossary_subset_dir: Path | None = None,
) -> int:
    glossary_text = glossary_csv.read_text(encoding="utf-8")
    tasks = []
    with translation_results_jsonl.open(encoding="utf-8") as results_file:
        for line in results_file:
            if not line.strip():
                continue
            result = json.loads(line)
            if result.get("status") != "completed":
                continue
            try:
                output = json.loads(str(result.get("output", "")))
            except json.JSONDecodeError:
                continue
            if not isinstance(output, dict):
                continue
            chapter_id = output.get("chapter_id")
            translation = output.get("translation")
            if not isinstance(chapter_id, str) or not isinstance(translation, str):
                continue
            source_text = (source_dir / f"{chapter_id}.txt").read_text(encoding="utf-8")
            tasks.append(
                build_translation_qa_no_reference_task(
                    chapter_id=chapter_id,
                    source_text=source_text,
                    generated_translation=translation,
                    glossary_csv=read_chapter_glossary(
                        chapter_id, glossary_subset_dir=glossary_subset_dir, fallback_text=glossary_text
                    ),
                )
            )

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as jsonl_file:
        for task in tasks:
            jsonl_file.write(json.dumps(task, ensure_ascii=False) + "\n")
    return len(tasks)
