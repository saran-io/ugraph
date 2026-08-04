# Changelog

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
