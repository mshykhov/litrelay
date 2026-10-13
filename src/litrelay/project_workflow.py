from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from litrelay.agent_results import merge_glossary_results, validate_agent_results
from litrelay.batch_pipeline import BatchConfig, StageProfile, _run_stage, run_batch
from litrelay.book_export import export_book
from litrelay.book_inputs import read_chapters, validate_chapter
from litrelay.glossary_versioning import merge_glossary_version, validate_glossary
from litrelay.llm_agent_inputs import build_alignment_task, build_glossary_task, write_jsonl
from litrelay.project_config import normalize_glossary, read_config
from litrelay.project_storage import digest, project_lock, write_json
from litrelay.prompt_profiles import PromptSettings
from litrelay.prompts import build_glossary_prompt

Requester = Callable[[dict], dict]


def _inputs(project: Path) -> tuple[dict, dict[int, str], dict[int, str], str]:
    config = read_config(project)
    source = read_chapters(project / "input/source", min_chars=config["min_chars"])
    if set(source) != set(range(1, max(source) + 1)):
        raise ValueError("Missing source chapters")
    existing = (
        read_chapters(project / "input/translation", min_chars=config["min_chars"])
        if any((project / "input/translation").glob("*.txt"))
        else {}
    )
    if existing.keys() - source.keys():
        raise ValueError("Translation chapter absent from source")
    seed = project / "input/glossary.csv"
    fingerprint = digest(
        json.dumps(
            {
                "config": config,
                "source": {n: digest(t) for n, t in source.items()},
                "translation": {n: digest(t) for n, t in existing.items()},
                "seed": seed.read_text(encoding="utf-8") if seed.exists() else "",
            },
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    return config, source, existing, fingerprint


def project_status(project: Path) -> dict:
    config, source, existing, fp = _inputs(project)
    state_path = project / "work/progress.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"chapters": {}}
    accepted = {}
    for n in source:
        row = state["chapters"].get(str(n))
        p = project / "work/accepted" / f"{n:04d}.txt"
        if (
            row
            and row["fingerprint"] == fp
            and row["source_sha256"] == digest(source[n])
            and p.exists()
            and row["target_sha256"] == digest(p.read_text(encoding="utf-8"))
        ):
            accepted[str(n)] = row
    bootstrap_ready = state.get("glossary_fingerprint") == fp and (project / "work/glossary/active.csv").exists()
    return {
        "complete": len(accepted) == len(source) and bootstrap_ready,
        "bootstrap_ready": bootstrap_ready,
        "total": len(source),
        "accepted": len(accepted),
        "generated": sum(x["origin"] == "generated" for x in accepted.values()),
        "existing": len(existing),
        "missing": [n for n in source if str(n) not in accepted],
        "fingerprint": fp,
        "chapters": accepted,
    }


def _batch_config(
    project: Path, config: dict, *, batch: Path, start: int, end: int, glossary: Path, requester: Requester | None
) -> BatchConfig:
    def profile(name: str) -> StageProfile:
        p = config[name]
        return StageProfile(p["backend"], p["model"], p["concurrency"])

    return BatchConfig(
        slug=project.name,
        start=start,
        end=end,
        source_dir=project / "input/source",
        context_dir=project / "work/accepted",
        published_ru_dir=project / "work/accepted",
        glossary_csv=glossary,
        batch_dir=batch,
        translation_profile=profile("translation"),
        support_profile=profile("support"),
        context_window=config["context_window"],
        revise_attempts=config["revise_attempts"],
        chain=config["chain"],
        qa_thresholds=config["qa_thresholds"],
        prompt_settings=PromptSettings(
            config["source_language"], config["target_language"], config["style"], config["prompts"]
        ),
        text_validator=lambda cid, text: validate_chapter(
            int(cid), text, min_chars=config["min_chars"], target_language=config["target_language"]
        ),
        requester=requester,
    )


def _bootstrap(
    project: Path, config: dict, source: dict[int, str], existing: dict[int, str], fp: str, requester: Requester | None
) -> Path:
    batch = project / "work/bootstrap" / fp[:12]
    batch.mkdir(parents=True, exist_ok=True)
    glossary = batch / "glossary.curated.csv"
    ready = batch / "ready.json"
    if ready.exists() and glossary.exists():
        data = json.loads(ready.read_text())
        if data["fingerprint"] == fp and data["glossary_sha256"] == digest(glossary.read_text()):
            return glossary
    seed = project / "input/glossary.csv"
    glossary.write_text(
        seed.read_text() if seed.exists() else "source,target_ru,type,note,confidence\n", encoding="utf-8"
    )
    cfg = _batch_config(project, config, batch=batch, start=1, end=max(source), glossary=glossary, requester=requester)
    numbers = sorted(existing)
    count = min(config["glossary_samples"], len(numbers))
    chosen = [numbers[round(i * (len(numbers) - 1) / max(1, count - 1))] for i in range(count)]
    if chosen:
        tasks = batch / "alignment.tasks.jsonl"
        results = batch / "alignment.results.jsonl"
        write_jsonl(
            [
                build_alignment_task(
                    chapter_id=f"{n:04d}",
                    source_title=source[n].splitlines()[0],
                    ru_title=existing[n].splitlines()[0],
                    source_text=source[n],
                    ru_text=existing[n],
                )
                for n in chosen
            ],
            tasks,
        )
        _run_stage(cfg, tasks, results, cfg.support_profile)
        validation = validate_agent_results(tasks, results, kind="alignment")
        if not validation.ok:
            raise RuntimeError(f"Existing translation alignment failed; inspect {results}")
        if not seed.exists():
            tasks = batch / "glossary.tasks.jsonl"
            results = batch / "glossary.results.jsonl"
            write_jsonl(
                [
                    build_glossary_task(
                        chapter_id=f"{n:04d}",
                        prompt=build_glossary_prompt(
                            chapter_id=f"{n:04d}",
                            source_text=source[n],
                            ru_text=existing[n],
                            source_lang=config["source_language"],
                            target_lang=config["target_language"],
                        ),
                    )
                    for n in chosen
                ],
                tasks,
            )
            _run_stage(cfg, tasks, results, cfg.support_profile)
            if not validate_agent_results(tasks, results, kind="glossary").ok:
                raise RuntimeError(f"Glossary extraction failed; inspect {results}")
            candidates = batch / "candidates.csv"
            merge_glossary_results(results, candidates)
            merge_glossary_version(
                candidates, glossary, review_csv=batch / "review-needed.csv", version="bootstrap", min_confidence=0.90
            )
    if not validate_glossary(glossary).ok:
        raise RuntimeError(f"Invalid glossary: {glossary}")
    write_json(ready, {"fingerprint": fp, "glossary_sha256": digest(glossary.read_text()), "aligned_samples": chosen})
    return glossary


def run_project(project: Path, *, requester: Requester | None = None, max_chapters: int | None = None) -> dict:
    if not (project / "project.json").is_file():
        raise ValueError("Unknown project; use litrelay init first")
    with project_lock(project):
        config, source, existing, fp = _inputs(project)
        status = project_status(project)
        if requester is None and (status["missing"] or not status["bootstrap_ready"]):
            for name in ["translation", "support"]:
                backend = config[name]["backend"]
                if backend == "openai" and not os.environ.get("OPENAI_API_KEY"):
                    raise RuntimeError("Set OPENAI_API_KEY for the openai backend")
                if backend != "openai" and shutil.which(backend) is None:
                    raise RuntimeError(f"Install and sign in to {backend}, or choose another backend in project.json")
        progress_path = project / "work/progress.json"
        previous = json.loads(progress_path.read_text()) if progress_path.exists() else {}
        state = {
            "chapters": status["chapters"],
            "fingerprint": fp,
            "glossary_fingerprint": previous.get("glossary_fingerprint"),
        }
        accepted = project / "work/accepted"
        accepted.mkdir(parents=True, exist_ok=True)
        for n, text in existing.items():
            validate_chapter(n, text, min_chars=config["min_chars"], target_language=config["target_language"])
            (accepted / f"{n:04d}.txt").write_text(text, encoding="utf-8")
            state["chapters"][str(n)] = {
                "origin": "existing_translation",
                "fingerprint": fp,
                "source_sha256": digest(source[n]),
                "target_sha256": digest(text),
            }
        write_json(project / "work/progress.json", state)
        missing = [n for n in source if str(n) not in state["chapters"]]
        if max_chapters is not None:
            if max_chapters < 1:
                raise ValueError("max_chapters must be positive")
            missing = missing[:max_chapters]
        glossary_path = project / "work/glossary/active.csv"
        if not glossary_path.exists() or state["glossary_fingerprint"] != fp:
            base = _bootstrap(project, config, source, existing, fp, requester)
            glossary_path.parent.mkdir(parents=True, exist_ok=True)
            glossary_path.write_text(base.read_text(), encoding="utf-8")
            state["glossary_fingerprint"] = fp
            write_json(progress_path, state)
        elif state["chapters"] and any(x["fingerprint"] != fp for x in state["chapters"].values()):
            raise RuntimeError("Mixed project checkpoints")
        while missing:
            start = end = missing[0]
            while end + 1 in missing and end - start + 1 < config["batch_size"]:
                end += 1
            batch = project / "work/batches" / f"{start:04d}-{end:04d}-{fp[:12]}"
            cfg = _batch_config(
                project, config, batch=batch, start=start, end=end, glossary=glossary_path, requester=requester
            )
            report = run_batch(cfg)
            if report.qa_failed or report.published != end - start + 1:
                raise RuntimeError(
                    f"QA blocked export; inspect {batch}/needs-revision.txt and rerun after resolving its defects"
                )
            scores = {
                str(int(q["chapter_id"])): {k: q[k] for k in config["qa_thresholds"]}
                for row in (batch / "qa.results.jsonl").read_text().splitlines()
                if (q := json.loads(json.loads(row)["output"]))
            }
            for n in range(start, end + 1):
                text = (batch / "published" / f"{n:04d}.txt").read_text(encoding="utf-8")
                validate_chapter(n, text, min_chars=config["min_chars"], target_language=config["target_language"])
                (accepted / f"{n:04d}.txt").write_text(text, encoding="utf-8")
                state["chapters"][str(n)] = {
                    "origin": "generated",
                    "fingerprint": fp,
                    "source_sha256": digest(source[n]),
                    "target_sha256": digest(text),
                    "qa_scores": scores[str(n)],
                    "batch": str(batch.relative_to(project)),
                }
                missing.remove(n)
            glossary_path.write_text(report.next_glossary_csv.read_text(), encoding="utf-8")
            write_json(project / "work/progress.json", state)
        result = project_status(project)
        if result["complete"]:
            result = export_project(project)
        return result


def export_project(project: Path) -> dict:
    config = read_config(project)
    status = project_status(project)
    if not status["complete"]:
        raise ValueError(
            f"Book is incomplete; bootstrap_ready={status['bootstrap_ready']}, missing chapters {status['missing'][:20]}"
        )
    chapters = {
        n: (project / "work/accepted" / f"{n:04d}.txt").read_text(encoding="utf-8")
        for n in range(1, status["total"] + 1)
    }
    for n, text in chapters.items():
        validate_chapter(n, text, min_chars=config["min_chars"], target_language=config["target_language"])
    glossary = project / "work/glossary/active.csv"
    public_glossary = normalize_glossary(glossary.read_text(), public=True)
    report = {k: v for k, v in status.items() if k != "missing"}
    report.update(
        {
            "title": config["title"],
            "source_language": config["source_language"],
            "target_language": config["target_language"],
            "profile": config["profile"],
        }
    )
    files = export_book(
        chapters,
        out_dir=project / "output",
        title=config["title"],
        language=config["target_language"],
        report=report,
        glossary=public_glossary,
    )
    write_json(project / "output/report.json", report)
    return {**status, "outputs": {k: str(v) for k, v in files.items()}}
