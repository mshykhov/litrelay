from __future__ import annotations

import argparse
import json
from pathlib import Path

from litrelay.project_config import initialize_project
from litrelay.project_scaffold import _validate_slug
from litrelay.project_workflow import export_project, project_status, run_project
from litrelay.prompt_profiles import STYLES

COMMANDS = {"init", "run", "status", "export", "profiles", "reader"}


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
    init.add_argument("--min-chars", type=int, default=100)
    for command in ["run", "status", "export"]:
        parser = subparsers.add_parser(
            command,
            help={
                "run": "Translate missing chapters, verify and export the complete book",
                "status": "Show local progress without calling a model",
                "export": "Package verified chapters as TXT, EPUB and ZIP",
            }[command],
        )
        parser.add_argument("name")
        parser.add_argument("--workspace", type=Path, default=Path("projects"))
        if command == "run":
            parser.add_argument("--max-chapters", type=int)
            parser.add_argument("--dry-run", action="store_true")
    subparsers.add_parser("profiles", help="List built-in literary translation profiles")
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
            )
            print(
                f"Project: {project}\nProfile: {config['profile']}; {config['source_language']} -> {config['target_language']}\nRun: litrelay run {args.name} --workspace {args.workspace}"
            )
            return 0
        if args.command == "status" or (args.command == "run" and args.dry_run):
            result = project_status(project)
        elif args.command == "export":
            result = export_project(project)
        else:
            result = run_project(project, max_chapters=args.max_chapters)
        summary = {k: v for k, v in result.items() if k not in {"chapters", "fingerprint"}}
        if "missing" in summary:
            summary["missing_preview"] = summary.pop("missing")[:20]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Error: {error}")
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Rerun the same command to resume.")
        return 130
