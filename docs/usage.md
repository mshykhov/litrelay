# Inputs, running and exports

## Prepared chapters

A directory contains `1.txt`, `2.txt` or zero-padded `0001.txt`, `0002.txt`. Filenames represent canonical original chapter numbers. Each UTF-8 file contains a title line, then the full body. No navigation menus, paywall previews or verification pages.

Combined TXT supports Arabic-numbered `Chapter 1`, `Глава 1` or `第1章` headings. A preface outside any numbered chapter is rejected rather than silently discarded. Other heading systems should be normalized to numbered files first.

EPUB import reads its XHTML spine in order. Navigation documents and explicitly non-linear items are excluded. Unsupported image-only chapters or ambiguous front matter are rejected; normalize them before import. Import copies the text; it does not modify your original file.

Originals must cover 1 through N without gaps. An existing translation can cover any subset of those canonical numbers, including internal gaps. Known title numbers must match their filenames. If source and translation use different numbering, align them first using the advanced chapter-map/alignment tools. Index position alone is not reliable evidence of matching chapters.

Default minimum body length is 100 characters. For deliberately short chapters, set an appropriate `--min-chars` at initialization.

## Initialize

```bash
uv run litrelay init book --source originals --translation translated --source-lang zh --target-lang ru --title "Book title"
```

`init` creates `projects/book/`. `--workspace /path` selects another parent directory. Reinitialization refuses to overwrite a project. Inputs live in `input/source` and `input/translation`; accepted chapters, glossary versions and audit artifacts live in `work/`.

## Run and resume

```bash
uv run litrelay run book
uv run litrelay run book --max-chapters 5
uv run litrelay run book --dry-run
uv run litrelay status book
```

The default run fills all missing chapters in consecutive batches. A run lock prevents two runners from updating the same project. Dead-process locks can be recovered; an ambiguous lock is reported for inspection. Results and accepted chapter hashes are saved between batches.

A failed translation or QA stage stops the run with its batch path. No failed batch is accepted. Two automatic revision attempts are enabled by default. Inspect `needs-revision.txt`, QA issues and revision results. Correct the source, seed glossary, settings or prompts and rerun. Changed inputs/settings invalidate generated acceptance; the old audit files remain available.

Each existing translation chapter is trusted input after structure checks, and sampled pairs undergo semantic alignment checks before glossary extraction. It is preserved rather than rewritten by the model.

## Export

The runner exports only after every source chapter has an accepted target chapter. You can rebuild exports with:

```bash
uv run litrelay export book
```

- `book.txt`: complete target-language book in order.
- `book.epub`: EPUB 3 with navigation and a complete reading spine.
- `book.zip`: numbered target TXT chapters, TXT/EPUB books, `glossary.csv`, `report.json`.
- `report.json`: completion status, chapter provenance, hashes and generated-chapter QA scores.

Archives include no original source files, credentials or model prompts. Original content, checkpoints and generated books stay under ignored `projects/` by default.

EPUB package structure follows [EPUB 3.3](https://www.w3.org/TR/epub-33/). This implementation handles plain text books; it does not preserve source illustrations or complex layouts.
