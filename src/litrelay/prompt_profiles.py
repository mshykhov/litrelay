from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STYLES = {
    "continuation": "Match the established translation: its names, terminology, narrator voice, register, punctuation and dialogue style. Existing target chapters are evidence; preserve their established choices.",
    "fresh": "Create consistent natural literary prose. Choose names and recurring terminology deliberately; keep the same choices once recorded in the glossary.",
    "literary": "Use fluent, expressive literary prose with natural rhythm and vivid dialogue. Preserve the author's voice and every fact; avoid decorative additions and paraphrased summaries.",
}
SYSTEMS = {
    "translation": "You are a professional literary translator from {source_language} to {target_language}. Translate the FULL chapter. Preserve all paragraphs, dialogue, facts, numbers, scene order and meaningful author notes. Translate the title and preserve its chapter number. Follow canonical glossary targets, never alternatives. Use established target-language context when available. Self-check completeness and terminology. Return the requested JSON schema only.",
    "qa": "You are a literary translation editor for {source_language} to {target_language}. Compare the FULL source with the generated translation and glossary. No reference translation is available. Check meaning, completeness including numbers and final paragraphs, terminology and literary style. Score each requested metric from 0 to 100. Give concrete defects. Never treat fluent writing as evidence of completeness. Return the requested JSON schema only.",
    "glossary": "You are a literary terminologist for {source_language} to {target_language}. Extract recurring names, places, organizations and concepts actually evidenced by the supplied source and translation. Preserve established target terms. Skip ordinary words. Return the requested CSV schema only.",
    "alignment": "You are an alignment auditor for {source_language} and {target_language}. Determine whether the supplied source and target chapters describe the same events in the same order. Do not trust matching numbers alone. Return the requested JSON schema only.",
}
QUALITY_GATES = [
    "Preserve all source facts, numbers, paragraph content, dialogue turns and scene order without adding details.",
    "Follow canonical glossary target terms, including grammatical inflection; do not use rejected alternatives.",
    "Write natural literary prose in the configured target language and follow the selected style.",
    "Do not leave untranslated source residue or mixed-script names where the target language does not require them.",
]


@dataclass(frozen=True)
class PromptSettings:
    source_language: str
    target_language: str
    style: str = ""
    templates: dict[str, str] = field(default_factory=dict)
    reader_feedback: str = ""


def prepare_tasks(path: Path, settings: PromptSettings) -> Path:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        task = json.loads(line)
        agent = task["agent"]
        stage = {
            "translation-agent": "translation",
            "translation-qa": "qa",
            "glossary-extractor": "glossary",
            "alignment-auditor": "alignment",
        }.get(agent, "glossary")
        system = settings.templates.get(stage, SYSTEMS[stage])
        system = system.replace("{source_language}", settings.source_language).replace(
            "{target_language}", settings.target_language
        )
        task["system"] = (
            system + f"\nLanguages: {settings.source_language} -> {settings.target_language}.\nStyle: {settings.style}"
        )
        data = task["input"]
        if stage == "qa":
            task["system"] += (
                "\nAn empty glossary is valid when translating from scratch. Judge newly coined terms "
                "against the source and their consistency within the chapter; do not deduct points "
                "merely because no canonical glossary exists yet. Glossary extraction and persistence "
                "are handled by the pipeline, not by the chapter translator."
                " When provisional_glossary_candidates are supplied, verify their names and meanings "
                "against the source and the current translation. These are newly extracted proposals, "
                "not immutable canonical choices. Score only the translated chapter, including terminology "
                "actually used in it. Put concerns about canonical glossary notes or provisional proposals "
                "alone in glossary_issues for a human editor, not in issues or missing_or_changed_facts, "
                "and do not lower chapter scores for those concerns. Canonical notes can rely on wider "
                "chapters; absence of supporting evidence in this chapter is not a translation defect. "
                "The translator cannot change the canonical glossary. Approved proper names may be "
                "localized concisely; do not require every source morpheme in a name. Wrong entities "
                "or meanings in the translated chapter remain translation defects and affect scores. "
                "Use issues, missing_or_changed_facts and recommended_action only for translation fixes."
            )
        if settings.reader_feedback and stage in {"translation", "qa"}:
            data["reader_feedback"] = settings.reader_feedback
            task["system"] += (
                "\nReader feedback applies only to this chapter. Follow it while preserving source facts "
                "and canonical glossary choices. During QA, check whether it was addressed; report "
                "unresolved defects and lower the relevant quality scores."
            )
        data["source_language"] = settings.source_language
        data["target_language"] = settings.target_language
        if "recent_russian_context" in data:
            data["recent_target_context"] = data.pop("recent_russian_context")
        if "quality_gates" in data:
            data["quality_gates"] = QUALITY_GATES
        if "previous_translation" in data:
            task["system"] += (
                "\nRevision: repair every listed QA defect, return the complete corrected translation, preserve correct material."
            )
        if isinstance(data.get("prompt"), str):
            data["prompt"] = (
                data["prompt"]
                .replace("Chinese", settings.source_language)
                .replace("Russian", settings.target_language)
                .replace("RUSSIAN", "TARGET")
            )
        rows.append(task)
    configured = path.with_name(path.stem + ".configured.jsonl")
    configured.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    return configured
