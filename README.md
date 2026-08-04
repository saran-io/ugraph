# okf-kit

Turn a YouTube channel into a knowledge base an AI agent can actually navigate — and cite.

Plain markdown, YAML frontmatter, relative links. **No database, no embeddings, no vector
store.** An agent reads `index.md`, follows links to the three pages it needs, and answers
with a citation that points at a timestamp in an immutable transcript.

```
concepts/llm-as-a-judge.md
  → cites 5 talks, each "(title @ 00:14:32)"
    → sources/ai-engineer/build-evals-that-actually-matter.md
      → raw/ai-engineer/build-evals-that-actually-matter.md  ← the exact words, verbatim
```

Because a knowledge base is only worth as much as your willingness to trust it,
`okf verify` checks that **every quote is a literal substring of its transcript and every
timestamp is real**. That check is the point. Everything else is plumbing.

---

## What this is not

It does not summarize videos. One page per video is a folder of summaries, not a wiki.

It builds **concepts synthesized across every source that taught them**. Ten talks
mentioning context engineering produce *one* page citing ten sources. That merge is the
entire value, and it is also the hard part — see [Architecture](#architecture).

---

## Install

```bash
uv tool install okf-kit          # or: pipx install okf-kit
brew install yt-dlp              # required for the YouTube source
```

## Quickstart

```bash
okf init ~/vault/04_learning              # scaffold a KB (SCHEMA.md, taxonomy, dirs)
okf ingest youtube https://youtube.com/@aiDotEngineer --limit 50
okf index                                 # regenerate navigation
okf lint                                  # conformance gate — must be 0 errors
okf status                                # what is extracted, what is pending
```

You now have transcripts and source stubs. To turn them into concepts, see
[Extraction](#extraction) — that step needs an agent, not a script.

### Connecting it to Obsidian

There is nothing to connect. An OKF bundle *is* a directory of markdown, so point
`okf init` at a folder inside your vault and Obsidian sees it immediately — links resolve,
backlinks work, the graph view shows the concept cluster.

The one setting worth changing: add `raw/` to **Settings → Files & Links → Excluded files**.
Transcripts are the audit trail, not reading material, and they will otherwise dominate
search results.

Notion is not supported yet. It is a real adapter rather than a no-op, and it fights the
format — relative links and no-database is the premise, not an implementation detail.

---

## Architecture

Ingestion is a script. Extraction is not, and pretending otherwise is where this kind of
tool usually goes wrong.

```
okf ingest ──────────────► raw/ + sources/          deterministic, no LLM
                                │
  ┌─────────────────────────────┴───────────────────────────┐
  │  Phase A   parallel, one agent per transcript           │
  │            → candidates/<slug>.json                     │  needs an agent
  │  Phase B   SERIAL, one context                          │  harness
  │            → cluster candidates, decide create/merge     │  (Claude Code,
  │  Phase C   parallel, ONE AGENT PER CONCEPT               │   or your own)
  └─────────────────────────────┬───────────────────────────┘
                                │
okf index && okf lint && okf verify   ◄──── deterministic again
```

**Why the phases split this way.** Canonicalization needs a global view — you cannot know
whether "context rot" deserves its own page until you have seen every transcript that
mentions it. But a large corpus does not fit in one context alongside page-writing.

So Phase A extracts *only candidates* (a few KB per transcript, so all of them fit at
once), Phase B decides globally, and Phase C writes. **Phase C parallelizes by concept,
never by transcript** — that is what makes duplicate pages structurally impossible. Twenty
agents each reading a different talk will each independently create
`context-engineering.md`.

Phase A emits verbatim quotes with timestamps, so Phase C writes cited pages without
re-reading transcripts. Cost stays near 1× the corpus instead of 3×.

## Extraction

The agent instructions ship with the package:

```bash
okf skills install                # copies skills/ into ./.claude/skills/
```

Then in Claude Code: `/channel-to-kb`. The skill covers batch selection, the
create-vs-merge threshold, and the citation format. `skills/references/candidate-extraction.md`
is the Phase A spec — read it before pointing any other harness at this.

It is written for Claude Code because that is what it was built and tested against. The
specs are plain markdown and carry no Claude-specific syntax, so adapting them to another
agent runner is a prompt-plumbing exercise, not a rewrite.

---

## Commands

| | |
|---|---|
| `okf init PATH` | Scaffold a KB — `SCHEMA.md`, `taxonomy.json`, directories |
| `okf ingest youtube URL` | Fetch transcripts. Incremental and resumable |
| `okf index` | Regenerate every `index.md`. Deterministic; `--check` for CI |
| `okf lint` | Conformance gate. Links, frontmatter, reciprocity, orphans |
| `okf verify` | **Every quote verbatim? Every timestamp real?** |
| `okf status` | Extraction progress, canonicalization health |
| `okf skills install` | Install the agent instructions into `.claude/skills/` |

`okf status` prints a histogram of concepts by source count. Watch it: a page citing one
source is a merge candidate, three or more means canonicalization is working. If new
clusters stop producing merges, the wiki has quietly become a folder again.

---

## Configuration

`okf.toml` beside your KB, or `--kb PATH`, or `OKF_KB`:

```toml
kb = "04_learning"
taxonomy = "taxonomy.json"
```

`taxonomy.json` holds the closed vocabulary — domains, entity subtypes, source types — and
drives how indexes group. Edit it, run `okf index`, done.

---

## Status

**Alpha.** Built and exercised on a single channel: ~150 talks, 57 concepts, 385 pages,
lint clean. It has not been run against a second channel, and the demo-to-product gap is
real — expect the first unfamiliar corpus to find something.

Known limits, all measured rather than guessed:

- `concepts/index.md` grows linearly with concept count (~9 KB at 57). On small-context
  models this becomes the bottleneck before your content does. Per-domain index splitting
  is the fix, and it is not written yet.
- There is no contradiction detection. Two pages can assert opposite things and nothing
  will notice.
- Maps of content drift. If you hand-curate `_mocs/`, expect to re-check them.

## Credit

The Open Knowledge Format is **[Cole Medin](https://github.com/coleam00)**'s — see
[cole-medin-knowledge-base](https://github.com/coleam00/cole-medin-knowledge-base), which
is both the specification and a substantial reference bundle. This project is an
independent implementation of that idea as a reusable tool.

It diverges in a few places, marked **OKF-v** in `SCHEMA.md`: multi-channel support, a
`confidence` field, source affiliation labelling, and the two-phase extraction split. The
navigation model — traverse relative links from an index, load only what you need — comes
from [Karpathy's LLM wiki pattern](https://karpathy.bearblog.dev/).

MIT.
