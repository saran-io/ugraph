# Contributing

```bash
git clone https://github.com/saran-io/ugraph && cd ugraph
uv venv && uv pip install -e ".[dev]"
uv run pytest && uv run ruff check src/ tests/
```

That is the whole setup. Tests take under a second and touch no network.

## What this project is

A knowledge-base builder and validator. It turns source material into plain markdown
with citations that can be mechanically checked against an immutable transcript.

The format is the [Open Knowledge Format](https://github.com/coleam00/cole-medin-knowledge-base),
originated by Cole Medin. This is an independent implementation; divergences are marked
**OKF-v** in `templates/SCHEMA.md`.

## Two things worth understanding before changing anything

**Markdown is the source of truth.** Not a database, not an index, not a cache. Anything
that wants to become authoritative — a graph store, a `stage:` field in frontmatter, an
embedding index — will drift from the files the first time somebody edits a page by hand,
and people edit these pages by hand constantly. Derive instead. `ugraph ledger` and
`ugraph graph` are both derived views and must stay that way.

**Canonicalization is the whole value.** The pipeline exists to turn ten talks about one
idea into *one page citing ten sources*. A change that makes it easier to produce one page
per source has broken the tool, however green the tests are.

## Architecture

```
ugraph ingest ──────────► raw/ + sources/          deterministic, no LLM
                               │
   Phase A   parallel, one agent per source  → candidates/*.json
   Phase B   SERIAL, one context             → decide create / merge / embed
   Phase C   parallel, ONE AGENT PER CONCEPT → write pages
                               │
ugraph index && lint && verify   ◄──────────  deterministic again
```

Phase C parallelizes **by concept, never by source**. Twenty agents each reading a
different talk will each independently create `context-engineering.md`.

`src/ugraph/` is a thin CLI over a library: `cli.py` resolves a `Config`, calls one
library function, formats the result. Logic in `cli.py` cannot be tested or reused, so it
does not live there.

## Adding a source adapter

The highest-value contribution. Any adapter that writes the same two files inherits
`lint`, `verify`, `ledger`, `graph`, and `status` with no further work:

```
raw/<channel>/<slug>.md        immutable, with provenance frontmatter
sources/<channel>/<slug>.md    a source page, summary_status: pending
```

Follow `src/ugraph/sources/youtube.py`. Take a `Config`, take a `progress` callback
rather than printing, and checkpoint state after **every** item — a write is cheap, a
re-download is not.

RSS is the most wanted one.

## Tests

No mocks. Tests build a real KB on disk and assert the gates fire. A mocked linter test
proves the mock works.

Some tests exist because something went wrong, and their docstrings say what. Do not
delete those without reading them — for instance, one bad file must never truncate a lint
run, because a gate that fails open is worse than no gate.

## Before opening a PR

```bash
uv run pytest
uv run ruff check src/ tests/
uv build && tar -tzf dist/*.tar.gz | grep -c venv    # must print 0
```

That last line is not paranoia. The sdist once shipped a 613-file virtualenv containing an
absolute symlink, which made `pip install git+...` fail while the wheel installed fine.
CI runs the real install from both artifacts for exactly that reason.

## Style

Comments explain *why*, not *what*. If a rule exists because something broke, say what
broke — those are the comments worth reading a year later.
