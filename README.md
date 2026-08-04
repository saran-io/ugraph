# ugraph-kit

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
`ugraph verify` checks that **every quote is a literal substring of its transcript and every
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
uv tool install ugraph-kit          # or: pipx install ugraph-kit
brew install yt-dlp              # required for the YouTube source
```

## Quickstart

```bash
ugraph init ~/vault/04_learning              # scaffold a KB (SCHEMA.md, taxonomy, dirs)
ugraph ingest youtube https://youtube.com/@aiDotEngineer --limit 50
ugraph index                                 # regenerate navigation
ugraph lint                                  # conformance gate — must be 0 errors
ugraph status                                # what is extracted, what is pending
```

You now have transcripts and source stubs. To turn them into concepts, see
[Extraction](#extraction) — that step needs an agent, not a script.

### Connecting it to Obsidian

There is nothing to connect. An OKF bundle *is* a directory of markdown, so point
`ugraph init` at a folder inside your vault and Obsidian sees it immediately — links resolve,
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
ugraph ingest ──────────────► raw/ + sources/          deterministic, no LLM
                                │
  ┌─────────────────────────────┴───────────────────────────┐
  │  Phase A   parallel, one agent per transcript           │
  │            → candidates/<slug>.json                     │  needs an agent
  │  Phase B   SERIAL, one context                          │  harness
  │            → cluster candidates, decide create/merge     │  (Claude Code,
  │  Phase C   parallel, ONE AGENT PER CONCEPT               │   or your own)
  └─────────────────────────────┬───────────────────────────┘
                                │
ugraph index && ugraph lint && ugraph verify   ◄──── deterministic again
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
ugraph skills install                # copies skills/ into ./.claude/skills/
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
| `ugraph init PATH` | Scaffold a KB — `SCHEMA.md`, `taxonomy.json`, directories |
| `ugraph ingest youtube URL` | Fetch transcripts. Incremental and resumable |
| `ugraph index` | Regenerate every `index.md`. Deterministic; `--check` for CI |
| `ugraph lint` | Conformance gate. Links, frontmatter, reciprocity, orphans |
| `ugraph verify` | **Every quote verbatim? Every timestamp real?** |
| `ugraph status` | Extraction progress, canonicalization health |
| `ugraph graph` | Export as a graph — JSON, GraphML, DOT, Canvas, d3 |
| `ugraph ledger` | **Where is every source in its lifecycle?** |
| `ugraph skills install` | Install the agent instructions into `.claude/skills/` |

### Tracking what is done and what is stuck

```bash
ugraph ledger                 # every source and its stage
ugraph ledger --stuck 14      # pulled, unprocessed for 14+ days — the work queue
ugraph ledger --write         # markdown report into the logs directory
ugraph ledger --slug X        # when each stage happened for one source
```

Stages are the same whatever the source is: `discovered → pulled → extracted →
synthesized → linked → verified`, plus `skipped` (nothing transferable — a valid end
state) and `orphaned` (cited by concepts but never pulled, so its quotes cannot be
checked).

**State is derived from the files, never stored.** A `stage:` field in frontmatter would
be a second source of truth and would drift the first time a page was edited by hand.
Transitions are logged separately, because derivation can tell you *where* something is
but not *when* it got there.

This needs no per-source-type code. Every adapter writes the same `raw/` + `sources/`
pair, so a blog or newsletter adapter appears in the ledger the day it lands.

`ugraph status` prints a histogram of concepts by source count. Watch it: a page citing one
source is a merge candidate, three or more means canonicalization is working. If new
clusters stop producing merges, the wiki has quietly become a folder again.

---

## Do I need a graph database?

Almost certainly not, and the honest answer is worth stating because the alternative is
fashionable.

A knowledge base in this format **already is a graph** — pages are nodes, typed
relationship headings are labelled edges, and `ugraph lint` enforces bidirectionality. What
it lacks is a *query engine*. Traversal answers "what relates to X." It cannot answer
"which concepts cite only one source and appear in two clusters" without walking
everything.

So export the graph rather than becoming one:

```bash
ugraph graph --format json                       # nodes + typed edges
ugraph graph --format canvas --concepts-only \
          --out ~/vault/"Concept Graph.canvas"   # Obsidian Canvas, natively
ugraph graph --format d3 --out kb.html            # standalone interactive page
ugraph graph --format graphml --out kb.graphml    # Gephi, yEd, Neo4j import
ugraph graph --format dot --no-provenance         # Graphviz
ugraph graph --format obsidian-groups             # colour Obsidian's own graph view
```

**Obsidian Canvas is the best native target**, and better than Obsidian's graph view:
nodes are `file` nodes pointing at the real pages, so clicking one opens the note, and
edges carry the relationship name — which the built-in graph view cannot show. The canvas
must live inside the vault, since Canvas stores vault-relative paths.

`--concepts-only` matters for anything visual. Sources usually outnumber concepts several
times over, so an unfiltered picture is mostly provenance and the idea structure
disappears into it.

**Markdown stays the source of truth; the graph is derived and disposable.** Regenerating
costs milliseconds, so there is no reason to let a second system become authoritative,
drift from the files, and turn `git diff` into something you cannot read.

For scale: a KB of ~230 pages exports to roughly 64 KB. That fits in a model's context
window whole — often it is simpler to hand an agent the entire graph than to give it a
query language.

A real graph database earns its place when you have genuinely fragmented sources across
many systems, node counts in the thousands, and aggregate workloads as the *primary* use.
Below that it is infrastructure you maintain instead of using.

---

## Configuration

`ugraph.toml` beside your KB, or `--kb PATH`, or `OKF_KB`:

```toml
kb = "04_learning"
taxonomy = "taxonomy.json"
```

`taxonomy.json` holds the closed vocabulary — domains, entity subtypes, source types — and
drives how indexes group. Edit it, run `ugraph index`, done.

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
