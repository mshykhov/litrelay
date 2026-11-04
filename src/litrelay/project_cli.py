from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from litrelay.project_config import initialize_project
from litrelay.project_revision import revise_project_chapter
from litrelay.project_scaffold import _validate_slug
from litrelay.project_workflow import export_project, project_status, run_project
from litrelay.prompt_profiles import STYLES
from litrelay.telemetry import latest_summary
from litrelay.term_fix_apply import apply_term_fix
from litrelay.term_fix_batch import TermFixBatchError, fix_terms
from litrelay.term_fix_plan import propose_term_fix

REASONING_EFFORTS = ["low", "medium", "high", "xhigh", "max"]
COMMANDS = {
    "init",
    "run",
    "revise",
    "status",
    "export",
    "profiles",
    "reader",
    "stats",
    "fix-term",
    "fix-terms",
    "apply-term-fix",
}


def register_commands(subparsers: argparse._SubParsersAction) -> None:
    init = subparsers.add_parser("init", help="Import a book and save a reusable translation project")
    init.add_argument("name")
    init.add_argument("--workspace", type=Path, default=Path("projects"))
    init.add_argument("--source", type=Path, required=True)
    init.add_argument("--translation", type=Path)
    init.add_argument("--title")
    init.add_argument("--source-lang", default="zh")
    init.add_argument("--target-lang", default="ru")
    init.add_argument("--profile", choices=list(STYLES))
    init.add_argument("--glossary", type=Path)
    init.add_argument("--style-file", type=Path)
    init.add_argument("--prompts-dir", type=Path)
    init.add_argument("--backend", choices=["codex", "claude", "openai"], default="codex")
    init.add_argument("--model", default="gpt-5.5")
    init.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    init.add_argument("--support-reasoning-effort", choices=REASONING_EFFORTS)
    init.add_argument("--min-chars", type=int, default=100)
    for command in ["run", "revise", "status", "export", "stats"]:
        parser = subparsers.add_parser(
            command,
            help={
                "run": "Translate missing chapters, verify and export the complete book",
                "revise": "Revise one accepted chapter using reader feedback, or translate it again from scratch",
                "status": "Show local progress without calling a model",
                "export": "Package verified chapters as TXT, EPUB and ZIP",
                "stats": "Read the latest debug run summary without calling a model",
            }[command],
        )
        parser.add_argument("name")
        parser.add_argument("--workspace", type=Path, default=Path("projects"))
        if command == "run":
            parser.add_argument("--max-chapters", type=int)
            parser.add_argument("--dry-run", action="store_true")
        if command == "revise":
            chapters = parser.add_mutually_exclusive_group(required=True)
            chapters.add_argument("--chapter", type=int)
            chapters.add_argument("--chapters", help="Inclusive chapter range, e.g. 7-10")
            parser.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
            feedback = parser.add_mutually_exclusive_group()
            feedback.add_argument("--feedback", help="Chapter-specific instructions")
            feedback.add_argument("--feedback-file", type=Path, help="Read UTF-8 instructions from a file")
            parser.add_argument("--from-scratch", action="store_true", help="Do not send the previous translation")
        if command in {"run", "revise"}:
            parser.add_argument("--debug", action="store_true", help="Live stage progress and durable run telemetry")
            parser.add_argument(
                "--log-file", type=Path, help="Append debug events to this JSONL file (implies --debug)"
            )
    subparsers.add_parser("profiles", help="List built-in literary translation profiles")
    term = subparsers.add_parser("fix-term", help="Plan contextual term replacements without retranslating chapters")
    term.add_argument("name")
    term.add_argument("--workspace", type=Path, default=Path("projects"))
    term.add_argument("--source-term", required=True)
    term.add_argument("--target", required=True)
    term.add_argument("--pattern", required=True, help="Regex matching only the target-language spans to replace")
    term.add_argument("--model")
    term.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    term.add_argument("--review-model", help="Independent reviewer model; defaults to project support model")
    term.add_argument("--review-reasoning-effort", choices=REASONING_EFFORTS)
    term.add_argument("--batch-size", type=int, default=64)
    term.add_argument("--apply", action="store_true", help="Apply a fully validated plan after generation")
    apply_term = subparsers.add_parser("apply-term-fix", help="Apply a saved term-fix plan without model calls")
    apply_term.add_argument("name")
    apply_term.add_argument("--workspace", type=Path, default=Path("projects"))
    apply_term.add_argument("--plan", type=Path, required=True)
    terms = subparsers.add_parser(
        "fix-terms", help="Plan, independently review and optionally apply a list of terminology rules"
    )
    terms.add_argument("name")
    terms.add_argument("--workspace", type=Path, default=Path("projects"))
    terms.add_argument("--rules", type=Path, required=True, help="CSV: source_term,target,pattern")
    terms.add_argument("--model")
    terms.add_argument("--reasoning-effort", choices=REASONING_EFFORTS)
    terms.add_argument("--review-model")
    terms.add_argument("--review-reasoning-effort", choices=REASONING_EFFORTS)
    terms.add_argument("--apply", action="store_true")
    terms.add_argument("--debug", action="store_true")
    reader = subparsers.add_parser("reader", help="Optional Reader CMS delivery integration")
    sync = reader.add_subparsers(dest="reader_command", required=True).add_parser("sync")
    sync.add_argument("name")
    sync.add_argument("--workspace", type=Path, default=Path("projects"))
    sync.add_argument("--base-url", required=True)
    sync.add_argument("--book-id", type=int, required=True)
    sync.add_argument("--archive-book-id", type=int)
    sync.add_argument("--audio", action="store_true")
    sync.add_argument("--status", choices=["publish", "draft"], default="publish")


def execute(args: argparse.Namespace) -> int:
    try:
        if args.command == "profiles":
            for name, description in STYLES.items():
                print(f"{name}: {description}")
            return 0
        _validate_slug(args.name)
        project = args.workspace / args.name
        if args.command == "fix-terms":
            with args.rules.open(encoding="utf-8-sig", newline="") as handle:
                rules = list(csv.DictReader(handle))
            result = fix_terms(
                project,
                rules,
                apply=args.apply,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                review_model=args.review_model,
                review_reasoning_effort=args.review_reasoning_effort,
                event_handler=(lambda event: print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True))
                if args.debug
                else None,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "fix-term":
            plan = propose_term_fix(
                project,
                args.source_term,
                args.target,
                args.pattern,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                batch_size=args.batch_size,
                review_model=args.review_model,
                review_reasoning_effort=args.review_reasoning_effort,
            )
            if args.apply:
                result = apply_term_fix(project, Path(plan["plan_path"]))
                result = {k: v for k, v in result.items() if k != "accepted_after"}
            else:
                result = {
                    "plan_path": plan["plan_path"],
                    "matches": len(plan["patches"]),
                    "uncertain": sum(p["uncertain"] for p in plan["patches"]),
                    "preview": plan["patches"][:10],
                    "model": plan["model"],
                    "reasoning_effort": plan["reasoning_effort"],
                    "usage": plan["usage"],
                }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "apply-term-fix":
            result = apply_term_fix(project, args.plan)
            print(json.dumps({k: v for k, v in result.items() if k != "accepted_after"}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "reader":
            import os

            from litrelay.integrations.reader_sync import reader_client, sync_chapters
            from litrelay.project_storage import digest, project_lock

            if not project_status(project)["complete"]:
                raise ValueError("Finish translation before Reader sync")
            username = os.environ.get("READER_API_USER")
            password = os.environ.get("READER_APP_PASSWORD") or os.environ.get("READER_API_PASS")
            if not username or not password:
                raise ValueError("Set READER_API_USER and READER_APP_PASSWORD for Reader sync")
            checkpoint = project / "work/integrations" / digest(args.base_url)[:12] / f"book-{args.book_id}.json"
            with project_lock(project):
                result = sync_chapters(
                    project / "work/accepted",
                    book_id=args.book_id,
                    call=reader_client(args.base_url, username, password),
                    checkpoint=checkpoint,
                    audio=args.audio,
                    archive_book_id=args.archive_book_id,
                    status=args.status,
                )
            print(json.dumps({k: v for k, v in result.items() if k != "chapters"}, indent=2))
            return 0
        if args.command == "init":
            config = initialize_project(
                project,
                source=args.source,
                translation=args.translation,
                title=args.title or args.name,
                source_language=args.source_lang,
                target_language=args.target_lang,
                profile=args.profile,
                glossary=args.glossary,
                min_chars=args.min_chars,
                backend=args.backend,
                model=args.model,
                style=args.style_file.read_text(encoding="utf-8") if args.style_file else "",
                prompts_dir=args.prompts_dir,
                reasoning_effort=args.reasoning_effort,
                support_reasoning_effort=args.support_reasoning_effort,
            )
            print(
                f"Project: {project}\nProfile: {config['profile']}; {config['source_language']} -> {config['target_language']}\nRun: litrelay run {args.name} --workspace {args.workspace}"
            )
            return 0
        if args.command == "status" or (args.command == "run" and args.dry_run):
            result = project_status(project)
        elif args.command == "export":
            result = export_project(project)
        elif args.command == "stats":
            result = latest_summary(project)
        elif args.command == "revise":
            if args.chapters:
                match = re.fullmatch(r"([0-9]+)-([0-9]+)", args.chapters)
                if not match or int(match[1]) < 1 or int(match[1]) > int(match[2]):
                    raise ValueError("--chapters requires a positive ascending range, e.g. 7-10")
                first, last = int(match[1]), int(match[2])
            else:
                first = last = args.chapter
            feedback = args.feedback_file.read_text(encoding="utf-8") if args.feedback_file else args.feedback or ""
            revisions = []
            for chapter in range(first, last + 1):
                try:
                    result = revise_project_chapter(
                        project,
                        chapter=chapter,
                        feedback=feedback,
                        from_scratch=args.from_scratch,
                        debug=args.debug,
                        log_file=args.log_file,
                        reasoning_effort=args.reasoning_effort,
                    )
                except (ValueError, RuntimeError, OSError) as error:
                    if args.chapters:
                        done = [item["revised_chapter"] for item in revisions]
                        raise RuntimeError(
                            f"Chapter {chapter} failed: {error}. Successfully revised chapters: {done}; results kept"
                        ) from error
                    raise
                revisions.append(result)
            if args.chapters:
                result = {
                    **result,
                    "revised_chapters": [item["revised_chapter"] for item in revisions],
                    "revisions": [
                        {k: item[k] for k in ("revised_chapter", "revision_dir", "previous_version")}
                        for item in revisions
                    ],
                }
        else:
            result = run_project(project, max_chapters=args.max_chapters, debug=args.debug, log_file=args.log_file)
        summary = {k: v for k, v in result.items() if k not in {"chapters", "fingerprint"}}
        if "missing" in summary:
            summary["missing_preview"] = summary.pop("missing")[:20]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except TermFixBatchError as error:
        print(
            json.dumps(
                {"error": str(error), "completed_source_terms": error.completed_source_terms, "plans": error.plans},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Error: {error}")
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Rerun the same command to resume.")
        return 130
