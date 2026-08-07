# Changelog

## Unreleased

### Share boundary + `ugraph x`

- New outbound share surface, documented in `docs/adr/0002-share-boundary.md`.
  Knowledge commands never publish; bare `ugraph` never posts.
- `ugraph x` posts text to X after preview + confirmation (`--yes` for scripts,
  `--dry-run` for validation without network).
- `ugraph x auth set|status` stores OAuth 1.0a user-context credentials under
  `~/.config/ugraph/share/x.toml` at mode `0600` and refuses world-readable files.
- Environment overrides: `UGRAPH_X_API_KEY`, `UGRAPH_X_API_SECRET`,
  `UGRAPH_X_ACCESS_TOKEN`, `UGRAPH_X_ACCESS_TOKEN_SECRET`.
- Append-only redacted receipts in `~/.config/ugraph/share/receipts.jsonl`.

### Person capture and one-command install

- `ugraph person URL` resolves the creator behind a YouTube video, channel, or profile,
  previews the identity, and writes only after confirmation. Bare `ugraph` reads a copied
  URL and runs the same flow; `--yes` makes it scriptable.
- Person writes are idempotent. The canonical page lives under `entities/people/`;
  `resources/people/` receives a compatibility redirect, and an existing human-authored
  canonical page is never overwritten.
- The exact supplied source URL is preserved, including `?t=` timestamps. Metadata comes
  from yt-dlp rather than a model, so the command does not invent a biography.
- `yt-dlp` is now a runtime dependency. A fresh `uv tool install` no longer needs a
  separate Homebrew/pip step before YouTube commands work.
- Added the ugraph product mark, `ugraph.build` links, and a first-use person walkthrough.

### Recency selectors

`extract`, `ledger` and `status` take `--newest N`, `--since DATE` and `--channel SLUG`.
`--since` accepts `YYYY-MM-DD` or a window (`7d`, `2w`, `3m`, `1y`). `ingest` takes
`--newest N`; it has no `--since`, because YouTube's playlist listing carries no upload
dates and fetching them costs a full metadata request per video.

**Behaviour change:** `extract` now processes sources **newest-published first**. It
previously followed filesystem order, so `--limit 10` meant "ten talks whose slug happens
to start with `a`" — arbitrary, and invisible unless you checked. Pass `--dry-run` to see
the batch before committing to it.

Undated sources sort last and are excluded by `--since`. Sorting them naively put them
*first*, so `--newest 3` would return pages whose date nobody knows and call them the
most recent.

### Resume actually resumes

- Ingest state is reconciled against `youtube_id` in every transcript on each run, so a
  lost, moved or orphaned state file no longer means re-downloading the whole channel.
  Union in both directions: disk recovers a lost file, and state remembers a video whose
  transcript was deliberately deleted.
- Videos that cannot be fetched are recorded with a reason, timestamp and attempt count,
  and excluded from later runs. Previously they were never marked as tried, so they sat
  at the head of the queue permanently — a channel whose newest 25 videos lacked captions
  would retry those same 25 on every run and never advance. `--retry-failed` reconsiders
  them without erasing the history.
- `ugraph ingest --newest N` is idempotent: "make sure the newest N are held".

## 0.1.0 — unreleased

First public version. Everything below is new, so this entry describes the shape of the
tool rather than a diff.

### Commands

- `ugraph init` — scaffold a knowledge base. Interactive with no arguments: finds an
  enclosing Obsidian/Logseq/Foam vault, asks where the KB goes, which channel to ingest,
  and what will run the model. Refuses a vault root or any directory that already holds
  markdown, so it cannot scatter itself among someone's real notes.
- `ugraph ingest youtube URL` — transcripts into `raw/` + `sources/`. Incremental and
  resumable; checkpoints after every video.
- `ugraph extract` — optional Phase A via Ollama or an API key. Every quote is checked
  against the transcript before it is written.
- `ugraph index` — regenerate navigation. Deterministic; `--check` for CI.
- `ugraph lint` — conformance gate: links, frontmatter, reciprocity, orphans.
- `ugraph verify` — every quote a literal substring of its transcript, every timestamp
  real.
- `ugraph status` — extraction progress and canonicalization health.
- `ugraph ledger` — per-source lifecycle, derived from the files rather than stored.
- `ugraph graph` — JSON, GraphML, DOT, Obsidian Canvas, d3.
- `ugraph skills install` — the agent instructions for the extraction pass.

Every command takes `--json`. That output is the API a UI will be built on, and CI
asserts it stays parseable.

### Notes

- Requires Python 3.10+. `python-frontmatter` imports `typing.TypeGuard`, so 3.9 does not
  work despite what an earlier `requires-python` claimed.
- Three runtime dependencies. Model backends are an optional `[api]` extra; the
  deterministic core calls no model and needs no key.
- Exercised on ~150 talks across two channels: 57 concepts, 385 pages, lint clean.
