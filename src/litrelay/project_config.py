from __future__ import annotations

import csv
import io
import json
import math
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from litrelay.book_inputs import read_chapters, validate_chapter
from litrelay.glossary_versioning import validate_glossary
from litrelay.project_storage import write_json
from litrelay.prompt_profiles import STYLES


def initialize_project(
    project: Path,
    *,
    source: Path,
    translation: Path | None = None,
    title: str = "Untitled",
    source_language: str = "zh",
    target_language: str = "ru",
    profile: str | None = None,
    glossary: Path | None = None,
    min_chars: int = 100,
    backend: str = "codex",
    model: str = "gpt-5.5",
    style: str = "",
    prompts_dir: Path | None = None,
) -> dict:
    if project.exists() and any(project.iterdir()):
        raise ValueError("Project already exists; use run to resume")
    for language in (source_language, target_language):
        if not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", language):
            raise ValueError("Languages must be BCP47 codes such as zh, ru, en, uk or pt-BR")
    if backend not in {"codex", "claude", "openai"} or not model.strip():
        raise ValueError("Select codex, claude or openai and a model")
    if min_chars < 1:
        raise ValueError("min_chars must be positive")
    chapters = read_chapters(source, min_chars=min_chars)
    missing = set(range(1, max(chapters) + 1)) - chapters.keys()
    if missing:
        raise ValueError(f"Missing source chapters: {sorted(missing)[:20]}")
    existing = read_chapters(translation, min_chars=min_chars) if translation else {}
    if existing.keys() - chapters.keys():
        raise ValueError("Translation contains chapter numbers absent from source")
    for n, text in existing.items():
        validate_chapter(n, text, min_chars=min_chars, target_language=target_language)
    profile = profile or ("continuation" if existing else "fresh")
    if profile not in STYLES:
        raise ValueError(f"Unknown profile: {profile}")
    if profile == "continuation" and not existing:
        raise ValueError("continuation profile requires existing translation")
    templates = {}
    if prompts_dir:
        for name in ["translation", "qa", "glossary", "alignment"]:
            p = prompts_dir / f"{name}.md"
            if p.exists():
                templates[name] = p.read_text(encoding="utf-8")
        if not templates:
            raise ValueError("Prompts directory needs translation.md, qa.md, glossary.md or alignment.md")
    seed = normalize_glossary(glossary.read_text(encoding="utf-8-sig")) if glossary else None
    if seed is not None:
        with TemporaryDirectory(prefix="litrelay-glossary-") as temporary:
            sample = Path(temporary) / "seed.csv"
            sample.write_text(seed, encoding="utf-8")
            report = validate_glossary(sample)
            if not report.ok:
                raise ValueError(f"Invalid seed glossary: {report.errors}")
    for folder in ["input/source", "input/translation", "work/accepted", "work/batches", "work/glossary", "output"]:
        (project / folder).mkdir(parents=True, exist_ok=True)
    if seed is not None:
        path = project / "input/glossary.csv"
        path.write_text(seed, encoding="utf-8")
    for relative, data in [("input/source", chapters), ("input/translation", existing)]:
        for n, text in data.items():
            (project / relative / f"{n:04d}.txt").write_text(text, encoding="utf-8")
    config = {
        "version": 1,
        "title": title,
        "source_language": source_language,
        "target_language": target_language,
        "profile": profile,
        "style": STYLES[profile] + (" " + style if style else ""),
        "prompts": templates,
        "translation": {"backend": backend, "model": model, "concurrency": 1},
        "support": {"backend": backend, "model": model, "concurrency": 5},
        "batch_size": 10,
        "context_window": 5,
        "chain": True,
        "revise_attempts": 2,
        "glossary_samples": 12,
        "min_chars": min_chars,
        "qa_thresholds": {"meaning_score": 90, "terminology_score": 85, "style_score": 75, "omission_score": 95},
    }
    write_json(project / "project.json", config)
    return config


def read_config(project: Path) -> dict:
    config = json.loads((project / "project.json").read_text(encoding="utf-8"))
    if config.get("version") != 1:
        raise ValueError("Unsupported project config version")
    for name in ["batch_size", "context_window", "min_chars", "glossary_samples"]:
        if not isinstance(config[name], int) or config[name] < 1:
            raise ValueError(f"{name} must be positive")
    if (
        not isinstance(config["chain"], bool)
        or not isinstance(config["revise_attempts"], int)
        or not 0 <= config["revise_attempts"] <= 10
    ):
        raise ValueError("Invalid chain/revise_attempts settings")
    for language in [config["source_language"], config["target_language"]]:
        if not isinstance(language, str) or not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*", language):
            raise ValueError("Use BCP 47 language codes")
    expected = {"meaning_score", "terminology_score", "style_score", "omission_score"}
    if set(config["qa_thresholds"]) != expected or any(
        not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 100
        for x in config["qa_thresholds"].values()
    ):
        raise ValueError("QA thresholds need four finite scores between 0 and 100")
    for name in ["translation", "support"]:
        profile = config[name]
        if profile["backend"] not in {"codex", "claude", "openai"} or not profile["model"]:
            raise ValueError(f"Invalid {name} backend/model")
        if not 1 <= profile["concurrency"] <= 32:
            raise ValueError("concurrency must be between 1 and 32")
    return config


def normalize_glossary(text: str, *, public: bool = False) -> str:
    reader = csv.DictReader(io.StringIO(text))
    fields = list(reader.fieldnames or [])
    if "target" in fields and "target_ru" not in fields:
        fields[fields.index("target")] = "target_ru"
    required = {"source", "target_ru", "type", "note", "confidence"}
    if not required.issubset(fields):
        raise ValueError("Glossary needs source,target,type,note,confidence columns (target_ru is also accepted)")
    if public:
        fields = [("target" if x == "target_ru" else x) for x in fields]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for row in reader:
        if "target" in row and "target_ru" not in row:
            row["target_ru"] = row.pop("target")
        if public:
            row["target"] = row.pop("target_ru")
        writer.writerow(row)
    return out.getvalue()
