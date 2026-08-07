<p align="center">
  <a href="https://ugraph.build">
    <img src="https://raw.githubusercontent.com/saran-io/ugraph/main/docs/assets/ugraph-logo.svg"
         width="132" alt="ugraph logo">
  </a>
</p>

<h1 align="center">ugraph</h1>

<p align="center">
  <strong>Build verifiable knowledge from the sources you trust.</strong><br>
  YouTube sources → plain Markdown → an agent-navigable graph with citations.
</p>

<p align="center">
  <a href="https://ugraph.build">Website</a> ·
  <a href="#install">Install</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#does-the-check-actually-catch-anything">Evidence</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10–3.13-3776AB" alt="Python 3.10 to 3.13">
  <img src="https://img.shields.io/badge/status-alpha-D97706" alt="Alpha status">
  <a href="https://github.com/saran-io/ugraph/actions/workflows/ci.yml">
    <img src="https://github.com/saran-io/ugraph/actions/workflows/ci.yml/badge.svg" alt="CI status">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-22A447" alt="MIT license">
  </a>
</p>

Plain markdown, YAML frontmatter, relative links. **No database, no embeddings, no vector
store.** An agent reads `index.md`, follows links to the pages it needs, and answers with
a citation that points at a timestamp in an immutable transcript.

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
```

That is the whole install. `yt-dlp`, used for deterministic YouTube metadata and
transcripts, is included as a runtime dependency.

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

### Save a person from any YouTube link

Copy a video, channel, or profile URL and run:

```bash
ugraph
```

ugraph resolves the creator, previews exactly what it found, and asks before writing:

```text
Detected: Kun Chen (@kunchenguid)
  profile: https://www.youtube.com/channel/...
  source:  L8 Principal Building a Full Stack App with Agentic Engineering
Add this person to your knowledge base? [Y/n]
```

It creates one canonical record under `entities/people/` and a compatibility redirect
under `resources/people/`. Repeating the command does not duplicate the person or
overwrite human-written content.

The explicit and automation-friendly forms are:

```bash
ugraph person "https://www.youtube.com/watch?v=..."
ugraph person "https://www.youtube.com/watch?v=..." --yes
```

No model or API key is involved. Identity metadata comes directly from YouTube through
`yt-dlp`; ugraph does not invent a biography.

### Share to X (outbound only)

Posting is a separate boundary from knowledge capture — see
[`docs/adr/0002-share-boundary.md`](docs/adr/0002-share-boundary.md). Bare `ugraph`
never tweets.

```bash
# one-time: store Read+Write user tokens from the X developer portal (mode 0600)
ugraph x auth set
ugraph x auth status

# copy text, then:
ugraph x                 # preview → confirm → publish
ugraph x "hello world"   # explicit text
ugraph x --dry-run "…"   # validate only, no network
ugraph x --yes "…"       # skip confirm (scripts / CI)
```

Credentials live in `~/.config/ugraph/share/` — never inside the Obsidian vault.
Successful posts append a redacted receipt (post id + URL, no secrets).

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

**Why a 7B model is safe here.** Every quote is checked against the transcript before
anything is written. A quote that is not a literal substring is rejected outright; a
timestamp is not trusted at all but recomputed from the paragraph the quote actually sits
in. A model that paraphrases gets caught by a substring test rather than believed, the
transcript is retried, and a model that fails three times is the wrong model.

**What a local model is actually like.** Set expectations low and the gate does the rest.
On an 8 GB M-series Mac, `qwen2.5-coder:7b` over two ~12-minute talks produced 12 candidate
concepts across runs and **the gate threw away 8–9 of them** as non-verbatim. The 3–4 that
survive are genuinely quoted, correctly timestamped, and pass `ugraph verify` unedited.
Budget roughly 5–10 minutes per talk.

That two-thirds rejection rate is the system working, not failing — but it means local
extraction is a way to make progress on a backlog cheaply, not a way to get the same
result as a strong model for free. It finds fewer concepts and needs more passes.

> **If you are on Ollama, know this:** it silently caps every request at a 4096-token
> context no matter what the model supports, truncating the prompt from the front rather
> than erroring. That drops the schema first, and the model then answers in a format it
> invented — which parses cleanly and contains nothing. `ugraph` sizes `num_ctx` to the
> prompt and constrains the output schema to avoid this. If you drive Ollama yourself,
> set `num_ctx` explicitly.

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

### Choosing what to work on

`extract`, `ledger` and `status` take the same three selectors, and everything is
ordered **most recently published first**:

```bash
ugraph extract --newest 10           # the 10 most recent talks
ugraph extract --since 2w            # published in the last fortnight
ugraph extract --channel ai-engineer --newest 5
ugraph extract --newest 20 --limit 5 # of the 20 most recent, do 5
ugraph extract --newest 10 --dry-run # see the batch before spending an hour on it
```

`--since` takes `YYYY-MM-DD` or a window (`7d`, `2w`, `3m`, `1y`). `--limit` bounds the
*work*; the selectors bound the *window*, and `--limit` applies last.

Sources with no publication date sort **last** and are excluded by `--since`. A page
that cannot prove it falls inside a window is not in that window — otherwise undated
pages sort to the top and get returned as "the newest", which is exactly the bug that
made this worth writing down.

**On the ingest side, `--newest` and `--limit` mean different things:**

```bash
ugraph ingest youtube URL --newest 10   # make sure the 10 most recent are held
ugraph ingest youtube URL --limit 10    # fetch 10 I don't have yet (backfill)
```

`--newest` is idempotent: run it twice and the second run fetches nothing. There is no
`--since` for ingest — YouTube's playlist listing returns no upload dates, so a date
filter would need a full metadata fetch per video, which is most of the cost of
ingesting anyway.
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

The one exception is which videos have been *seen*, which no file can tell you — a video
whose captions were unavailable leaves nothing behind. That lives in
`.ugraph/state/youtube.json`, and it is a **cache, not the authority**: every run
reconciles it against the `youtube_id` in each transcript, so a deleted, moved or
orphaned state file heals itself instead of triggering a full re-download. Videos that
can never be fetched are recorded with a reason and a count, so they stop consuming a
slot in every future batch — without that, a channel whose newest videos lack captions
makes `--limit 25` retry the same 25 forever.

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
