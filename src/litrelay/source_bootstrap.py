import csv

from litrelay.agent_results import merge_glossary_results, validate_agent_results
from litrelay.batch_pipeline import BatchConfig, _run_stage
from litrelay.glossary_versioning import merge_glossary_version, validate_glossary
from litrelay.llm_agent_inputs import build_glossary_task, write_jsonl


def bootstrap_source_glossary(config: BatchConfig, source: dict[int, str], count: int) -> list[int]:
    selected = sorted(source)[:count]
    context = "\n\n".join(source[n] for n in selected)
    prompt = (
        "Prepare an initial glossary BEFORE translating this new book. No existing target translation exists. "
        "Use only the supplied source chapters as evidence. Choose concise natural target-language names "
        "and recurring terminology; avoid cumbersome literal calques. Preserve distinct concepts. "
        "Use context to resolve aliases and titles. Record genuine uncertainty in a short note and lower confidence. "
        "Do not invent lore or explain later events. Extract only important recurring people, places, "
        "organizations, ranks, artifacts and techniques. Return CSV: source,target_ru,type,note,confidence. "
        "Use numeric confidence between 0 and 1; no commas inside fields. "
        "The target_ru column contains the configured target language even when it is not Russian.\n\n" + context
    )
    draft = config.batch_dir / "glossary-source.results.jsonl"
    tasks = config.batch_dir / "glossary-source.tasks.jsonl"
    write_jsonl([build_glossary_task(chapter_id="0001", prompt=prompt)], tasks)
    _run_stage(config, tasks, draft, config.translation_profile)
    if not validate_agent_results(tasks, draft, kind="glossary").ok:
        raise RuntimeError(f"Source glossary extraction failed; inspect {draft}")
    proposed = config.batch_dir / "glossary-source.proposed.csv"
    merge_glossary_results(draft, proposed)
    tasks = config.batch_dir / "glossary-source-review.tasks.jsonl"
    reviewed = config.batch_dir / "glossary-source-review.results.jsonl"
    review_prompt = (
        "Review this PROPOSED initial glossary against the supplied original chapters BEFORE book translation. "
        "Check that every source term occurs, aliases and titles refer to the right entities, and target names "
        "are accurate, concise, natural and internally consistent. Correct wrong or clumsy choices; remove "
        "unsupported terms. Do not preserve a bad proposal merely because it is already listed. "
        "Return the full corrected glossary as CSV: source,target_ru,type,note,confidence. "
        "Use numeric confidence 0 to 1 and no commas inside fields. Use the configured target language.\n\n"
        "PROPOSED GLOSSARY:\n" + proposed.read_text(encoding="utf-8") + "\nSOURCE CHAPTERS:\n" + context
    )
    write_jsonl([build_glossary_task(chapter_id="0001", prompt=review_prompt)], tasks)
    _run_stage(config, tasks, reviewed, config.support_profile)
    if not validate_agent_results(tasks, reviewed, kind="glossary").ok:
        raise RuntimeError(f"Source glossary review failed; inspect {reviewed}")
    candidates = config.batch_dir / "glossary-source.reviewed.csv"
    merge_glossary_results(reviewed, candidates)
    with candidates.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    supported = config.batch_dir / "glossary-source.supported.csv"
    unsupported = config.batch_dir / "glossary-source.unmatched.csv"
    for path, matches in [(supported, True), (unsupported, False)]:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(row for row in rows if bool(row["source"] and row["source"] in context) == matches)
    merge_glossary_version(
        supported,
        config.glossary_csv,
        review_csv=config.batch_dir / "review-needed.csv",
        version="source-bootstrap",
        min_confidence=config.glossary_conf_threshold,
    )
    if not validate_glossary(config.glossary_csv).ok:
        raise RuntimeError(f"Invalid source glossary: {config.glossary_csv}")
    return selected
