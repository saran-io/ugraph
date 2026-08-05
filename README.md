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

## The structure

Seven directories. That is the whole format, and it is deliberately something you could
have created by hand:

```
knowledge/
├── index.md          the entry point — an agent starts here and follows links
├── concepts/         ideas, synthesized across every source that taught them
├── entities/         the people, companies and tools those ideas belong to
├── sources/          one page per talk: what it covered, what it contributed
├── raw/              transcripts. Immutable. Never edited, never hand-written
├── _mocs/            hand-curated maps of content, when you want a reading order
├── SCHEMA.md         the rules, in the repo, readable by you and by an agent
└── taxonomy.json     your closed vocabulary — domains, source types, subtypes
```

A page is markdown with frontmatter and typed relationship headings:

```markdown
---
type: concept
domain: ai_engineering
confidence: high
---

# LLM as a judge

Use a model to grade output that code cannot check. Lyft's deterministic criteria
"usually looks like a code assertion, as you see in traditional unit test"
([Build Evals That Actually Matter](../sources/ai-engineer/build-evals.md) @ 00:10:24).

## Prerequisites
- [error analysis loop](error-analysis-loop.md)

## Contrasts with
- [offline and online evals](offline-and-online-evals.md)

## Sources
- [Build Evals That Actually Matter](../sources/ai-engineer/build-evals.md)
```

Those headings are the graph. `## Prerequisites` is a labelled edge, `ugraph lint`
enforces that it points somewhere real and that the other page points back, and
`ugraph graph` exports the whole thing to Canvas, GraphML, DOT, d3 or JSON without any
of it ever having lived in a database.

**Why this and not a vector store.** You can read it. You can `git diff` it. You can
grep it, edit a page by hand at 2am, and nothing needs re-indexing. When an agent cites
something you can click the citation and land on the sentence. A ~230-page base exports
to about 64 KB of JSON — small enough to hand a model the entire graph instead of
teaching it a query language.

---

## Install

```bash
uv tool install git+https://github.com/saran-io/ugraph
# or: pipx install git+https://github.com/saran-io/ugraph
brew install yt-dlp   # or: uv tool install yt-dlp / pipx install yt-dlp
```

## Quickstart

```bash
cd ~/MyVault      # or anywhere; a knowledge base is just a folder
ugraph init       # asks three questions, writes ugraph.toml, scaffolds
```

`init` with no arguments is interactive. It looks for an enclosing vault, asks where the
KB should live, which channel to ingest, and what will run the model — then prints the
exact next commands for the answers you gave. Every question is also a flag, so
`ugraph init knowledge` still works and CI never sees a prompt.

Then:

```bash
ugraph ingest youtube https://youtube.com/@SomeChannel --limit 50
ugraph index                                 # regenerate navigation
ugraph lint                                  # conformance gate — must be 0 errors
ugraph status                                # what is extracted, what is pending
```

You now have transcripts and source stubs. To turn them into concepts, see
[Extraction](#extraction) — that step needs a model, and you choose which one.

### Using it with your notes app

There is nothing to connect. A knowledge base here *is* a directory of markdown files
with relative links, so anything that reads a folder of markdown sees it immediately —
links resolve, backlinks work, graph views show the concept cluster.

| | |
|---|---|
| **Obsidian** | Works today. `init` detects `.obsidian` and offers the vault as the base |
| **Logseq**, **Foam** | Same — detected by `.logseq` / `.foam`, no configuration |
| **Plain git / VS Code / anything** | Works. There is no vault requirement at all |
| **Notion** | Not supported. Needs a real adapter — see below |

```bash
cd ~/MyVault            # your existing vault, with all your notes
ugraph init             # the KB gets its own folder inside it
ugraph ingest youtube https://youtube.com/@SomeChannel --limit 25
ugraph lint
```

**Give it its own folder.** Not the vault root — the knowledge base has a strict schema,
and `ugraph lint` would report every note you already have as a malformed page. `init`
refuses a vault root or any directory that already holds markdown, and tells you what to
run instead. Your existing notes are never read, never linted, never touched.

`ugraph.toml` lands in the vault root, so every command works from anywhere inside the
vault with no flags.

For Obsidian, one setting is worth changing: add `raw/` to **Settings → Files & Links →
Excluded files**. Transcripts are the audit trail, not reading material, and they will
otherwise dominate search results.

Notion is the one case that needs code rather than a folder. Its pages are rows in a
database behind an API, so relative links, `git diff`, and grep — the whole premise — do
not survive the trip. A sync adapter is possible and is not written; the format stays
markdown-first either way.

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

**ugraph itself never calls a model.** No API key is required to install it, and nothing
phones home. Ingesting, indexing, linting, verifying, the ledger and the graph are all
deterministic Python over your files. Turning transcripts into concepts is the one step
that needs a model, and you pick which:

| Backend | What it costs | What it can do |
|---|---|---|
| `claude-code` | You already have it | Every phase, best quality — this is the default |
| `api` | Your Anthropic or OpenAI key | Phase A; needs `pip install 'ugraph-kit[api]'` |
| `ollama` | Nothing. Local and private | Phase A only |

### With Claude Code

```bash
ugraph skills install                # copies skills/ into ./.claude/skills/
```

Then in Claude Code: `/channel-to-kb`. The skill covers batch selection, the
create-vs-merge threshold, and the citation format. `skills/channel-to-kb/references/candidate-extraction.md`
is the Phase A spec — read it before pointing any other harness at this. The specs are
plain markdown with no Claude-specific syntax, so adapting them to another agent runner is
prompt plumbing, not a rewrite.

### With a local model or an API key

```bash
ollama pull qwen2.5-coder:7b
ugraph extract --backend ollama --limit 10     # or: --backend api
```

This runs **Phase A only** — one transcript at a time, out to candidate JSON.

**Why a 7B model is safe here.** Every quote a model returns is checked against the
transcript before anything is written: a quote that is not a literal substring is
rejected, and so is a timestamp the transcript does not contain. A model that paraphrases
gets caught by a substring test rather than trusted. Rejected concepts are dropped and the
transcript is retried; a model that fails three times is the wrong model. Measured on this
machine: `qwen2.5-coder:7b` extracted 5 concepts from one 45-minute talk in about 7
minutes, all verbatim, none rejected.

**Why Phase B is not offered locally.** Deciding that ten candidates are one concept needs
every candidate in view at once, and there is no mechanical check for getting it wrong.
`ugraph verify` catches a fabricated quote; nothing catches bad judgement. That step wants
a strong model and a human looking at the result — so `ugraph extract` does not pretend to
do it.

---

## Does the check actually catch anything?

Yes, and the most useful evidence is that it caught things in *my own* knowledge base —
the one I built by hand and had read several times.

Running `ugraph verify` over 385 pages found 11 defects. Ten were the small ways a quote
quietly stops being a quote: an editor writing `because` where the speaker said `cuz`,
`self-harm` where the captions read `self harm`, `[OpenTelemetry]` expanded in place over
a garbled acronym, two fragments stitched across an elision, a period the speaker never
paused for.

The eleventh was a sentence nobody said. A concept page attributed *"if this interaction
should grant a concession, did it?"* to a Lyft talk. The word "concession" is in that
transcript. That sentence is not — it was a cleaned-up paraphrase wearing quotation marks.

Every one of those was invisible to reading, and each one had been read. Tidying a
machine transcript is a reasonable thing for an editor to do, and it is still how a
speaker ends up on record saying something they did not say. That is the whole argument
for a mechanical check: not that you are careless, but that this particular error is
undetectable by care.

(One of the 11 turned out to be the checker's fault — it blamed a citation for the quote
next door. That got fixed too. A gate people learn to argue with is a gate they ignore.)

---

## Commands

| | |
|---|---|
| `ugraph init [PATH]` | Scaffold a KB. Interactive with no arguments |
| `ugraph ingest youtube URL` | Fetch transcripts. Incremental and resumable |
| `ugraph extract` | Phase A via a local or API model, behind the verbatim gate |
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

`ugraph.toml` beside your KB, or `--kb PATH`, or `UGRAPH_KB`:

```toml
kb = "knowledge"
taxonomy = "taxonomy.json"

[extract]                        # optional; written by `ugraph init`
backend = "ollama"               # claude-code | api | ollama
model = "qwen2.5-coder:7b"
```

`taxonomy.json` holds the closed vocabulary — domains, entity subtypes, source types — and
drives how indexes group. Edit it, run `ugraph index`, done.

---

## Status

**Alpha.** Built and exercised on ~150 talks: 57 concepts, 385 pages, `lint` clean and
`verify` clean. The demo-to-product gap is real — expect the first unfamiliar corpus to
find something.

Known limits, all measured rather than guessed:

- **Nobody has benchmarked whether it answers questions better than a bare model.** The
  format is designed for agent traversal and the citations are real, but "an agent
  navigates this well" is currently a design intention, not a published finding. If that
  matters to you, treat it as unproven.
- YouTube is the only source adapter so far. The contract is small — write `raw/` +
  `sources/` and you inherit `lint`, `verify`, `ledger` and `graph` — and RSS is the
  most wanted next one.

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
