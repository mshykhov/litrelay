# Profiles, languages and prompts

Use `litrelay profiles` to inspect built-in styles. `continuation` requires existing target chapters; `fresh` and `literary` can start from the original alone. All profiles preserve content and use the same quality gates.

```bash
uv run litrelay init book --source original.epub --source-lang en --target-lang ru --profile literary --backend claude --model <model>
```

Use BCP 47 language codes such as `zh`, `ru`, `en`, `uk`, `ja`, `de`, `fr` or `pt-BR`. Languages are included in translation, QA, revision, alignment and glossary tasks. A profile selects style; it does not force a model provider.

## Existing terminology

With a partial translation, the runner samples up to 12 pairs across the available chapters and checks semantic alignment. It extracts stable names and terms evidenced by those translations. A supplied seed glossary overrides automatic extraction. Canonical target choices survive later glossary merges; conflicting candidates are recorded for review.

Without a translation or seed, LitRelay prepares a source-based glossary before translating. The translation model proposes concise names from the first three source chapters, then the support model reviews and corrects the proposal against those same chapters. Reviewed entries with confidence at least 0.90 form the initial glossary; uncertain entries are saved for review. `bootstrap_source_chapters` in project.json controls the initial window. A supplied seed bypasses source bootstrap. Existing translations still use aligned chapter pairs.

The default sequential mode discovers new terms after each chapter and injects them into the next chapter's glossary. QA sees draft candidates before acceptance; revisions refresh those candidates. Previously translated target chapters also supply style/context.

Optionally set `preflight_glossary` to `true` in project.json to extract source terms absent from the canonical glossary before each batch and review any new proposals. This adds one support model call per batch and a second when review is needed. High-confidence terms enter a staged glossary used for translation and QA; the active glossary updates only after the batch passes QA. Chapter-specific `revise` preserves the active glossary and does not run preflight.

QA scores concern the translated chapter. Editorial concerns about canonical glossary notes or proposed entries alone are reported separately in `glossary_issues`; batch runs save them in `glossary-qa-review-needed.json`. A wrong meaning or entity in the chapter still affects its scores. This prevents a chapter translator from being asked to edit a frozen glossary.

```bash
uv run litrelay init book --source original --translation translated --glossary glossary.csv --style-file style.txt --prompts-dir examples/prompts
```

Seed CSV columns: `source,target,type,note,confidence`. For compatibility, older `target_ru` files are accepted; public exports use the neutral `target` column. Never put rejected alternatives in the canonical target field.

## Settings

Edit `projects/book/project.json` before a run. `translation` and `support` each specify `backend`, `model` and `concurrency`. Supported backends are `codex`, `claude`, `openai`. `chain: true` translates sequentially and carries newly coined terms forward; support stages can still run concurrently. Choose `chain: false` for independent parallel translation when the existing glossary/context is already stable.

Other settings: `batch_size`, `context_window`, `glossary_samples`, `revise_attempts`, `min_chars`, `qa_thresholds`. Model identifiers belong to your provider/account; LitRelay does not assume every model is available everywhere.

Set `reasoning_effort` separately inside `translation` and `support` to `low`, `medium`, `high`, `xhigh` or `max`, subject to model support. Codex CLI and OpenAI requests receive the configured effort; Claude uses its own defaults. Omit the setting to preserve the existing backend defaults (Codex: `low`). Debug stage events record the configured effort. Set these at creation with `init --reasoning-effort high --support-reasoning-effort low`. For a one-off chapter revision, `revise --reasoning-effort high` overrides only translation and repair stages without changing project settings.

## Custom prompts

At initialization, `--prompts-dir` copies any of `translation.md`, `qa.md`, `glossary.md`, `alignment.md` into the project configuration. Each replaces that stage's system prompt. `{source_language}` and `{target_language}` placeholders are expanded. Style and languages are appended to every stage; the task payload supplies the source, glossary and relevant context.

The structured output contract and deterministic checks remain in force. This allows different narration styles and languages without removing validation. Edit `style` and `prompts` in the saved config to refine them; changed settings invalidate old generated acceptance.

For chapter-specific feedback without changing the project configuration, use `litrelay revise book --chapter 7 --feedback "Clarify the dialogue"`. See [chapter revision](usage.md#revise-chapters). This feedback reaches translation, QA and repair attempts while the saved style and canonical glossary remain unchanged.
