# LitRelay

[![CI](https://github.com/mshykhov/litrelay/actions/workflows/ci.yml/badge.svg)](https://github.com/mshykhov/litrelay/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Turn an original book, optionally with a partial translation, into a complete translated book.**

LitRelay keeps terminology and voice consistent, translates missing chapters, checks each translation against its full source, and resumes interrupted work. The result is **TXT, EPUB and a ZIP** containing numbered chapters, the book, glossary and quality report. No website is required.

## Three commands

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), and a signed-in Codex CLI. Clone this repository and run:

```bash
uv sync
uv run litrelay init my-book --source /path/to/original --translation /path/to/existing-translation --title "My Book"
uv run litrelay run my-book
```

Omit `--translation` to translate from scratch. Languages default to Chinese → Russian; use `--source-lang en --target-lang uk`, or another language pair.

**Codex is the default backend**, with `gpt-5.5` as the default model. Install the Codex CLI and sign in with `codex login`. LitRelay calls the CLI directly; this backend does not require an `OPENAI_API_KEY` in LitRelay. To select it explicitly:

```bash
uv run litrelay init my-book --source /path/to/original --backend codex --model gpt-5.5
```

Use `--backend claude --model <model>` or `--backend openai --model <model>` to select another provider. The `openai` backend requires `OPENAI_API_KEY` and calls the API directly. Model names can be changed to ones available in your account.

Inputs can be **numbered UTF-8 TXT files**, a combined TXT with numbered headings, or a text EPUB. Original chapters must form a complete sequence starting at 1. Existing translations can contain gaps; LitRelay fills them. Chapters supplied as existing translation are preserved. [Input details](docs/usage.md).

Results: `projects/my-book/output/book.{txt,epub,zip}`. Run the same command again to resume; valid accepted chapters do not call the model again. `uv run litrelay status my-book` shows progress without model calls.

## Profiles and terminology

- **continuation**: selected automatically with an existing translation. Sample aligned pairs, extract established terms and use preceding target chapters as context.
- **fresh**: selected without a translation. Choose terminology from the source and carry new terms into subsequent chapters.
- **literary**: expressive, natural prose while preserving facts and the author's voice.

Languages, style, backend/model, stage concurrency and quality thresholds are saved in `projects/my-book/project.json`. Supply a seed glossary, a style file or your own prompts at initialization. [Profiles and customization](docs/profiles.md).

## Quality and recovery

Translation → source-based QA → automatic revision → deterministic checks → accepted chapters → export. Missing QA, failed scores, changed source hashes, source residue and broken numbering block acceptance. Defaults: meaning90, terminology85, style75, completeness95. These are automated review scores, not percentages of guaranteed accuracy.

Alignment sampling checks prepared source/translation pairs; it does not prove every input chapter is correct. LitRelay cannot reconstruct text missing from an upstream mirror. Use complete originals and correctly numbered pairs. Human editorial review remains useful for publication.

## Debug and run statistics

```bash
uv run litrelay run my-book --debug
uv run litrelay stats my-book
```

Debug shows stages and chapters, elapsed time, models, concurrency, every request attempt, retries, cache hits, QA scores and export progress. Long stages print a heartbeat. JSONL events and a JSON summary are saved under `projects/my-book/work/logs/`, including failed and interrupted runs. Progress goes to stderr; stdout remains JSON.

Token reports include input/output, cached input, cache writes and reasoning when available. Missing usage is `null`; known subtotals and coverage are reported separately. Cached input and reasoning are never added twice. A fully cached resume spends zero new model tokens. Provider-reported dollar estimates are kept when available; LitRelay does not invent prices. [Details, custom log paths and privacy](docs/debug.md).

## Project layout

```text
src/litrelay/          translation, glossary, QA, book I/O and project runner
src/litrelay/integrations/  optional external delivery
projects/<name>/      ignored inputs, configuration, checkpoints and output
examples/            short original demo texts and customizable prompts
docs/                usage, profiles, architecture and integrations
tests/               offline pipeline and packaging regression tests
```

Reader CMS upload and durable audio generation are a separate, explicitly invoked [integration](docs/reader.md). The main workflow never uploads a book or starts audio.

For development: `uv run pytest -q` and `uv build`. Advanced preparation/repair commands remain available through `litrelay --help`; the old `novel-translation` executable is retained as an alias. [Architecture and development](docs/architecture.md).

MIT licensed. No novel texts, credentials or local production data are included in this repository.
