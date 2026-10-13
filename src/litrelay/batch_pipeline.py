from __future__ import annotations

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from litrelay.agent_backends import make_requester
from litrelay.agent_executor import run_agent_tasks
from litrelay.glossary_feedback import write_glossary_candidates
from litrelay.glossary_reconcile import (
    build_reconcile_batch_task,
    flag_glossary_terms,
    write_reconcile_overrides,
)
from litrelay.glossary_subset import write_glossary_subsets
from litrelay.glossary_versioning import merge_glossary_version
from litrelay.pilot_tasks import write_translation_qa_no_reference_tasks
from litrelay.post_translation_glossary import write_post_translation_glossary_tasks
from litrelay.prompt_profiles import PromptSettings, prepare_tasks
from litrelay.protected_terms import apply_protected_term_fixes
from litrelay.publisher import LocalExportPublisher, Publisher
from litrelay.qa_gate import evaluate_qa_results
from litrelay.revision import apply_revisions, write_revision_tasks
from litrelay.translation_batch import write_translation_batch_tasks
from litrelay.translation_results import export_translation_results, validate_translation_results

Requester = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class StageProfile:
    backend: str
    model: str
    concurrency: int = 1
    max_retries: int = 2
    timeout: int = 900


_DEFAULT_TRANSLATION_PROFILE = StageProfile(backend="codex", model="gpt-5.5", concurrency=1)
_DEFAULT_SUPPORT_PROFILE = StageProfile(backend="codex", model="gpt-5.5", concurrency=5)


@dataclass(frozen=True)
class BatchConfig:
    slug: str
    start: int
    end: int
    source_dir: Path
    context_dir: Path
    published_ru_dir: Path
    glossary_csv: Path
    batch_dir: Path
    translation_profile: StageProfile = _DEFAULT_TRANSLATION_PROFILE
    support_profile: StageProfile = _DEFAULT_SUPPORT_PROFILE
    context_window: int = 5
    glossary_conf_threshold: float = 0.90
    revise_attempts: int = 0
    chain: bool = False
    incremental_glossary: bool = True
    qa_thresholds: dict[str, float] | None = None
    protected_csv: Path | None = None
    style_guide: Path | None = None
    recap: Path | None = None
    text_validator: Callable[[str, str], None] | None = None
    prompt_settings: PromptSettings | None = None
    requester: Requester | None = None
    publisher: Publisher | None = None


@dataclass(frozen=True)
class BatchReport:
    translated: int
    qa_passed: int
    qa_failed: int
    glossary_candidates: int
    reconcile_flags: int
    published: int
    next_glossary_csv: Path


def _resolve_requester(config: BatchConfig, profile: StageProfile) -> Requester | None:
    if config.requester is not None:
        return config.requester
    return make_requester(profile.backend, profile.model, profile.timeout)


def _run_stage(config: BatchConfig, tasks: Path, results: Path, profile: StageProfile) -> None:
    if config.prompt_settings is not None:
        tasks = prepare_tasks(tasks, config.prompt_settings)
    real_cli = config.requester is None and profile.backend != "openai"
    run_agent_tasks(
        tasks,
        results,
        model=profile.model,
        requester=_resolve_requester(config, profile),
        concurrency=profile.concurrency,
        max_retries=profile.max_retries,
        task_timeout=profile.timeout if real_cli else None,
    )


def _guard_qa(config: BatchConfig, translations: Path, qa: Path) -> None:
    if config.text_validator is None:
        return
    outputs = {
        json.loads(row["output"])["chapter_id"]: json.loads(row["output"])["translation"]
        for row in (json.loads(x) for x in translations.read_text().splitlines())
        if row.get("status") == "completed"
    }
    rows = [json.loads(x) for x in qa.read_text().splitlines() if x.strip()]
    for row in rows:
        if row.get("status") != "completed":
            continue
        data = json.loads(row["output"])
        try:
            config.text_validator(data["chapter_id"], outputs[data["chapter_id"]])
        except ValueError as error:
            data.setdefault("issues", []).append(str(error))
            data["deterministic_errors"] = [str(error)]
            data["terminology_score"] = 0
            row["output"] = json.dumps(data, ensure_ascii=False)
    qa.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


def _revise_failed(
    config: BatchConfig,
    subset_dir: Path,
    results_path: Path,
    qa_results_path: Path,
    failed_chapters: list[str],
) -> list[str]:
    bd = config.batch_dir
    remaining = list(failed_chapters)
    for attempt in range(1, config.revise_attempts + 1):
        if not remaining:
            break
        rev_tasks = bd / f"revise-{attempt}.tasks.jsonl"
        rev_results = bd / f"revise-{attempt}.results.jsonl"
        count = write_revision_tasks(
            source_dir=config.source_dir,
            translation_results_jsonl=results_path,
            qa_results_jsonl=qa_results_path,
            failed_chapter_ids=remaining,
            glossary_csv=config.glossary_csv,
            out_jsonl=rev_tasks,
            glossary_subset_dir=subset_dir,
        )
        if count == 0:
            break
        _run_stage(config, rev_tasks, rev_results, config.translation_profile)

        rev_qa_tasks = bd / f"revise-qa-{attempt}.tasks.jsonl"
        rev_qa_results = bd / f"revise-qa-{attempt}.results.jsonl"
        write_translation_qa_no_reference_tasks(
            source_dir=config.source_dir,
            translation_results_jsonl=rev_results,
            glossary_csv=config.glossary_csv,
            out_jsonl=rev_qa_tasks,
            glossary_subset_dir=subset_dir,
        )
        _run_stage(config, rev_qa_tasks, rev_qa_results, config.support_profile)
        _guard_qa(config, rev_results, rev_qa_results)
        apply_revisions(
            translation_results_jsonl=results_path,
            qa_results_jsonl=qa_results_path,
            revised_results_jsonl=rev_results,
            revised_qa_jsonl=rev_qa_results,
            thresholds=config.qa_thresholds,
        )
        report = evaluate_qa_results(
            qa_results_path,
            thresholds=config.qa_thresholds,
            expected_chapter_ids={f"{n:04d}" for n in range(config.start, config.end + 1)},
        )
        remaining = [d.chapter_id for d in report.decisions if d.verdict != "pass"]
    return remaining


def run_batch(config: BatchConfig) -> BatchReport:
    if not 1 <= config.start <= config.end:
        raise ValueError("Invalid chapter range")
    bd = config.batch_dir
    bd.mkdir(parents=True, exist_ok=True)

    subset_dir = bd / "glossary-subsets"
    write_glossary_subsets(
        config.glossary_csv,
        config.source_dir,
        subset_dir,
        start=config.start,
        end=config.end,
    )

    tasks = bd / "translation.tasks.jsonl"
    results = bd / "translation.results.jsonl"
    if config.chain:
        _translate_chained(config, subset_dir=subset_dir, results_path=results)
        write_translation_batch_tasks(
            source_dir=config.source_dir,
            context_dir=config.context_dir,
            glossary_csv=config.glossary_csv,
            out_jsonl=tasks,
            start=config.start,
            end=config.end,
            context_window=config.context_window,
            style_guide=config.style_guide,
            recap=config.recap,
            glossary_subset_dir=subset_dir,
        )
    else:
        write_translation_batch_tasks(
            source_dir=config.source_dir,
            context_dir=config.context_dir,
            glossary_csv=config.glossary_csv,
            out_jsonl=tasks,
            start=config.start,
            end=config.end,
            context_window=config.context_window,
            style_guide=config.style_guide,
            recap=config.recap,
            glossary_subset_dir=subset_dir,
        )
        _run_stage(config, tasks, results, config.translation_profile)

    validation = validate_translation_results(tasks, results)
    if not validation.ok or validation.completed != config.end - config.start + 1:
        raise RuntimeError(f"translation stage failed: {validation}")

    qa_tasks = bd / "qa.tasks.jsonl"
    qa_results = bd / "qa.results.jsonl"
    write_translation_qa_no_reference_tasks(
        source_dir=config.source_dir,
        translation_results_jsonl=results,
        glossary_csv=config.glossary_csv,
        out_jsonl=qa_tasks,
        glossary_subset_dir=subset_dir,
    )
    _run_stage(config, qa_tasks, qa_results, config.support_profile)
    _guard_qa(config, results, qa_results)
    qa_report = evaluate_qa_results(
        qa_results,
        thresholds=config.qa_thresholds,
        expected_chapter_ids={f"{n:04d}" for n in range(config.start, config.end + 1)},
    )
    failed_chapters = [decision.chapter_id for decision in qa_report.decisions if decision.verdict != "pass"]
    if config.revise_attempts > 0 and failed_chapters:
        failed_chapters = _revise_failed(config, subset_dir, results, qa_results, failed_chapters)
        qa_report = evaluate_qa_results(
            qa_results,
            thresholds=config.qa_thresholds,
            expected_chapter_ids={f"{n:04d}" for n in range(config.start, config.end + 1)},
        )
    failed_chapters = [d.chapter_id for d in qa_report.decisions if d.verdict != "pass"]
    needs_revision = bd / "needs-revision.txt"
    needs_revision.write_text("".join(f"{chapter}\n" for chapter in failed_chapters), encoding="utf-8")

    if failed_chapters:
        next_glossary = bd / "glossary-next.curated.csv"
        next_glossary.write_text(config.glossary_csv.read_text(encoding="utf-8"), encoding="utf-8")
        return BatchReport(validation.completed, qa_report.passed, qa_report.failed, 0, 0, 0, next_glossary)

    post_results = bd / "post-glossary.results.jsonl"
    if not (config.chain and config.incremental_glossary):
        post_tasks = bd / "post-glossary.tasks.jsonl"
        write_post_translation_glossary_tasks(
            source_dir=config.source_dir,
            translation_results_jsonl=results,
            glossary_csv=config.glossary_csv,
            out_jsonl=post_tasks,
            glossary_subset_dir=subset_dir,
        )
        _run_stage(config, post_tasks, post_results, config.support_profile)
    candidates_csv = bd / "glossary-candidates.csv"
    feedback = write_glossary_candidates(post_results, candidates_csv)

    flags = flag_glossary_terms(config.glossary_csv, config.published_ru_dir)
    reconcile_proposals = bd / "glossary-reconcile-proposals.csv"
    if flags:
        reconcile_tasks = bd / "glossary-reconcile.tasks.jsonl"
        reconcile_results = bd / "glossary-reconcile.results.jsonl"
        _write_jsonl([build_reconcile_batch_task(flags, config.published_ru_dir)], reconcile_tasks)
        _run_stage(config, reconcile_tasks, reconcile_results, config.support_profile)
        write_reconcile_overrides(reconcile_results, reconcile_proposals)

    review_csv = bd / "glossary-review-needed.csv"
    merged_csv = bd / "glossary-merged.csv"
    merge_glossary_version(
        candidates_csv,
        merged_csv,
        base_csv=config.glossary_csv,
        review_csv=review_csv,
        version=f"{config.slug}-{config.start}-{config.end}",
        min_confidence=config.glossary_conf_threshold,
    )
    next_glossary = bd / "glossary-next.curated.csv"
    next_glossary.write_text(merged_csv.read_text(encoding="utf-8"), encoding="utf-8")

    accepted_dir = bd / "accepted"
    export_translation_results(results, accepted_dir)
    if config.protected_csv is not None and config.protected_csv.exists():
        guarded_dir = bd / "guarded"
        apply_protected_term_fixes(accepted_dir, config.protected_csv, guarded_dir)
        publish_source = guarded_dir
    else:
        publish_source = accepted_dir

    publisher = config.publisher or LocalExportPublisher(out_dir=bd / "published")
    publish_summary = publisher.publish(publish_source, {"slug": config.slug})

    return BatchReport(
        translated=validation.completed,
        qa_passed=qa_report.passed,
        qa_failed=qa_report.failed,
        glossary_candidates=feedback.candidates_written,
        reconcile_flags=len(flags),
        published=publish_summary.published,
        next_glossary_csv=next_glossary,
    )


_COINED_COLUMNS = ["source", "target_ru", "type", "note", "confidence"]


def _translate_chained(config: BatchConfig, *, subset_dir: Path, results_path: Path) -> None:
    accum = config.batch_dir / "context-accum"
    accum.mkdir(parents=True, exist_ok=True)
    for path in config.context_dir.glob("*.txt"):
        if path.stem.isdigit() and int(path.stem) < config.start:
            (accum / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    incremental = config.incremental_glossary
    coined: dict[str, dict[str, str]] = {}
    post_results_path = config.batch_dir / "post-glossary.results.jsonl"
    post_file = post_results_path.open("w", encoding="utf-8") if incremental else None
    try:
        with results_path.open("w", encoding="utf-8") as results_file:
            for index in range(config.start, config.end + 1):
                chapter_id = f"{index:04d}"
                if incremental and coined:
                    _inject_coined_terms(subset_dir / f"{chapter_id}.csv", coined.values())
                task_path = config.batch_dir / f"chain-{chapter_id}.tasks.jsonl"
                result_path = config.batch_dir / f"chain-{chapter_id}.results.jsonl"
                write_translation_batch_tasks(
                    source_dir=config.source_dir,
                    context_dir=accum,
                    glossary_csv=config.glossary_csv,
                    out_jsonl=task_path,
                    start=index,
                    end=index,
                    context_window=config.context_window,
                    style_guide=config.style_guide,
                    recap=config.recap,
                    glossary_subset_dir=subset_dir,
                )
                _run_stage(config, task_path, result_path, config.translation_profile)
                for line in result_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    results_file.write(line + "\n")
                    results_file.flush()
                    result = json.loads(line)
                    if result.get("status") != "completed":
                        continue
                    try:
                        output = json.loads(str(result.get("output", "")))
                    except json.JSONDecodeError:
                        continue
                    translation = output.get("translation")
                    if isinstance(translation, str) and translation.strip():
                        (accum / f"{chapter_id}.txt").write_text(translation, encoding="utf-8")
                if incremental:
                    _accumulate_coined_terms(
                        config,
                        chapter_id=chapter_id,
                        translation_results_path=result_path,
                        subset_dir=subset_dir,
                        coined=coined,
                        post_file=post_file,
                    )
    finally:
        if post_file is not None:
            post_file.close()


def _inject_coined_terms(subset_path: Path, coined_rows) -> None:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    if subset_path.exists():
        with subset_path.open(encoding="utf-8", newline="") as subset_file:
            for row in csv.DictReader(subset_file):
                rows.append({column: (row.get(column) or "").strip() for column in _COINED_COLUMNS})
                seen.add((row.get("source") or "").strip())
    added = 0
    for row in coined_rows:
        source = row["source"]
        if source in seen:
            continue
        rows.append({column: row.get(column, "") for column in _COINED_COLUMNS})
        seen.add(source)
        added += 1
    if added == 0:
        return
    subset_path.parent.mkdir(parents=True, exist_ok=True)
    with subset_path.open("w", encoding="utf-8", newline="") as subset_file:
        writer = csv.DictWriter(subset_file, fieldnames=_COINED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _accumulate_coined_terms(
    config: BatchConfig,
    *,
    chapter_id: str,
    translation_results_path: Path,
    subset_dir: Path,
    coined: dict[str, dict[str, str]],
    post_file,
) -> None:
    bd = config.batch_dir
    pg_tasks = bd / f"chain-postgloss-{chapter_id}.tasks.jsonl"
    pg_results = bd / f"chain-postgloss-{chapter_id}.results.jsonl"
    count = write_post_translation_glossary_tasks(
        source_dir=config.source_dir,
        translation_results_jsonl=translation_results_path,
        glossary_csv=config.glossary_csv,
        out_jsonl=pg_tasks,
        glossary_subset_dir=subset_dir,
    )
    if count == 0:
        return
    _run_stage(config, pg_tasks, pg_results, config.support_profile)
    if post_file is not None:
        for line in pg_results.read_text(encoding="utf-8").splitlines():
            if line.strip():
                post_file.write(line + "\n")
        post_file.flush()
    cand_csv = bd / f"chain-postgloss-{chapter_id}.candidates.csv"
    write_glossary_candidates(pg_results, cand_csv)
    with cand_csv.open(encoding="utf-8", newline="") as cand_file:
        for row in csv.DictReader(cand_file):
            source = (row.get("source") or "").strip()
            target = (row.get("target_ru") or "").strip()
            if not source or not target or source in coined:
                continue
            coined[source] = {
                "source": source,
                "target_ru": target,
                "type": (row.get("type") or "").strip(),
                "note": (row.get("note") or "").strip(),
                "confidence": (row.get("confidence") or "").strip(),
            }


def _write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as jsonl_file:
        for row in rows:
            jsonl_file.write(json.dumps(row, ensure_ascii=False) + "\n")
