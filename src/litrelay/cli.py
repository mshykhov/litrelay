import argparse
import json
import os
from pathlib import Path

from litrelay.agent_executor import run_agent_tasks
from litrelay.agent_results import (
    format_agent_result_report,
    merge_glossary_results,
    validate_agent_results,
)
from litrelay.agent_usage import format_agent_usage_summary, summarize_agent_usage
from litrelay.alignment_review import (
    build_alignment_review_rows,
    choose_alignment_review_indexes,
    write_alignment_review_csv,
)
from litrelay.batch_pipeline import BatchConfig, StageProfile, run_batch
from litrelay.chapter_map import build_chapter_map_rows, write_chapter_map_csv
from litrelay.chapter_pairs import discover_pairs
from litrelay.glossary_feedback import write_glossary_candidates
from litrelay.glossary_reconcile import (
    build_reconcile_batch_task,
    flag_glossary_terms,
    write_reconcile_overrides,
)
from litrelay.glossary_subset import DEFAULT_ALWAYS_INCLUDE_TYPES, write_glossary_subset, write_glossary_subsets
from litrelay.glossary_versioning import (
    apply_glossary_overrides,
    format_glossary_validation_report,
    merge_glossary_version,
    validate_glossary,
    write_batch_manifest,
)
from litrelay.integrations.reader import ReaderApiPublisher
from litrelay.llm_agent_inputs import build_alignment_task, build_glossary_task, write_jsonl
from litrelay.pilot_tasks import write_translation_pilot_task, write_translation_qa_task
from litrelay.post_translation_glossary import write_post_translation_glossary_tasks
from litrelay.project_cli import COMMANDS, register_commands
from litrelay.project_cli import execute as execute_project
from litrelay.project_scaffold import create_novel_project
from litrelay.prompts import build_glossary_prompt
from litrelay.protected_terms import (
    apply_protected_term_fixes,
    format_protected_term_report,
    validate_protected_terms,
)
from litrelay.qa_gate import evaluate_qa_results, format_qa_gate_report
from litrelay.ranobelib_download import download_ranobelib_chapters, read_ranobelib_refs_from_csv
from litrelay.source_text_split import split_numbered_chinese_txt
from litrelay.tbl_glossary import write_tbl_glossary_csv
from litrelay.text_extraction import extract_text
from litrelay.text_verification import format_verification_report, verify_numbered_texts, verify_text_directory
from litrelay.translation_batch import write_translation_batch_tasks
from litrelay.translation_results import (
    export_translation_results,
    format_translation_result_report,
    validate_translation_results,
)
from litrelay.translation_state import advance_state, read_state, write_state


def main() -> None:
    raise SystemExit(run())


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in COMMANDS:
        return execute_project(args)

    if args.command == "make-glossary-prompts":
        return _make_glossary_prompts(args)
    if args.command == "make-chapter-map":
        return _make_chapter_map(args)
    if args.command == "extract-texts":
        return _extract_texts(args)
    if args.command == "download-ranobelib":
        return _download_ranobelib(args)
    if args.command == "verify-texts":
        return _verify_texts(args)
    if args.command == "split-source-txt":
        return _split_source_txt(args)
    if args.command == "verify-numbered-texts":
        return _verify_numbered_texts(args)
    if args.command == "make-alignment-review":
        return _make_alignment_review(args)
    if args.command == "make-agent-inputs":
        return _make_agent_inputs(args)
    if args.command == "run-agent-tasks":
        return _run_agent_tasks(args)
    if args.command == "validate-agent-results":
        return _validate_agent_results(args)
    if args.command == "merge-glossary-results":
        return _merge_glossary_results(args)
    if args.command == "summarize-agent-usage":
        return _summarize_agent_usage(args)
    if args.command == "make-translation-pilot-task":
        return _make_translation_pilot_task(args)
    if args.command == "make-translation-qa-task":
        return _make_translation_qa_task(args)
    if args.command == "init-novel":
        return _init_novel(args)
    if args.command == "make-translation-batch":
        return _make_translation_batch(args)
    if args.command == "validate-translation-results":
        return _validate_translation_results(args)
    if args.command == "export-translation-results":
        return _export_translation_results(args)
    if args.command == "make-glossary-subset":
        return _make_glossary_subset(args)
    if args.command == "make-glossary-subsets":
        return _make_glossary_subsets(args)
    if args.command == "make-post-translation-glossary-tasks":
        return _make_post_translation_glossary_tasks(args)
    if args.command == "export-tbl-glossary":
        return _export_tbl_glossary(args)
    if args.command == "validate-glossary":
        return _validate_glossary(args)
    if args.command == "merge-glossary-version":
        return _merge_glossary_version(args)
    if args.command == "write-batch-manifest":
        return _write_batch_manifest(args)
    if args.command == "apply-glossary-overrides":
        return _apply_glossary_overrides(args)
    if args.command == "validate-protected-terms":
        return _validate_protected_terms(args)
    if args.command == "apply-protected-term-fixes":
        return _apply_protected_term_fixes(args)
    if args.command == "run-batch":
        return _run_batch(args)
    if args.command == "qa-gate":
        return _qa_gate(args)
    if args.command == "make-glossary-candidates":
        return _make_glossary_candidates(args)
    if args.command == "flag-glossary-terms":
        return _flag_glossary_terms(args)
    if args.command == "apply-reconcile-results":
        return _apply_reconcile_results(args)
    if args.command == "publish-chapters":
        return _publish_chapters(args)

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="litrelay")
    subparsers = parser.add_subparsers(dest="command")
    register_commands(subparsers)

    prompts = subparsers.add_parser("make-glossary-prompts")
    prompts.add_argument("--source-dir", type=Path, required=True)
    prompts.add_argument("--ru-dir", type=Path, required=True)
    prompts.add_argument("--out-dir", type=Path, required=True)
    prompts.add_argument("--source-lang", default="Chinese")
    prompts.add_argument("--target-lang", default="Russian")

    chapter_map = subparsers.add_parser("make-chapter-map")
    chapter_map.add_argument("--ranobelib-json", type=Path, required=True)
    chapter_map.add_argument("--qidian-json", type=Path, required=True)
    chapter_map.add_argument("--out-csv", type=Path, required=True)
    chapter_map.add_argument("--ranobelib-slug", required=True)
    chapter_map.add_argument("--preferred-branch-id", type=int)
    chapter_map.add_argument("--ranobelib-base-url", default="https://ranobelib.me/ru")

    extract_texts = subparsers.add_parser("extract-texts")
    extract_texts.add_argument("--format", choices=["ranobelib-api", "qidian-page-json"], required=True)
    extract_texts.add_argument("--input-dir", type=Path, required=True)
    extract_texts.add_argument("--out-dir", type=Path, required=True)

    ranobelib = subparsers.add_parser("download-ranobelib")
    ranobelib.add_argument("--chapter-map-csv", type=Path, required=True)
    ranobelib.add_argument("--api-slug", required=True)
    ranobelib.add_argument("--out-json-dir", type=Path, required=True)
    ranobelib.add_argument("--out-text-dir", type=Path, required=True)
    ranobelib.add_argument("--start-index", type=int)
    ranobelib.add_argument("--end-index", type=int)
    ranobelib.add_argument("--limit", type=int)
    ranobelib.add_argument("--sleep-seconds", type=float, default=0.2)
    ranobelib.add_argument("--force", action="store_true")

    verify = subparsers.add_parser("verify-texts")
    verify.add_argument("--chapter-map-csv", type=Path, required=True)
    verify.add_argument("--text-dir", type=Path, required=True)
    verify.add_argument("--min-chars", type=int, default=1000)

    split_source = subparsers.add_parser("split-source-txt")
    split_source.add_argument("--source-txt", type=Path, required=True)
    split_source.add_argument("--out-dir", type=Path, required=True)
    split_source.add_argument("--encoding", default="utf-8")

    verify_numbered = subparsers.add_parser("verify-numbered-texts")
    verify_numbered.add_argument("--text-dir", type=Path, required=True)
    verify_numbered.add_argument("--expected-count", type=int, required=True)
    verify_numbered.add_argument("--min-chars", type=int, default=1000)

    alignment = subparsers.add_parser("make-alignment-review")
    alignment.add_argument("--working-map-csv", type=Path, required=True)
    alignment.add_argument("--source-dir", type=Path, required=True)
    alignment.add_argument("--ru-dir", type=Path, required=True)
    alignment.add_argument("--out-csv", type=Path, required=True)
    alignment.add_argument("--total", type=int, required=True)
    alignment.add_argument("--sample-every", type=int, default=25)
    alignment.add_argument("--known-risks", default="")
    alignment.add_argument("--preview-chars", type=int, default=360)

    agent_inputs = subparsers.add_parser("make-agent-inputs")
    agent_inputs.add_argument("--kind", choices=["alignment", "glossary"], required=True)
    agent_inputs.add_argument("--out-jsonl", type=Path, required=True)
    agent_inputs.add_argument("--working-map-csv", type=Path)
    agent_inputs.add_argument("--source-dir", type=Path)
    agent_inputs.add_argument("--ru-dir", type=Path)
    agent_inputs.add_argument("--prompts-dir", type=Path)

    run_agents = subparsers.add_parser("run-agent-tasks")
    run_agents.add_argument("--input-jsonl", type=Path, required=True)
    run_agents.add_argument("--out-jsonl", type=Path, required=True)
    run_agents.add_argument("--model", default="gpt-5.4")
    run_agents.add_argument("--max-output-tokens", type=int, default=1200)
    run_agents.add_argument("--limit", type=int)
    run_agents.add_argument("--no-resume", action="store_true")
    run_agents.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high", "xhigh"])

    validate_agents = subparsers.add_parser("validate-agent-results")
    validate_agents.add_argument("--kind", choices=["alignment", "glossary"], required=True)
    validate_agents.add_argument("--tasks-jsonl", type=Path, required=True)
    validate_agents.add_argument("--results-jsonl", type=Path, required=True)

    merge_glossary = subparsers.add_parser("merge-glossary-results")
    merge_glossary.add_argument("--results-jsonl", type=Path, required=True)
    merge_glossary.add_argument("--out-csv", type=Path, required=True)

    usage = subparsers.add_parser("summarize-agent-usage")
    usage.add_argument("--results-jsonl", type=Path, required=True)
    usage.add_argument("--model", choices=["gpt-5.4-mini", "gpt-5.4"], required=True)

    pilot_translation = subparsers.add_parser("make-translation-pilot-task")
    pilot_translation.add_argument("--chapter-id", required=True)
    pilot_translation.add_argument("--source-dir", type=Path, required=True)
    pilot_translation.add_argument("--ru-dir", type=Path, required=True)
    pilot_translation.add_argument("--glossary-csv", type=Path, required=True)
    pilot_translation.add_argument("--out-jsonl", type=Path, required=True)
    pilot_translation.add_argument("--context-start", type=int, required=True)
    pilot_translation.add_argument("--context-end", type=int, required=True)

    pilot_qa = subparsers.add_parser("make-translation-qa-task")
    pilot_qa.add_argument("--chapter-id", required=True)
    pilot_qa.add_argument("--source-dir", type=Path, required=True)
    pilot_qa.add_argument("--ru-dir", type=Path, required=True)
    pilot_qa.add_argument("--glossary-csv", type=Path, required=True)
    pilot_qa.add_argument("--translation-results-jsonl", type=Path, required=True)
    pilot_qa.add_argument("--out-jsonl", type=Path, required=True)

    init_novel = subparsers.add_parser("init-novel")
    init_novel.add_argument("--slug", required=True)
    init_novel.add_argument("--title", required=True)
    init_novel.add_argument("--source-lang", required=True)
    init_novel.add_argument("--target-lang", required=True)
    init_novel.add_argument("--root", type=Path, default=Path("."))

    translation_batch = subparsers.add_parser("make-translation-batch")
    translation_batch.add_argument("--source-dir", type=Path, required=True)
    translation_batch.add_argument("--context-dir", type=Path, required=True)
    translation_batch.add_argument("--glossary-csv", type=Path, required=True)
    translation_batch.add_argument("--out-jsonl", type=Path, required=True)
    translation_batch.add_argument("--start", type=int, required=True)
    translation_batch.add_argument("--end", type=int, required=True)
    translation_batch.add_argument("--context-window", type=int, default=5)
    translation_batch.add_argument("--style-guide", type=Path)
    translation_batch.add_argument("--recap", type=Path)
    translation_batch.add_argument("--glossary-subset-dir", type=Path)

    translation_validate = subparsers.add_parser("validate-translation-results")
    translation_validate.add_argument("--tasks-jsonl", type=Path, required=True)
    translation_validate.add_argument("--results-jsonl", type=Path, required=True)

    translation_export = subparsers.add_parser("export-translation-results")
    translation_export.add_argument("--results-jsonl", type=Path, required=True)
    translation_export.add_argument("--out-dir", type=Path, required=True)

    glossary_subset = subparsers.add_parser("make-glossary-subset")
    glossary_subset.add_argument("--glossary-csv", type=Path, required=True)
    glossary_subset.add_argument("--source-chapter", type=Path, required=True)
    glossary_subset.add_argument("--out-csv", type=Path, required=True)
    glossary_subset.add_argument(
        "--always-include-types",
        default=",".join(sorted(DEFAULT_ALWAYS_INCLUDE_TYPES)),
    )

    glossary_subsets = subparsers.add_parser("make-glossary-subsets")
    glossary_subsets.add_argument("--glossary-csv", type=Path, required=True)
    glossary_subsets.add_argument("--source-dir", type=Path, required=True)
    glossary_subsets.add_argument("--out-dir", type=Path, required=True)
    glossary_subsets.add_argument("--start", type=int, required=True)
    glossary_subsets.add_argument("--end", type=int, required=True)
    glossary_subsets.add_argument(
        "--always-include-types",
        default=",".join(sorted(DEFAULT_ALWAYS_INCLUDE_TYPES)),
    )

    post_glossary = subparsers.add_parser("make-post-translation-glossary-tasks")
    post_glossary.add_argument("--source-dir", type=Path, required=True)
    post_glossary.add_argument("--translation-results-jsonl", type=Path, required=True)
    post_glossary.add_argument("--glossary-csv", type=Path, required=True)
    post_glossary.add_argument("--out-jsonl", type=Path, required=True)

    tbl_glossary = subparsers.add_parser("export-tbl-glossary")
    tbl_glossary.add_argument("--glossary-csv", type=Path, required=True)
    tbl_glossary.add_argument("--out-csv", type=Path, required=True)

    validate_glossary_parser = subparsers.add_parser("validate-glossary")
    validate_glossary_parser.add_argument("--glossary-csv", type=Path, required=True)
    validate_glossary_parser.add_argument("--previous-csv", type=Path)
    validate_glossary_parser.add_argument("--allow-target-changes", action="store_true")

    merge_glossary = subparsers.add_parser("merge-glossary-version")
    merge_glossary.add_argument("--candidates-csv", type=Path, required=True)
    merge_glossary.add_argument("--out-csv", type=Path, required=True)
    merge_glossary.add_argument("--base-csv", type=Path)
    merge_glossary.add_argument("--review-csv", type=Path)
    merge_glossary.add_argument("--changelog", type=Path)
    merge_glossary.add_argument("--version", default="")
    merge_glossary.add_argument("--min-confidence", type=float, default=0.0)

    batch_manifest = subparsers.add_parser("write-batch-manifest")
    batch_manifest.add_argument("--out-json", type=Path, required=True)
    batch_manifest.add_argument("--slug", required=True)
    batch_manifest.add_argument("--start", type=int, required=True)
    batch_manifest.add_argument("--end", type=int, required=True)
    batch_manifest.add_argument("--model", required=True)
    batch_manifest.add_argument("--glossary-csv", type=Path, required=True)
    batch_manifest.add_argument("--glossary-version", required=True)
    batch_manifest.add_argument("--style-guide", type=Path)
    batch_manifest.add_argument("--recap", type=Path)
    batch_manifest.add_argument("--prompt-version", default="translation-agent-v1")

    glossary_overrides = subparsers.add_parser("apply-glossary-overrides")
    glossary_overrides.add_argument("--base-csv", type=Path, required=True)
    glossary_overrides.add_argument("--overrides-csv", type=Path, required=True)
    glossary_overrides.add_argument("--out-csv", type=Path, required=True)

    protected_validate = subparsers.add_parser("validate-protected-terms")
    protected_validate.add_argument("--text-dir", type=Path, required=True)
    protected_validate.add_argument("--protected-csv", type=Path, required=True)

    protected_fix = subparsers.add_parser("apply-protected-term-fixes")
    protected_fix.add_argument("--source-dir", type=Path, required=True)
    protected_fix.add_argument("--protected-csv", type=Path, required=True)
    protected_fix.add_argument("--out-dir", type=Path, required=True)

    qa_gate_parser = subparsers.add_parser("qa-gate")
    qa_gate_parser.add_argument("--results-jsonl", type=Path, required=True)

    candidates = subparsers.add_parser("make-glossary-candidates")
    candidates.add_argument("--results-jsonl", type=Path, required=True)
    candidates.add_argument("--out-csv", type=Path, required=True)

    flag_terms = subparsers.add_parser("flag-glossary-terms")
    flag_terms.add_argument("--glossary-csv", type=Path, required=True)
    flag_terms.add_argument("--published-ru-dir", type=Path, required=True)
    flag_terms.add_argument("--out-jsonl", type=Path, required=True)
    flag_terms.add_argument("--confidence-threshold", type=float, default=0.80)

    reconcile_apply = subparsers.add_parser("apply-reconcile-results")
    reconcile_apply.add_argument("--results-jsonl", type=Path, required=True)
    reconcile_apply.add_argument("--out-csv", type=Path, required=True)

    run_batch_parser = subparsers.add_parser("run-batch")
    run_batch_parser.add_argument("--slug", required=True)
    run_batch_parser.add_argument("--start", type=int)
    run_batch_parser.add_argument("--end", type=int)
    run_batch_parser.add_argument("--state-file", type=Path)
    run_batch_parser.add_argument("--count", type=int, default=10)
    run_batch_parser.add_argument("--source-dir", type=Path, required=True)
    run_batch_parser.add_argument("--context-dir", type=Path, required=True)
    run_batch_parser.add_argument("--published-ru-dir", type=Path, required=True)
    run_batch_parser.add_argument("--glossary-csv", type=Path, required=True)
    run_batch_parser.add_argument("--batch-dir", type=Path, required=True)
    run_batch_parser.add_argument("--translation-backend", choices=["openai", "claude", "codex"], default="codex")
    run_batch_parser.add_argument("--translation-model", default="gpt-5.5")
    run_batch_parser.add_argument("--translation-concurrency", type=int, default=1)
    run_batch_parser.add_argument("--support-backend", choices=["openai", "claude", "codex"], default="codex")
    run_batch_parser.add_argument("--support-model", default="gpt-5.5")
    run_batch_parser.add_argument("--support-concurrency", type=int, default=5)
    run_batch_parser.add_argument("--cli-timeout", type=int, default=900)
    run_batch_parser.add_argument("--max-retries", type=int, default=2)
    run_batch_parser.add_argument("--revise-attempts", type=int, default=1)
    run_batch_parser.add_argument("--chain", action="store_true")
    run_batch_parser.add_argument(
        "--no-incremental-glossary",
        action="store_true",
        help="disable per-chapter glossary accumulation within a chained batch",
    )
    run_batch_parser.add_argument("--context-window", type=int, default=10)
    run_batch_parser.add_argument("--glossary-conf-threshold", type=float, default=0.90)
    run_batch_parser.add_argument("--protected-csv", type=Path)
    run_batch_parser.add_argument("--style-guide", type=Path)
    run_batch_parser.add_argument("--recap", type=Path)
    run_batch_parser.add_argument("--qa-min-meaning", type=float, default=85.0)
    run_batch_parser.add_argument("--qa-min-terminology", type=float, default=85.0)
    run_batch_parser.add_argument("--qa-min-style", type=float, default=75.0)
    run_batch_parser.add_argument("--qa-min-omission", type=float, default=88.0)

    publish_chapters = subparsers.add_parser("publish-chapters")
    publish_chapters.add_argument("--chapters-dir", type=Path, required=True)
    publish_chapters.add_argument("--reader-base-url", required=True)
    publish_chapters.add_argument("--reader-book-id", type=int, required=True)
    publish_chapters.add_argument("--reader-user", default=None)
    publish_chapters.add_argument("--status", choices=["publish", "draft"], default="publish")
    publish_chapters.add_argument("--start-number", type=int)

    return parser


def _make_glossary_prompts(args: argparse.Namespace) -> int:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    pairs = discover_pairs(args.source_dir, args.ru_dir)

    for pair in pairs:
        source_text = pair.source_path.read_text(encoding="utf-8")
        ru_text = pair.ru_path.read_text(encoding="utf-8")
        prompt = build_glossary_prompt(
            chapter_id=pair.chapter_id,
            source_text=source_text,
            ru_text=ru_text,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
        )
        (args.out_dir / f"{pair.chapter_id}.md").write_text(prompt, encoding="utf-8")

    print(f"Wrote {len(pairs)} glossary prompt(s) to {args.out_dir}")
    return 0


def _make_chapter_map(args: argparse.Namespace) -> int:
    ranobelib_payload = json.loads(args.ranobelib_json.read_text(encoding="utf-8"))
    qidian_payload = json.loads(args.qidian_json.read_text(encoding="utf-8"))
    rows = build_chapter_map_rows(
        ranobelib_payload,
        qidian_payload,
        ranobelib_slug=args.ranobelib_slug,
        preferred_branch_id=args.preferred_branch_id,
        ranobelib_base_url=args.ranobelib_base_url,
    )
    write_chapter_map_csv(rows, args.out_csv)

    print(f"Wrote {len(rows)} chapter map row(s) to {args.out_csv}")
    return 0


def _extract_texts(args: argparse.Namespace) -> int:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    input_paths = sorted(args.input_dir.glob("*.json"))

    for input_path in input_paths:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        text = extract_text(payload, args.format)
        (args.out_dir / f"{input_path.stem}.txt").write_text(text, encoding="utf-8")

    print(f"Wrote {len(input_paths)} text file(s) to {args.out_dir}")
    return 0


def _download_ranobelib(args: argparse.Namespace) -> int:
    refs = read_ranobelib_refs_from_csv(
        args.chapter_map_csv,
        start_index=args.start_index,
        end_index=args.end_index,
        limit=args.limit,
    )
    summary = download_ranobelib_chapters(
        refs,
        api_slug=args.api_slug,
        out_json_dir=args.out_json_dir,
        out_text_dir=args.out_text_dir,
        sleep_seconds=args.sleep_seconds,
        force=args.force,
    )
    print(f"RanobeLib download: downloaded={summary.downloaded} skipped={summary.skipped} failed={summary.failed}")
    return 1 if summary.failed else 0


def _verify_texts(args: argparse.Namespace) -> int:
    report = verify_text_directory(args.chapter_map_csv, args.text_dir, min_chars=args.min_chars)
    print(format_verification_report(report))
    return 0 if report.ok else 1


def _split_source_txt(args: argparse.Namespace) -> int:
    summary = split_numbered_chinese_txt(args.source_txt, args.out_dir, encoding=args.encoding)
    print(f"Wrote {summary.chapter_count} source chapter file(s) to {args.out_dir}")
    return 0


def _verify_numbered_texts(args: argparse.Namespace) -> int:
    report = verify_numbered_texts(args.text_dir, expected_count=args.expected_count, min_chars=args.min_chars)
    print(format_verification_report(report))
    return 0 if report.ok else 1


def _make_alignment_review(args: argparse.Namespace) -> int:
    known_risks = [int(value) for value in args.known_risks.split(",") if value.strip()]
    indexes = choose_alignment_review_indexes(
        total=args.total,
        sample_every=args.sample_every,
        known_risks=known_risks,
    )
    rows = build_alignment_review_rows(
        args.working_map_csv,
        source_dir=args.source_dir,
        ru_dir=args.ru_dir,
        indexes=indexes,
        preview_chars=args.preview_chars,
    )
    write_alignment_review_csv(rows, args.out_csv)
    print(f"Wrote {len(rows)} alignment review row(s) to {args.out_csv}")
    return 0


def _make_agent_inputs(args: argparse.Namespace) -> int:
    if args.kind == "alignment":
        tasks = _build_alignment_tasks(args)
    else:
        tasks = _build_glossary_tasks(args)
    write_jsonl(tasks, args.out_jsonl)
    print(f"Wrote {len(tasks)} {args.kind} agent task(s) to {args.out_jsonl}")
    return 0


def _run_agent_tasks(args: argparse.Namespace) -> int:
    summary = run_agent_tasks(
        args.input_jsonl,
        args.out_jsonl,
        model=args.model,
        max_output_tokens=args.max_output_tokens,
        limit=args.limit,
        resume=not args.no_resume,
        reasoning_effort=args.reasoning_effort,
    )
    print(f"Agent run: completed={summary.completed} skipped={summary.skipped} failed={summary.failed}")
    return 1 if summary.failed else 0


def _validate_agent_results(args: argparse.Namespace) -> int:
    report = validate_agent_results(args.tasks_jsonl, args.results_jsonl, kind=args.kind)
    print(format_agent_result_report(report))
    return 0 if report.ok else 1


def _merge_glossary_results(args: argparse.Namespace) -> int:
    count = merge_glossary_results(args.results_jsonl, args.out_csv)
    print(f"Wrote {count} glossary term row(s) to {args.out_csv}")
    return 0


def _summarize_agent_usage(args: argparse.Namespace) -> int:
    summary = summarize_agent_usage(args.results_jsonl, model=args.model)
    print(format_agent_usage_summary(summary))
    return 0


def _make_translation_pilot_task(args: argparse.Namespace) -> int:
    write_translation_pilot_task(
        chapter_id=args.chapter_id,
        source_dir=args.source_dir,
        ru_dir=args.ru_dir,
        glossary_csv=args.glossary_csv,
        out_jsonl=args.out_jsonl,
        context_start=args.context_start,
        context_end=args.context_end,
    )
    print(f"Wrote translation pilot task to {args.out_jsonl}")
    return 0


def _make_translation_qa_task(args: argparse.Namespace) -> int:
    write_translation_qa_task(
        chapter_id=args.chapter_id,
        source_dir=args.source_dir,
        ru_dir=args.ru_dir,
        glossary_csv=args.glossary_csv,
        translation_results_jsonl=args.translation_results_jsonl,
        out_jsonl=args.out_jsonl,
    )
    print(f"Wrote translation QA task to {args.out_jsonl}")
    return 0


def _init_novel(args: argparse.Namespace) -> int:
    summary = create_novel_project(
        args.root,
        slug=args.slug,
        title=args.title,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
    )
    print(
        "Novel project initialized: "
        f"slug={summary.slug} created_files={summary.created_files} created_dirs={summary.created_dirs}"
    )
    return 0


def _make_translation_batch(args: argparse.Namespace) -> int:
    count = write_translation_batch_tasks(
        source_dir=args.source_dir,
        context_dir=args.context_dir,
        glossary_csv=args.glossary_csv,
        out_jsonl=args.out_jsonl,
        start=args.start,
        end=args.end,
        context_window=args.context_window,
        style_guide=args.style_guide,
        recap=args.recap,
        glossary_subset_dir=args.glossary_subset_dir,
    )
    print(f"Wrote {count} translation task(s) to {args.out_jsonl}")
    return 0


def _validate_translation_results(args: argparse.Namespace) -> int:
    report = validate_translation_results(args.tasks_jsonl, args.results_jsonl)
    print(format_translation_result_report(report))
    return 0 if report.ok else 1


def _export_translation_results(args: argparse.Namespace) -> int:
    count = export_translation_results(args.results_jsonl, args.out_dir)
    print(f"Wrote {count} translated chapter file(s) to {args.out_dir}")
    return 0


def _make_glossary_subset(args: argparse.Namespace) -> int:
    always_include_types = {value.strip() for value in args.always_include_types.split(",") if value.strip()}
    count = write_glossary_subset(
        args.glossary_csv,
        args.source_chapter,
        args.out_csv,
        always_include_types=always_include_types,
    )
    print(f"Wrote {count} glossary row(s) to {args.out_csv}")
    return 0


def _make_glossary_subsets(args: argparse.Namespace) -> int:
    always_include_types = {value.strip() for value in args.always_include_types.split(",") if value.strip()}
    summary = write_glossary_subsets(
        args.glossary_csv,
        args.source_dir,
        args.out_dir,
        start=args.start,
        end=args.end,
        always_include_types=always_include_types,
    )
    print(f"Wrote {len(summary)} glossary subset file(s) to {args.out_dir}")
    return 0


def _make_post_translation_glossary_tasks(args: argparse.Namespace) -> int:
    count = write_post_translation_glossary_tasks(
        source_dir=args.source_dir,
        translation_results_jsonl=args.translation_results_jsonl,
        glossary_csv=args.glossary_csv,
        out_jsonl=args.out_jsonl,
    )
    print(f"Wrote {count} post-translation glossary task(s) to {args.out_jsonl}")
    return 0


def _export_tbl_glossary(args: argparse.Namespace) -> int:
    count = write_tbl_glossary_csv(args.glossary_csv, args.out_csv)
    print(f"Wrote {count} TBL glossary row(s) to {args.out_csv}")
    return 0


def _validate_glossary(args: argparse.Namespace) -> int:
    report = validate_glossary(
        args.glossary_csv,
        previous_csv=args.previous_csv,
        allow_target_changes=args.allow_target_changes,
    )
    print(format_glossary_validation_report(report))
    return 0 if report.ok else 1


def _merge_glossary_version(args: argparse.Namespace) -> int:
    summary = merge_glossary_version(
        args.candidates_csv,
        args.out_csv,
        base_csv=args.base_csv,
        review_csv=args.review_csv,
        changelog=args.changelog,
        version=args.version,
        min_confidence=args.min_confidence,
    )
    print(
        "Glossary merge: "
        f"added={summary.added} preserved={summary.preserved} "
        f"conflicts={summary.conflicts} output_rows={summary.output_rows}"
    )
    return 0


def _write_batch_manifest(args: argparse.Namespace) -> int:
    manifest = write_batch_manifest(
        args.out_json,
        slug=args.slug,
        start=args.start,
        end=args.end,
        model=args.model,
        glossary_csv=args.glossary_csv,
        glossary_version=args.glossary_version,
        style_guide=args.style_guide,
        recap=args.recap,
        prompt_version=args.prompt_version,
    )
    print(
        "Batch manifest: "
        f"slug={manifest['slug']} start={manifest['range']['start']} "
        f"end={manifest['range']['end']} glossary={manifest['glossary']['version']}"
    )
    return 0


def _apply_glossary_overrides(args: argparse.Namespace) -> int:
    summary = apply_glossary_overrides(args.base_csv, args.overrides_csv, args.out_csv)
    print(
        "Glossary overrides: "
        f"applied={summary.applied} added={summary.added} "
        f"missing={summary.missing} output_rows={summary.output_rows}"
    )
    return 1 if summary.missing else 0


def _validate_protected_terms(args: argparse.Namespace) -> int:
    report = validate_protected_terms(args.text_dir, args.protected_csv)
    print(format_protected_term_report(report))
    return 0 if report.ok else 1


def _apply_protected_term_fixes(args: argparse.Namespace) -> int:
    summary = apply_protected_term_fixes(args.source_dir, args.protected_csv, args.out_dir)
    print(
        "Protected term fixes: "
        f"files_written={summary.files_written} replacements={summary.replacements} "
        f"out_dir={summary.out_dir}"
    )
    return 0


def _qa_gate(args: argparse.Namespace) -> int:
    report = evaluate_qa_results(args.results_jsonl)
    print(format_qa_gate_report(report))
    return 0 if report.ok else 1


def _make_glossary_candidates(args: argparse.Namespace) -> int:
    summary = write_glossary_candidates(args.results_jsonl, args.out_csv)
    print(f"Wrote {summary.candidates_written} glossary candidate(s) to {args.out_csv}")
    return 0


def _flag_glossary_terms(args: argparse.Namespace) -> int:
    flags = flag_glossary_terms(
        args.glossary_csv, args.published_ru_dir, confidence_threshold=args.confidence_threshold
    )
    task = build_reconcile_batch_task(flags, args.published_ru_dir)
    write_jsonl([task], args.out_jsonl)
    print(f"Flagged {len(flags)} term(s); wrote reconcile batch task to {args.out_jsonl}")
    return 0


def _apply_reconcile_results(args: argparse.Namespace) -> int:
    count = write_reconcile_overrides(args.results_jsonl, args.out_csv)
    print(f"Wrote {count} reconcile override(s) to {args.out_csv}")
    return 0


def _publish_chapters(args: argparse.Namespace) -> int:
    app_password = os.environ.get("READER_APP_PASSWORD") or os.environ.get("READER_API_PASS")
    if not app_password:
        print("Set READER_APP_PASSWORD (or READER_API_PASS) env var for publish-chapters")
        return 1
    username = args.reader_user or os.environ.get("READER_API_USER")
    if not username:
        print("Provide --reader-user or set READER_API_USER env var")
        return 1
    publisher = ReaderApiPublisher(
        base_url=args.reader_base_url,
        book_id=args.reader_book_id,
        username=username,
        app_password=app_password,
        status=args.status,
        renumber_from=args.start_number,
    )
    summary = publisher.publish(args.chapters_dir, {})
    print(f"Published {summary.published} chapter(s) to {summary.target}")
    return 0


def _run_batch(args: argparse.Namespace) -> int:
    state = read_state(args.state_file) if args.state_file is not None else None
    ru_start_number: int | None = None
    if state is not None:
        start = state.last_source_chapter + 1
        end = start + args.count - 1
        ru_start_number = state.last_ru_number + 1
    elif args.start is not None and args.end is not None:
        start, end = args.start, args.end
    else:
        print("run-batch requires either --state-file or both --start and --end")
        return 1

    translation_profile = StageProfile(
        backend=args.translation_backend,
        model=args.translation_model,
        concurrency=args.translation_concurrency,
        max_retries=args.max_retries,
        timeout=args.cli_timeout,
    )
    support_profile = StageProfile(
        backend=args.support_backend,
        model=args.support_model,
        concurrency=args.support_concurrency,
        max_retries=args.max_retries,
        timeout=args.cli_timeout,
    )
    config = BatchConfig(
        slug=args.slug,
        start=start,
        end=end,
        source_dir=args.source_dir,
        context_dir=args.context_dir,
        published_ru_dir=args.published_ru_dir,
        glossary_csv=args.glossary_csv,
        batch_dir=args.batch_dir,
        translation_profile=translation_profile,
        support_profile=support_profile,
        context_window=args.context_window,
        glossary_conf_threshold=args.glossary_conf_threshold,
        revise_attempts=args.revise_attempts,
        chain=args.chain,
        incremental_glossary=not args.no_incremental_glossary,
        qa_thresholds={
            "meaning_score": args.qa_min_meaning,
            "terminology_score": args.qa_min_terminology,
            "style_score": args.qa_min_style,
            "omission_score": args.qa_min_omission,
        },
        protected_csv=args.protected_csv,
        style_guide=args.style_guide,
        recap=args.recap,
    )
    report = run_batch(config)
    print(
        "Batch run: "
        f"translated={report.translated} qa_passed={report.qa_passed} qa_failed={report.qa_failed} "
        f"glossary_candidates={report.glossary_candidates} reconcile_flags={report.reconcile_flags} "
        f"published={report.published} next_glossary={report.next_glossary_csv}"
    )
    if report.qa_failed:
        print("QA failed; no chapters exported and state not advanced")
        return 1
    if state is not None:
        new_state = advance_state(state, report.translated)
        write_state(args.state_file, new_state)
        print(
            f"State advanced: last_source_chapter={new_state.last_source_chapter} "
            f"last_ru_number={new_state.last_ru_number}"
        )
        print(
            "To publish (reader creds from READER_API_* env): novel-translation publish-chapters "
            f"--chapters-dir {config.batch_dir / 'published'} --reader-book-id <BOOK_ID> "
            f"--start-number {ru_start_number} --status draft"
        )
    return 0


def _build_alignment_tasks(args: argparse.Namespace) -> list[dict]:
    if args.working_map_csv is None or args.source_dir is None or args.ru_dir is None:
        raise ValueError("alignment inputs require --working-map-csv, --source-dir and --ru-dir")

    import csv

    tasks = []
    with args.working_map_csv.open(encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            chapter_id = f"{int(row['aligned_index']):04d}"
            source_text = (args.source_dir / f"{chapter_id}.txt").read_text(encoding="utf-8")
            ru_text = (args.ru_dir / f"{chapter_id}.txt").read_text(encoding="utf-8")
            tasks.append(
                build_alignment_task(
                    chapter_id=chapter_id,
                    source_title=row["source_title"],
                    ru_title=row["ru_title"],
                    source_text=source_text,
                    ru_text=ru_text,
                )
            )
    return tasks


def _build_glossary_tasks(args: argparse.Namespace) -> list[dict]:
    if args.prompts_dir is None:
        raise ValueError("glossary inputs require --prompts-dir")

    tasks = []
    for prompt_path in sorted(args.prompts_dir.glob("*.md")):
        tasks.append(
            build_glossary_task(
                chapter_id=prompt_path.stem,
                prompt=prompt_path.read_text(encoding="utf-8"),
            )
        )
    return tasks
