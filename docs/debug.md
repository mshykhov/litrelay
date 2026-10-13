# Debug and telemetry

```bash
uv run litrelay run book --debug
uv run litrelay run book --log-file /path/to/events.jsonl
uv run litrelay stats book
```

Debug is opt-in and does not change translation prompts, quality gates or exports. `--log-file` implies debug. With `--dry-run`, the command only reads the current project status and creates no logs.

## Live progress

Progress is printed to stderr, leaving the final stdout JSON available for scripts. It includes input counts and selected language/profile/settings, bootstrap samples, alignment, glossary extraction/updates/reconciliation, translation, QA, revision and repeated QA. Each model stage reports its model, backend, concurrency, task count, result path, start/end time, completed/failed/skipped tasks and cache hits. Task events include ID, attempt, duration, response ID, input/output character counts, output validity and available token usage.

QA events show chapter scores and failed metrics. Accepted chapters show cumulative progress. Export events show formats and elapsed time. Every 15 seconds an active model stage prints a heartbeat with elapsed time and request/cache counts; it is a liveness message, not a completion estimate.

## Files and statistics

Default files are `projects/book/work/logs/run-<UTC timestamp>-<id>.jsonl` and the matching `.summary.json`. Events include UTC time, elapsed seconds and run ID. A custom journal appends events from multiple runs; filter by `run_id`. Summaries always stay in the project's log directory. Custom journals inside a project must be under `work/logs` so they cannot corrupt source texts or checkpoints.

The summary survives a normal failure or Ctrl-C and records `complete`, `partial`, `failed` or `interrupted`. Abrupt termination such as SIGKILL can leave only the flushed journal. `stats` returns the most recently written summary without contacting a provider.

The summary includes versions/platform, process ID, overall duration, request attempts, retry attempts, invalid outputs, failed request attempts, outer task timeouts, cache hits, model settings, QA check counts and per-stage timings/usage. QA counts include repeated checks after revision and may exceed the number of chapters. Cache hits include accepted chapters, bootstrap reuse and saved stage tasks; per-stage counts distinguish them.

## Honest usage accounting

| Field | Meaning |
|---|---|
| `tokens` | Complete totals for this run; a field is `null` if any new attempt did not report it |
| `known_tokens` | Sum of the reported values only; not a complete total when coverage is incomplete |
| `token_coverage` | Number of attempts reporting each token field |
| `usage_reported_calls`, `usage_missing_calls` | Attempts with/without both input and output usage |
| `usage_complete` | Whether every new attempt reported input and output tokens |
| `provider_reported_cost_usd` | Sum of provider-reported cost estimates, or `null` if coverage is incomplete |
| `known_provider_reported_cost_usd`, `cost_reported_calls`, `cost_complete` | Known cost subtotal and its coverage |

Codex reads usage from CLI JSONL; OpenAI reads Responses API usage. Claude uses its [JSON result metadata](https://code.claude.com/docs/en/headless#get-structured-output). Unsupported or omitted fields remain unknown. Claude's reported dollar cost is a client estimate and may differ from actual billing or subscription usage. No price table is applied to Codex or OpenAI tokens.

Input tokens include cached reads. Anthropic's separately reported cache read/write tokens are included in the normalized input count. Reasoning tokens are a subset of output tokens. These detail fields are displayed separately and never added again to total tokens. Every retry/revision is included; loading previously saved results does not add their historical usage to a new run. A run with no model attempts has zero token totals.

## Errors, timeouts and privacy

Debug records metadata, counts and QA scores. It excludes full prompts, original/translated text, raw responses, QA quotations and environment values. Error events contain a type/code rather than raw provider error bodies, which could echo private input. Detailed task errors remain in the private stage result file identified by `result_path`. Common credential patterns in metadata are also redacted. New journal/summary files use owner-only permissions on POSIX systems.

Actual CLI timeouts kill the process group, including subprocesses. Concurrent stages wait for active requests to stop before releasing the project lock and finalizing usage; they do not leave invisible workers generating after a failed run. A custom requester must impose its own I/O timeout because Python cannot forcibly stop an arbitrary function in a worker thread. An interrupted provider may not return usage; that attempt remains unknown.

The advanced executor's outer `task_timeout` is an observation deadline, not a replacement for the provider's I/O timeout. If a running request finishes late, its actual response/usage is preserved with `deadline_exceeded=true`, so a valid result is still available for resume. The deadline never cancels neighboring requests. The book runner relies directly on provider timeouts.

Inputs, batch results and logs are local under ignored `projects/` by default. An external `--workspace` or `--log-file` is managed by the caller; keep those directories private. Logs are retained until you remove them.
