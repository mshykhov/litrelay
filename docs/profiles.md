# Profiles, languages and prompts

Use `litrelay profiles` to inspect built-in styles. `continuation` requires existing target chapters; `fresh` and `literary` can start from the original alone. All profiles preserve content and use the same quality gates.

```bash
uv run litrelay init book --source original.epub --source-lang en --target-lang ru --profile literary --backend claude --model <model>
```

Use BCP 47 language codes such as `zh`, `ru`, `en`, `uk`, `ja`, `de`, `fr` or `pt-BR`. Languages are included in translation, QA, revision, alignment and glossary tasks. A profile selects style; it does not force a model provider.

## Existing terminology

With a partial translation, the runner samples up to 12 pairs across the available chapters and checks semantic alignment. It extracts stable names and terms evidenced by those translations. A supplied seed glossary overrides automatic extraction. Canonical target choices survive later glossary merges; conflicting candidates are recorded for review.

Without a translation, the glossary starts empty (or from your seed). The default sequential mode discovers new terms after each chapter and injects them into the next chapter's glossary. Previously translated target chapters also supply style/context.

```bash
uv run litrelay init book --source original --translation translated --glossary glossary.csv --style-file style.txt --prompts-dir examples/prompts
```

Seed CSV columns: `source,target,type,note,confidence`. For compatibility, older `target_ru` files are accepted; public exports use the neutral `target` column. Never put rejected alternatives in the canonical target field.

## Settings

Edit `projects/book/project.json` before a run. `translation` and `support` each specify `backend`, `model` and `concurrency`. Supported backends are `codex`, `claude`, `openai`. `chain: true` translates sequentially and carries newly coined terms forward; support stages can still run concurrently. Choose `chain: false` for independent parallel translation when the existing glossary/context is already stable.

Other settings: `batch_size`, `context_window`, `glossary_samples`, `revise_attempts`, `min_chars`, `qa_thresholds`. Model identifiers belong to your provider/account; LitRelay does not assume every model is available everywhere.

## Custom prompts

At initialization, `--prompts-dir` copies any of `translation.md`, `qa.md`, `glossary.md`, `alignment.md` into the project configuration. Each replaces that stage's system prompt. `{source_language}` and `{target_language}` placeholders are expanded. Style and languages are appended to every stage; the task payload supplies the source, glossary and relevant context.

The structured output contract and deterministic checks remain in force. This allows different narration styles and languages without removing validation. Edit `style` and `prompts` in the saved config to refine them; changed settings invalidate old generated acceptance.
