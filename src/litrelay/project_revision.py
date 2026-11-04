from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path

from litrelay.batch_pipeline import _emit_qa, _guard_qa, _prepare_glossary_review, _revise_failed, _run_stage
from litrelay.book_inputs import validate_chapter
from litrelay.glossary_subset import write_glossary_subsets
from litrelay.pilot_tasks import write_translation_qa_no_reference_tasks
from litrelay.project_storage import digest, project_lock, write_json
from litrelay.project_workflow import (
    Requester,
    _batch_config,
    _inputs,
    _require_backends,
    export_project,
    project_status,
)
from litrelay.qa_gate import evaluate_qa_results
from litrelay.telemetry import RunTrace
from litrelay.translation_batch import write_translation_batch_tasks
from litrelay.translation_results import export_translation_results, validate_translation_results


def revise_project_chapter(
    project: Path,
    *,
    chapter: int,
    feedback: str = "",
    from_scratch: bool = False,
    requester: Requester | None = None,
    debug: bool = False,
    log_file: Path | None = None,
    reasoning_effort: str | None = None,
) -> dict:
    if not (project / "project.json").is_file():
        raise ValueError("Unknown project; use litrelay init first")
    if chapter < 1:
        raise ValueError("Chapter must be positive")
    if reasoning_effort not in {None, "low", "medium", "high", "xhigh", "max"}:
        raise ValueError("Invalid reasoning effort")
    feedback = feedback.strip()
    if not feedback and not from_scratch:
        raise ValueError("Provide --feedback, --feedback-file or --from-scratch")
    trace = RunTrace(project, log_file=log_file) if debug or log_file else None
    try:
        with project_lock(project):
            result = _revise_chapter(project, chapter, feedback, from_scratch, requester, trace, reasoning_effort)
    except BaseException as error:
        if trace:
            trace.close(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", error=error)
        raise
    if trace:
        result["telemetry"] = trace.close(status="complete" if result["complete"] else "partial")
    return result


def _revise_chapter(
    project: Path,
    chapter: int,
    feedback: str,
    from_scratch: bool,
    requester: Requester | None,
    trace: RunTrace | None,
    reasoning_effort: str | None,
) -> dict:
    config, source, _, fp = _inputs(project)
    status = project_status(project)
    if not status["bootstrap_ready"] or str(chapter) not in status["chapters"]:
        raise ValueError("Chapter needs a current accepted translation; run the project first")
    if requester is None:
        _require_backends(config)
    cid = f"{chapter:04d}"
    accepted = project / "work/accepted" / f"{cid}.txt"
    previous = accepted.read_text(encoding="utf-8")
    progress = project / "work/progress.json"
    state = json.loads(progress.read_text(encoding="utf-8"))
    batch = project / "work/revisions" / cid / uuid.uuid4().hex
    batch.mkdir(parents=True)
    (batch / "previous.txt").write_text(previous, encoding="utf-8")
    write_json(batch / "progress.before.json", state)
    write_json(
        batch / "request.json",
        {
            "chapter": chapter,
            "feedback": feedback,
            "from_scratch": from_scratch,
            "fingerprint": fp,
            "reasoning_effort": reasoning_effort,
        },
    )
    glossary = batch / "glossary.csv"
    glossary.write_text((project / "work/glossary/active.csv").read_text(encoding="utf-8"), encoding="utf-8")
    cfg = _batch_config(
        project, config, batch=batch, start=chapter, end=chapter, glossary=glossary, requester=requester, trace=trace
    )
    cfg = replace(cfg, prompt_settings=replace(cfg.prompt_settings, reader_feedback=feedback))
    if reasoning_effort is not None:
        cfg = replace(cfg, translation_profile=replace(cfg.translation_profile, reasoning_effort=reasoning_effort))
    subsets = batch / "glossary-subsets"
    write_glossary_subsets(glossary, cfg.source_dir, subsets, start=chapter, end=chapter)
    tasks = batch / "translation.tasks.jsonl"
    results = batch / "translation.results.jsonl"
    write_translation_batch_tasks(
        source_dir=cfg.source_dir,
        context_dir=cfg.context_dir,
        glossary_csv=glossary,
        out_jsonl=tasks,
        start=chapter,
        end=chapter,
        context_window=config["context_window"],
        glossary_subset_dir=subsets,
    )
    if not from_scratch:
        task = json.loads(tasks.read_text(encoding="utf-8"))
        task["input"]["previous_translation"] = previous
        tasks.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")
    _run_stage(cfg, tasks, results, cfg.translation_profile)
    validation = validate_translation_results(tasks, results)
    if not validation.ok or validation.completed != 1:
        raise RuntimeError(f"Revision translation failed; previous chapter kept. Inspect {batch}")
    qa_tasks = batch / "qa.tasks.jsonl"
    qa_results = batch / "qa.results.jsonl"
    write_translation_qa_no_reference_tasks(
        source_dir=cfg.source_dir,
        translation_results_jsonl=results,
        glossary_csv=glossary,
        out_jsonl=qa_tasks,
        glossary_subset_dir=subsets,
    )
    _prepare_glossary_review(cfg, results, qa_tasks)
    _run_stage(cfg, qa_tasks, qa_results, cfg.support_profile)
    _guard_qa(cfg, results, qa_results)
    qa = evaluate_qa_results(qa_results, thresholds=cfg.qa_thresholds, expected_chapter_ids={cid})
    _emit_qa(cfg, qa, stage="qa")
    if not qa.ok and cfg.revise_attempts:
        _revise_failed(cfg, subsets, results, qa_results, [cid])
        qa = evaluate_qa_results(qa_results, thresholds=cfg.qa_thresholds, expected_chapter_ids={cid})
    if not qa.ok:
        raise RuntimeError(f"QA blocked revision; previous chapter kept. Inspect {batch}")
    export_translation_results(results, batch / "candidate")
    candidate = (batch / "candidate" / f"{cid}.txt").read_text(encoding="utf-8")
    validate_chapter(chapter, candidate, min_chars=config["min_chars"], target_language=config["target_language"])
    if _inputs(project)[3] != fp or accepted.read_text(encoding="utf-8") != previous:
        raise RuntimeError(f"Project changed during revision; candidate not accepted. Inspect {batch}")
    state["chapters"][str(chapter)] = {
        "origin": "generated",
        "fingerprint": fp,
        "source_sha256": digest(source[chapter]),
        "target_sha256": digest(candidate),
        "qa_scores": {metric: getattr(qa.decisions[0], metric) for metric in config["qa_thresholds"]},
        "batch": str(batch.relative_to(project)),
    }
    pending = accepted.with_suffix(".txt.tmp")
    try:
        pending.write_text(candidate, encoding="utf-8")
        pending.replace(accepted)
        write_json(progress, state)
    except BaseException:
        pending.write_text(previous, encoding="utf-8")
        pending.replace(accepted)
        write_json(progress, json.loads((batch / "progress.before.json").read_text(encoding="utf-8")))
        raise
    if trace:
        trace.emit({"event": "chapter_accepted", "chapter": chapter, "status": "revised"})
    result = project_status(project)
    if result["complete"]:
        result = export_project(project)
    return {
        **result,
        "revised_chapter": chapter,
        "revision_dir": str(batch),
        "previous_version": str(batch / "previous.txt"),
    }
