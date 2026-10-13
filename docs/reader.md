# Optional Reader CMS integration

Translation and export require no CMS. Invoke this integration only when you want to deliver a completed project to a compatible Reader REST API.

```bash
export READER_API_USER=your-user
export READER_APP_PASSWORD=your-app-password
uv run litrelay reader sync book --base-url https://reader.example/wp-json/reader/v1 --book-id 123 --audio
```

Create the destination book in your CMS first. Credentials are read from environment variables, never saved to project config or the export archive. `READER_API_PASS` is a legacy password alias.

Sync verifies chapter content, canonical order and live state, then saves a local checkpoint in `work/integrations/`. The destination may already contain the same chapters. Ambiguous/duplicate/unrelated chapter numbering stops sync. Re-running reconciles inventory and avoids duplicate creates, including a lost response after a successful POST.

When existing text changes and its audio is ready or generating, provide a separate draft archive book via `--archive-book-id`. The old chapter is backed up, moved to that archive and replaced with a new chapter ID, so stale audio is not served for updated text. Without an archive ID, that replacement is blocked.

`--audio` calls the per-chapter enqueue endpoint for every chapter needing audio. Jobs are persistent, with first chapter high priority and subsequent chapters low priority. Completion means every job is ready, generating or visibly queued; it does not mean all audio files are finished. A production delivery should also verify actual player playback, as done in the original operating workflow.

Expected endpoints: book chapters GET/POST, chapter GET/PATCH, book PATCH, `audio-status/{id}`, `audio-enqueue/{id}`. HTTPS and a User-Agent are used. A different CMS can be added as another integration without changing translation or file exports.

The older `publish-chapters` command is retained for explicit append-only operations and requires `--reader-base-url`; it does not offer resume or audio handling.
