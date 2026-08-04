---
type: overview
title: "Knowledge Base Schema (OKF)"
description: "Page types, frontmatter contracts, typed relationships, linking rules, and citation format for this knowledge base."
---

# Knowledge Base Schema

This is the machine-readable contract for everything in this directory. Plain markdown,
YAML frontmatter, navigated by `index.md` and relative links. No database, no embeddings.

**Read this before writing to the knowledge base.** `okf lint` enforces the structural
half of it and `okf verify` enforces the citation half. Neither one checks whether what
you wrote is *true* — that part is on you, and the rules below exist to make it
checkable by someone who does not trust you.

This is an independent implementation of Cole Medin's
[Open Knowledge Format](https://github.com/coleam00/cole-medin-knowledge-base) (OKF v0.1).
The format is his; the extensions below are not, and are marked **OKF-v** where it matters.

## Where the knowledge base lives

Wherever you put it. `okf init PATH` scaffolds one, and every command resolves the root
from `--kb PATH`, then `$OKF_KB`, then the `kb` key in the nearest `okf.toml`, then the
current directory if it looks like a knowledge base.

A KB is a directory of markdown files. It can sit inside an Obsidian vault, a git repo,
or nowhere in particular. Nothing in this schema depends on which.

## How this extends OKF

| Extension | What it adds | Why |
|---|---|---|
| Multi-source | `channel` on source pages; sources live at `sources/<channel>/<slug>.md` | Upstream assumes one YouTube channel. A concept is only worth canonicalizing if it survives contact with more than one speaker, so the format has to hold several channels — and papers, articles, and your own notes — at once. |
| `confidence` | `high` \| `medium` \| `low` on any page | Some claims rest on production numbers at scale; some rest on one person's home lab or a single demo. Without a field for that, the two look identical on the page and get cited identically. |
| Source affiliation | `affiliation` on source pages: `independent` \| `vendor` \| `buyer` | "This tool cuts latency 40%" means one thing in a vendor's talk and another in an account from someone who paid for it. The distinction is invisible once a claim has been lifted into a concept page, so it is recorded at the source. |
| `summary_status` | `pending` \| `done` on source pages | Ingestion is a script and extraction is an agent pass; they run at different rates and on different days. This field is the join between them, and it is what `okf status` counts. |
| Strict-tree link rule | Relative markdown links required under `concepts/`, `entities/`, `sources/`, `_mocs/`; `[[wikilinks]]` tolerated elsewhere in the KB | A wikilink only resolves inside the tool that invented it. The format's premise is that a filesystem is enough to follow an edge. Outside the strict tree — trackers, reading lists, human scratch notes — nothing traverses the links but a person in an editor, so wikilinks there are a warning, not an error. |

## Directory layout

```
<kb-root>/
├── index.md                    # entry point — every agent starts here (generated)
├── SCHEMA.md                   # this file
├── taxonomy.json               # the closed vocabularies — yours to edit
├── concepts/                   # ideas, techniques, patterns  (flat, no subfolders)
│   └── index.md
├── entities/                   # things that exist in the world
│   ├── index.md
│   ├── tools/
│   ├── people/
│   └── organizations/
├── sources/                    # one page per consumed artifact, under <channel>/
│   └── index.md
├── raw/                        # immutable transcripts — the audit trail
└── _mocs/                      # optional, hand-curated maps of content
```

`concepts/` is **flat on purpose.** Subject grouping lives in the `domain` field and is
rendered into `concepts/index.md` headings by `okf index`. Flat paths keep link targets
stable when a note's domain is reclassified — otherwise every reclassification is a file
move, and every file move breaks inbound links.

`_mocs/` is not created by `okf init`. Make it if you want curated narrative overviews;
the root index picks up its direct children automatically.

Phase A extraction candidates are written to `.okf/candidates/` **outside** the KB root.
They are working files, not knowledge, and must not be linted or indexed as pages.

## Page types

All dates are ISO `YYYY-MM-DD`. Every `.md` file in the KB must have frontmatter with a
non-empty `type`, except the three reserved names — `index.md`, `README.md`, `SCHEMA.md` —
which the linter skips. An unrecognized `type` is an error, not a shrug.

Fields not listed here are allowed and ignored. The linter checks that required fields are
present and that closed vocabularies are respected; it does not reject extra keys.

### `concept`

**Location:** `concepts/<id>.md`

```yaml
---
type: concept
title: "The PIV Loop"
description: "Plan-Implement-Verify cycle for driving coding agents without losing control."
domain: agentic_systems       # must be a key in taxonomy.json
status: growing               # seed | growing | evergreen
tags: [workflow, planning]
sources: [cole-medin/piv-loop-explained, ai-engineer/software-3-0]
confidence: high              # optional: high | medium | low
created: 2026-07-21
updated: 2026-08-03
---
```

| Field | Req | Notes |
|---|---|---|
| `type` | yes | literal `concept` |
| `title` | yes | human display name |
| `description` | yes | **one sentence**, reused verbatim in `index.md` |
| `domain` | yes | a key in `taxonomy.json` — drives index grouping |
| `status` | yes | `seed` \| `growing` \| `evergreen` |
| `created` / `updated` | yes | ISO date |
| `sources` | — | source slugs (`<channel>/<slug>`) that taught this |
| `tags` | — | free-form |
| `confidence` | — | `high` \| `medium` \| `low` — flag for claims resting on weak evidence |

`sources` is what `okf status` counts. A concept with one source is a merge candidate —
usually the same idea already living under another name. Three or more means
canonicalization is working.

### `entity`

**Location:** `entities/{tools,people,organizations}/<id>.md`

```yaml
---
type: entity
subtype: person               # tool | person | organization
title: "Andrej Karpathy"
description: "Founding member of OpenAI; coined Software 2.0/3.0 and context engineering."
resource: https://karpathy.ai
domain: ai_engineering
tags: [research, education]
sources: [ai-engineer/software-3-0-talk]
created: 2026-04-03
updated: 2026-08-03
---
```

Required: `type`, `subtype`, `title`, `description`, `created`, `updated`.
`status` is not required for entities. `domain` is optional but validated when present —
entities without one are grouped under **Other** in the index. `resource` is an optional
canonical URL, repo, or homepage.

`subtype` is a fixed set: `tool`, `person`, `organization`. Unlike domains, it is not
read from `taxonomy.json` — adding a fourth subtype means changing the tool, not the
vocabulary file.

An entity page says what the thing **is**. A concept page says what it is **for**.

### `source`

**Location:** `sources/<channel>/<slug>.md` — one per consumed artifact.

```yaml
---
type: source
source_type: video            # video | talk | paper | article | thread | course | book
title: "Context Engineering Is The New Prompt Engineering"
description: "Thesis: the bottleneck moved from wording to what you put in the window."
channel: cole-medin
affiliation: independent      # optional: independent | vendor | buyer
youtube_id: dQw4w9WgXcQ
url: https://www.youtube.com/watch?v=dQw4w9WgXcQ
slug: cole-medin/context-engineering
published: 2026-06-14
duration: "00:23:11"
raw: ../../raw/cole-medin/context-engineering.md
summary_status: pending       # pending | done
created: 2026-08-03
updated: 2026-08-03
---
```

Required: `type`, `source_type`, `title`, `description`, `slug`, `created`, `updated`.
When `source_type: video`, also required: `youtube_id`, `url`, `published`, `duration`,
`raw`.

`raw:` must resolve to a file inside `raw/`, and each transcript must be claimed by
exactly one source page. Two source pages pointing at one transcript is an error: it
double-counts toward the ≥2-source threshold below and fabricates corroboration that
never happened. (`okf ingest` also warns loudly when a channel publishes the same talk
twice under near-identical titles, for the same reason.)

`affiliation` is a convention the linter does not enforce. Record it anyway — a claim's
provenance stops being visible the moment it is lifted into a concept page.

`summary_status: done` means a human or an agent actually read the transcript and wrote
the thesis line. Do not set it on a source you did not read; `okf status` treats it as
ground truth for what is left to do, and re-ingestion deliberately refuses to clobber a
`done` page's hand-written description.

### `raw-transcript`

**Location:** `raw/<channel>/<slug>.md`

```yaml
---
type: raw-transcript
immutable: true
slug: cole-medin/context-engineering
url: https://www.youtube.com/watch?v=dQw4w9WgXcQ
published: 2026-06-14
duration: "00:23:11"
caption_source: youtube-auto
fetched: 2026-08-03
---
```

Required: `type`, `immutable`, `slug`.

**Never edit these by hand.** They are the audit trail — the thing a reader checks when
they do not believe a page. A transcript that has been tidied up is no longer evidence,
and there is no way to tell from the outside that it was tidied. Machine captions are
messy; the mess is the point.

Video transcript bodies are timestamped paragraph lines, roughly 30 seconds each:

```
[00:04:12] The thing nobody tells you about context windows is ...
```

Paragraphs are merged from raw caption cues so a citation lands on a readable block
rather than a three-word fragment.

### `moc`, `overview`, `note`

- `_mocs/*.md` use `type: moc` — hand-written narrative, opinionated where the generated
  indexes are neutral. Requires `type` and `title`.
- `type: overview` for documents about the KB itself. Requires `type` and `title`.
- `type: note` for human-facing pages that sit outside the traversable graph — link
  tables, trackers, reading lists. Held to almost no contract on purpose. Requires `type`
  and `title`.

These are exempt from the orphan check; they are entry points, not leaves.

## Typed relationships

Relationships are what make this a wiki instead of a folder of notes. An edge is asserted
by placing a link under one of these `##` or `###` headings:

| Heading | Meaning | Reciprocated |
|---|---|---|
| `## Prerequisites` | must be understood first | yes |
| `## Builds on` | parent concept this extends | yes |
| `## Part of` | component of a larger thing | yes |
| `## Contrasts with` | opposing, or defining-against | yes |
| `## Implemented by` | entities that realize this concept | yes |
| `## Tools` | tool entities used to do this | yes |
| `## Related` | worth exploring, untyped | yes |
| `## Sources` | provenance — the `sources/` pages that taught it | **no** |

**Reciprocity is loose.** If A links to B under a typed heading, B must link back to A
under *some* typed heading — not a specific one. Most of these relations have no clean
inverse: "A builds on B" does not make B a prerequisite of A in any sense an author would
write down. Demanding a matching heading would force people to assert relationships they
do not believe. `okf lint` reports one-way edges as warnings, never errors.

**Provenance is one-way and is never reciprocated.** A source does not link forward to the
concepts that cite it — it does not know about them, and it would go stale the moment
another concept cited it. This also means **inline citations are not graph edges**: a link
into `sources/` or `raw/` that happens to sit inside a typed section is provenance, not a
relationship, and the reciprocity check skips it. Without that exemption every citation
would generate a false one-way-edge warning and the check would be useless.

## Linking rules

- Inside `concepts/`, `entities/`, `sources/`, `_mocs/`, and at the KB root:
  **relative markdown links only** — `[Karpathy](../entities/people/karpathy.md)`.
- `[[wikilinks]]` in those directories are errors. Elsewhere in the KB they are warnings:
  fine for humans in an editor, invisible to a link-following agent.
- Links out of the KB into the rest of a surrounding vault are allowed and use relative
  paths too.
- Every link asserts a directed edge; the containing heading types it.
- Broken links are errors. Prefer creating a stub over leaving a dangling link.
- Links inside code fences and inline code are ignored, so examples in documentation do
  not get linted.

## Citation format

### Timestamped sources

```markdown
Karpathy calls this "jagged intelligence" — models that spike in verifiable domains
and fail unpredictably elsewhere ([Software 3.0](../sources/ai-engineer/software-3-0.md) @ 00:14:32).
```

The `@ HH:MM:SS` suffix must match a real `[HH:MM:SS]` marker in the transcript behind
that source page. Never estimate one. It is what lets an agent point a human at the exact
moment, and a fabricated timestamp is worse than no citation because it survives casual
inspection.

Quoted text must be copied character-for-character from the transcript. Do not fix the
grammar, do not paraphrase, do not stitch two sentences together.

### Sources without timestamps — convention

Articles, papers, and newsletters have no clock. Cite a **paragraph index** instead:

```markdown
The paper's own ablation undercuts the headline number ([Attention Sinks](../sources/arxiv/attention-sinks.md) ¶12).
```

`¶12` is the twelfth blank-line-separated block of the body of the immutable `raw/` file,
counted from 1, excluding frontmatter. The mechanic is identical to a timestamp: the
quote must appear in that paragraph, in that file, and the file never changes. The trust
model does not vary with source type — only the coordinate does.

**This is a convention, not a shipped feature.** `okf ingest` currently supports YouTube
only; there is no RSS, email, or PDF ingestion. If you place an article in `raw/` by hand,
`¶` is the citation form to use.

## Naming & atomicity

- **ID = KB-relative path minus `.md`.** `concepts/the-piv-loop.md` → `concepts/the-piv-loop`.
- Filenames are stable identities. **Never rename casually** — it breaks every inbound
  link, and inbound links are the only thing making a page findable.
- `kebab-case.md` for all new pages.
- **One topic per page.** Split past roughly 800–1,000 words of genuinely distinct
  subtopics.
- **Page-creation threshold:** create a page when a term recurs across **≥2 sources** *or*
  is linked from **≥2 places**. Otherwise embed it in the parent page.

That last rule is the one that keeps this from degrading into a folder of video
summaries. Every extraction pass produces candidates that feel worth a page in the moment;
most of them are one speaker's phrasing for something already covered. A KB of
single-mention stubs is strictly worse than a smaller dense one — it has the same
maintenance cost, worse navigation, and no corroboration. If you are about to create
`concepts/some-talk-title.md`, stop: that is a source, and it already exists in `sources/`.

## Domains and the taxonomy

`taxonomy.json` holds the closed vocabularies. The shipped values are a **default, not a
fixed list** — they reflect one corpus of AI-engineering talks and are expected to be
wrong for yours.

```
agentic_systems · ai_engineering · rag · local_llms
machine_learning · mathematics · system_design · product
```

Edit `domains` and `domain_order`, run `okf index`, done. That is the whole workflow:
`domains` maps slug → display label, `domain_order` fixes the heading order in generated
indexes, and any domain not in `domains` is a lint error on the page that declares it.

Two things are *not* user-editable this way:

- **Entity subtypes** are fixed at `tool`, `person`, `organization` in the tool itself.
  `entity_subtypes` and `entity_dirs` in the taxonomy control labels and directory names,
  and every subtype must have an explicit `entity_dirs` entry — it is not derived, because
  naive pluralization gives "persons".
- **Source types** in `source_types` control index grouping only. An unrecognized
  `source_type` is not a lint error; it lands under **Other**.

## Index contract

Every content directory has an `index.md`, generated by `okf index`. Entries are exactly:

```markdown
- [Display Name](relative-path.md) — one-line description
```

The description is **copied verbatim from the target's `description` field**. This is why
`description` must be one sentence: it is not a summary of the page, it is the line
someone reads while deciding whether to open the page. Editing an index by hand is
pointless — the next `okf index` overwrites it. Edit the source page's frontmatter.

Grouping comes from `taxonomy.json`. **Anything not matching a defined group lands under
`## Other` — nothing is ever silently dropped.** A page missing from its index is a lint
error, because a page an agent cannot find from an index is a page that does not exist.

`okf index` is deterministic: same KB contents in, byte-identical indexes out. That is
what makes `okf index --check` usable as a CI gate — if a rebuild would change any file,
the committed indexes are lying about what the KB contains.

## Validation

### `okf lint` — structural conformance

Errors block; warnings inform.

**Errors**
- missing or empty `type`, or an unrecognized `type`
- missing required field for the declared `type` (including the video-only fields)
- relative markdown link that does not resolve
- `[[wikilink]]` inside the strict tree
- `raw:` target that does not exist, or points outside `raw/`
- one transcript claimed by more than one source page
- concept/entity/source missing from its directory `index.md`
- `domain` not in `taxonomy.json`; `status`, `subtype`, or `confidence` outside its
  closed set

**Warnings**
- orphan page — no inbound link from any non-index content page
- one-way typed edge
- `description` longer than one sentence, or over 200 characters
- `status: seed` untouched for more than 90 days
- transcript in `raw/` with no source page pointing at it
- `[[wikilink]]` outside the strict tree

### `okf verify` — quote and timestamp verification

**Every `verbatim_quote` must be a literal substring of its transcript, and every
timestamp must resolve to a real marker in that file.** This is mandatory and automated:

```bash
okf verify                    # candidates and pages
okf verify --candidates-only  # Phase A output in .okf/candidates/
okf verify --pages-only       # citations in the KB itself
okf verify --json             # machine-readable; non-zero exit on any issue
```

This is the check the entire format's credibility rests on. Everything else — link
resolution, index coverage, reciprocal edges — establishes that the KB is *well-formed*.
None of it establishes that a single quoted sentence was ever said. A knowledge base whose
citations are approximately right is worse than no knowledge base, because it is trusted.

It is called out this loudly because it went wrong. In the original implementation this
check did not exist: quote fidelity was an instruction in a prompt and nothing verified
it. Three full extraction rounds ran that way, and `kb_lint.py` reported green the entire
time — every link resolved, every page was indexed, every required field was present, and
the structural linter had no opinion whatsoever about whether the quotes were real. Green
on structure was mistaken for green overall. `okf verify` exists so that mistake is not
available.

Run it in CI alongside `okf lint`. A KB that lints clean and fails verify is not
publishable.

### What is still manual

Semantic validation is not automated and is not close to it. Contradictions between
pages, claims that were true when recorded and are not now, a concept page that has
quietly drifted from what its sources actually said — nothing detects any of this. Two
pages can assert opposite things and every check will pass. That is an LLM review pass on
a cadence you set, and it is the standing reason to keep `raw/` immutable: it is the only
thing you can re-read to find out which page is wrong.
