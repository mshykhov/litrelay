from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from litrelay.glossary_subset import read_chapter_glossary
from litrelay.pilot_tasks import TRANSLATION_AGENT_SYSTEM, TRANSLATION_QUALITY_GATES
from litrelay.qa_gate import scores_pass_qa

REVISION_SYSTEM = (
    TRANSLATION_AGENT_SYSTEM
    + "\n\nREVISION MODE: you are given your previous Russian translation and concrete QA issues. "
    "Produce an improved FULL Russian translation that fixes every listed issue (meaning, terminology, "
    "style, omissions) while preserving everything already correct. Do not shorten or drop content. "
    "Return JSON only."
)

_QA_KEYS = ("meaning_score", "terminology_score", "style_score", "omission_score")


def build_revision_task(
    *,
    chapter_id: str,
    source_text: str,
    previous_translation: str,
    qa: dict[str, Any],
    glossary_csv: str,
) -> dict[str, Any]:
    return {
        "custom_id": f"translate-{chapter_id}",
        "agent": "translation-agent",
        "system": REVISION_SYSTEM,
        "input": {
            "chapter_id": chapter_id,
            "source_text": source_text,
            "glossary_csv": glossary_csv,
            "previous_translation": previous_translation,
            "qa_issues": qa.get("issues", []),
            "qa_missing_or_changed_facts": qa.get("missing_or_changed_facts", []),
            "qa_recommended_action": qa.get("recommended_action", ""),
            "qa_scores": {key: qa.get(key) for key in _QA_KEYS},
            "quality_gates": TRANSLATION_QUALITY_GATES,
        },
        "expected_output": {"format": "translation_json"},
    }


def write_revision_tasks(
    *,
    source_dir: Path,
    translation_results_jsonl: Path,
    qa_results_jsonl: Path,
    failed_chapter_ids: list[str],
    glossary_csv: Path,
    out_jsonl: Path,
    glossary_subset_dir: Path | None = None,
) -> int:
    translations = _load_outputs(translation_results_jsonl)
    qas = _load_outputs(qa_results_jsonl)
    fallback_text = glossary_csv.read_text(encoding="utf-8")
    tasks = []
    for chapter_id in failed_chapter_ids:
        if chapter_id not in translations or chapter_id not in qas:
            continue
        source_text = (source_dir / f"{chapter_id}.txt").read_text(encoding="utf-8")
        tasks.append(
            build_revision_task(
                chapter_id=chapter_id,
                source_text=source_text,
                previous_translation=str(translations[chapter_id].get("translation", "")),
                qa=qas[chapter_id],
                glossary_csv=read_chapter_glossary(
                    chapter_id, glossary_subset_dir=glossary_subset_dir, fallback_text=fallback_text
                ),
            )
        )
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with out_jsonl.open("w", encoding="utf-8") as jsonl_file:
        for task in tasks:
            jsonl_file.write(json.dumps(task, ensure_ascii=False) + "\n")
    return len(tasks)


def apply_revisions(
    *,
    translation_results_jsonl: Path,
    qa_results_jsonl: Path,
    revised_results_jsonl: Path,
    revised_qa_jsonl: Path,
    thresholds: dict[str, float] | None = None,
) -> dict[str, bool]:
    original_qa = _load_outputs(qa_results_jsonl)
    revised_translations = _load_outputs(revised_results_jsonl)
    revised_qa = _load_outputs(revised_qa_jsonl)

    keep: dict[str, bool] = {}
    for chapter_id in revised_translations:
        if chapter_id not in revised_qa:
            keep[chapter_id] = False
            continue
        original_avg = _avg(original_qa[chapter_id]) if chapter_id in original_qa else -1.0
        newly_passing = scores_pass_qa(revised_qa[chapter_id], thresholds) and not scores_pass_qa(
            original_qa.get(chapter_id, {}), thresholds
        )
        keep[chapter_id] = newly_passing or _avg(revised_qa[chapter_id]) >= original_avg

    accepted = {chapter_id for chapter_id, use in keep.items() if use}
    _replace_lines(translation_results_jsonl, revised_results_jsonl, accepted)
    _replace_lines(qa_results_jsonl, revised_qa_jsonl, accepted)
    return keep


def _avg(qa: dict[str, Any]) -> float:
    values = [float(qa.get(key, 0) or 0) for key in _QA_KEYS]
    return sum(values) / len(values)


def _load_outputs(path: Path) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("status") not in (None, "completed"):
            continue
        output = _parse_output(record)
        if output is not None and isinstance(output.get("chapter_id"), str):
            outputs[output["chapter_id"]] = output
    return outputs


def _parse_output(record: dict[str, Any]) -> dict[str, Any] | None:
    try:
        output = json.loads(str(record.get("output", "")))
    except json.JSONDecodeError:
        return None
    return output if isinstance(output, dict) else None


def _replace_lines(target: Path, source: Path, accepted: set[str]) -> None:
    replacements = _index_by_chapter(source)
    new_lines = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        chapter_id = _chapter_of(line)
        if chapter_id in accepted and chapter_id in replacements:
            new_lines.append(replacements[chapter_id])
        else:
            new_lines.append(line)
    target.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _index_by_chapter(path: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        chapter_id = _chapter_of(line)
        if chapter_id is not None:
            index[chapter_id] = line
    return index


def _chapter_of(line: str) -> str | None:
    output = _parse_output(json.loads(line))
    if output is None:
        return None
    chapter_id = output.get("chapter_id")
    return chapter_id if isinstance(chapter_id, str) else None
