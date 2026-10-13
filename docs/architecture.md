# Architecture and development

The project runner orchestrates reusable translation/glossary utilities. It reads local prepared text and writes local artifacts. Provider calls are confined to agent backends; external delivery is confined to `integrations/`.

| Module | Responsibility |
|---|---|
| `project_cli`, `project_config` | small public workflow and saved settings |
| `project_workflow`, `project_storage` | bootstrap, missing chapters, hashes, lock, resume |
| `book_inputs`, `book_export` | text/EPUB input and TXT/EPUB/ZIP output |
| `prompt_profiles` | language/style/template adaptation across all LLM stages |
| `batch_pipeline`, `revision`, `qa_gate` | translation, complete QA coverage, revision, acceptance |
| `glossary_*` | evidence extraction, canonical choices, versioning, review |
| `agent_executor`, `agent_backends` | structured calls, concurrency, retries, process timeout |
| `telemetry` | optional live progress, safe metadata journal and per-run usage accounting |
| `integrations/reader*` | optional CMS sync and audio queue |

## Contracts

- A failed or missing QA result blocks the whole batch before export/publishing.
- Chapter IDs from model output must be numeric and agree with task IDs.
- Continuation chains start with existing target context, then include prior generated chapters.
- Deterministic guards participate in revision: wrong numbering, short bodies and Chinese residue in configured non-CJK targets cannot pass on high model scores alone.
- Accepted provenance stores the exact full source hash, output hash, configuration fingerprint and QA scores. Cache reuse requires the current inputs and output to match.
- Only a complete accepted book is packaged. Supplied target chapters remain trusted input, with sampled alignment rather than full editorial QA.
- Seed/canonical glossary versions are preserved; proposed conflicts do not silently rename established entities.
- Reader POST creates a chapter. Unknown outcomes are reconciled from inventory, and repeated sync verifies existing content. Cached/generating audio requires explicit archival before text replacement. Per-chapter audio jobs use no temporary TTL.
- Telemetry counts each new request attempt, including rejected outputs and revisions; saved results are cache hits, with no new token spend. Incomplete token/cost totals are null, with known subtotals and coverage kept separately.
- Provider timeouts bound the actual subprocess/HTTP operation. CLI cancellation kills the process group; concurrent stages wait for active workers before releasing the project lock and closing telemetry. A custom requester must provide its own bounded I/O timeout.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
uv build
```

Tests use fake model/API responses and self-authored short fixtures; CI does not call paid APIs or a production CMS. Existing preparation/repair utilities and their regression tests are preserved. See `litrelay --help` and `<command> --help` for advanced tools, including alignment, glossary curation, source splitting and RanobeLib downloads.

The `novel-translation` executable remains a compatibility alias. Legacy `run-batch` has its earlier default score thresholds; the project runner uses the stronger 90/85/75/95 defaults. Legacy `publish-chapters` is append-only; use `reader sync` for repeatable delivery.

The old experiments and private production scripts remain in the original knowledge repository. They are not runtime dependencies or bundled source material.
