from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import TYPE_CHECKING

from litrelay.agent_results import merge_glossary_results, validate_agent_results
from litrelay.glossary_versioning import merge_glossary_version
from litrelay.llm_agent_inputs import build_glossary_task, write_jsonl

if TYPE_CHECKING:
    from litrelay.batch_pipeline import BatchConfig


def prepare_preflight_glossary(config: BatchConfig) -> Path:
    from litrelay.batch_pipeline import _run_stage

    batch = config.batch_dir
    staged = batch / "glossary-preflight.curated.csv"
    staged.write_bytes(config.glossary_csv.read_bytes())
    canonical = staged.read_text(encoding="utf-8")
    with staged.open(encoding="utf-8", newline="") as handle:
        existing = {(row.get("source") or "").strip() for row in csv.DictReader(handle)}
    source = "\n\n".join(
        (config.source_dir / f"{n:04d}.txt").read_text(encoding="utf-8") for n in range(config.start, config.end + 1)
    )
    profile = config.support_profile
    prefix = batch / "glossary-preflight"
    task_path = prefix.with_name(prefix.name + ".tasks.jsonl")
    result_path = prefix.with_name(prefix.name + ".results.jsonl")
    prompt = (
        "Before translation, extract only important new names, places and recurring concepts present in the "
        "supplied source chapters and absent from the canonical glossary. Preserve existing names and choices. "
        "Use context, avoid invented lore, and assign numeric confidence between 0 and 1. "
        "Return CSV source,target_ru,type,note,confidence. Use configured target language; no commas in fields.\n\n"
        f"CANONICAL GLOSSARY:\n{canonical}\nSOURCE CHAPTERS:\n{source}"
    )
    write_jsonl([build_glossary_task(chapter_id=f"{config.start:04d}", prompt=prompt)], task_path)
    _run_stage(config, task_path, result_path, profile)
    if not validate_agent_results(task_path, result_path, kind="glossary").ok:
        raise RuntimeError(f"Glossary preflight extraction failed; inspect {result_path}")
    draft = batch / "glossary-preflight.proposed.csv"
    merge_glossary_results(result_path, draft)
    proposed = _supported_rows(draft, source, existing)
    if not proposed:
        return staged
    candidate_fields = ["chapter_id", "source", "target_ru", "type", "note", "confidence"]
    with draft.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(proposed)
    review_task = batch / "glossary-preflight-review.tasks.jsonl"
    review_result = batch / "glossary-preflight-review.results.jsonl"
    review_prompt = (
        "Review the proposed NEW glossary terms against the source chapters before translation. "
        "Correct unsupported or inaccurate names and meanings, remove unsupported terms, preserve existing "
        "canonical targets, and do not introduce terms absent from the proposal. "
        "Return CSV source,target_ru,type,note,confidence with numeric confidence between 0 and 1.\n\n"
        f"CANONICAL GLOSSARY:\n{canonical}\nPROPOSED NEW TERMS:\n{draft.read_text(encoding='utf-8')}\n"
        f"SOURCE CHAPTERS:\n{source}"
    )
    write_jsonl([build_glossary_task(chapter_id=f"{config.start:04d}", prompt=review_prompt)], review_task)
    _run_stage(config, review_task, review_result, profile)
    if not validate_agent_results(review_task, review_result, kind="glossary").ok:
        raise RuntimeError(f"Glossary preflight review failed; inspect {review_result}")
    reviewed = batch / "glossary-preflight.reviewed.csv"
    merge_glossary_results(review_result, reviewed)
    proposed_sources = {row["source"] for row in proposed}
    rows = [row for row in _supported_rows(reviewed, source, existing) if row["source"] in proposed_sources]
    with reviewed.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(rows)
    merge_glossary_version(
        reviewed,
        staged,
        base_csv=staged,
        review_csv=batch / "glossary-preflight-review-needed.csv",
        version="preflight",
        min_confidence=config.glossary_conf_threshold,
    )
    return staged


def _supported_rows(path: Path, source: str, existing: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result = []
    for row in rows:
        term = (row.get("source") or "").strip()
        target = (row.get("target_ru") or "").strip()
        try:
            confidence = float(row.get("confidence") or "")
        except ValueError:
            continue
        if (
            term
            and target
            and term not in existing
            and term in source
            and math.isfinite(confidence)
            and 0 <= confidence <= 1
        ):
            result.append(row)
    return result
