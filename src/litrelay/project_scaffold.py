from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectScaffoldSummary:
    slug: str
    created_files: int
    created_dirs: int


PROJECT_DIRS = [
    "raw/source",
    "raw/ru",
    "metadata",
    "working/glossary",
    "working/batches",
    "working/qa",
    "working/accepted",
    "working/style",
    "working/recap",
    "working/translation-memory",
]


def create_novel_project(
    root: Path,
    *,
    slug: str,
    title: str,
    source_lang: str,
    target_lang: str,
) -> ProjectScaffoldSummary:
    _validate_slug(slug)
    example_dir = root / "examples" / slug
    private_project_dir = root / "private" / "projects" / slug

    created_dirs = 0
    for directory in [example_dir, private_project_dir, *[private_project_dir / value for value in PROJECT_DIRS]]:
        if not directory.exists():
            created_dirs += 1
        directory.mkdir(parents=True, exist_ok=True)

    files = {
        example_dir / "README.md": _readme(slug, title, source_lang, target_lang),
        example_dir / "source-acquisition.md": _source_acquisition(title),
        private_project_dir / "project.json": _project_json(slug, title, source_lang, target_lang),
    }
    created_files = 0
    for path, content in files.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created_files += 1

    return ProjectScaffoldSummary(slug=slug, created_files=created_files, created_dirs=created_dirs)


def _validate_slug(slug: str) -> None:
    if not slug or any(
        character for character in slug if not (character.isascii() and (character.isalnum() or character == "-"))
    ):
        raise ValueError("slug must contain only ASCII letters, digits, and hyphens")
    if slug.startswith("-") or slug.endswith("-") or "--" in slug:
        raise ValueError("slug must not start/end with hyphen or contain double hyphens")


def _project_json(slug: str, title: str, source_lang: str, target_lang: str) -> str:
    payload = {
        "slug": slug,
        "title": title,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "paths": {
            "source_dir": f"private/projects/{slug}/raw/source",
            "existing_translation_dir": f"private/projects/{slug}/raw/ru",
            "metadata_dir": f"private/projects/{slug}/metadata",
            "working_dir": f"private/projects/{slug}/working",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _readme(slug: str, title: str, source_lang: str, target_lang: str) -> str:
    return f"""# {title}

Reusable novel translation project.

```text
slug = {slug}
source_lang = {source_lang}
target_lang = {target_lang}
```

Private working files live in:

```text
private/projects/{slug}/
```
"""


def _source_acquisition(title: str) -> str:
    return f"""# Source acquisition notes

Novel: {title}

Record source URLs, export method, chapter counts, verification commands, and alignment notes here.
"""
