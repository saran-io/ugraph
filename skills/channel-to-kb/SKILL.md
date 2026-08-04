---
name: channel-to-kb
description: Extract concepts and entities from ingested YouTube transcripts into the OKF knowledge base at 04_learning/. Use when transcripts exist in raw/ with source pages marked summary_status pending, or when the user asks to process/extract/summarize ingested talks, grow the knowledge base from a channel, or run the extraction pass.
---

# Channel → Knowledge Base (extraction pass)

Stage 2 of the KB pipeline. Stage 1 (`09_ai_agents/agents/channel_ingest.py`) already
put timestamped transcripts in `raw/` and stub pages in `sources/`. This skill turns
them into **canonical, cross-linked concept and entity pages**.

Read `04_learning/SCHEMA.md` before writing anything. It is the contract; `kb_lint.py`
enforces it.

## The one rule that matters

**Synthesize across sources; never create one page per video.**

A concept page is not a talk summary. It is the canonical statement of an idea,
assembled from every source that taught it. Ten talks mentioning context engineering
produce **one** `concepts/context-engineering.md` citing ten sources — not ten pages.

If you find yourself creating `concepts/mcp-apps-talk.md`, stop. That is a source, and
it already exists in `sources/`.

## Two modes

**Single-pass** (below) — read transcripts and write pages in one go. Correct for
batches of ~10 or fewer.

**Two-phase** — for a channel too large to hold in one context (100+ talks). The reason
it exists: canonicalization needs a global view, but 750k tokens of transcript won't fit
alongside page writing. Splitting lets the expensive reading go parallel while the
decision that needs global knowledge stays serial.

```
Phase A  parallel, one agent per transcript   → 09_ai_agents/candidates/<slug>.json
         spec: references/candidate-extraction.md
         emits candidates ONLY — never pages
Phase B  serial, one context                  → cluster candidates, decide
         create / merge / embed against okf.concept_registry()
Phase C  parallel, ONE AGENT PER CONCEPT      → write pages
         parallelising by concept, not transcript, makes write conflicts impossible
Phase D  serial                               → reciprocity, build_indexes, kb_lint
```

**Never parallelise Phase C by transcript.** Twenty agents reading twenty talks will each
independently create `context-engineering.md`, and the merge — the entire value of the
KB — is lost.

Check progress any time with `python3 09_ai_agents/agents/kb_status.py --clusters`.

## Workflow (single-pass, and Phase B/C of two-phase)

### 1. Pick the batch

```bash
cd 09_ai_agents
grep -l "summary_status: pending" ../04_learning/sources/**/*.md | head -10
```

Default batch size is **10 transcripts**. Larger batches degrade canonicalization —
you stop noticing that talk 14 and talk 3 are describing the same idea.

### 2. Load what already exists — before reading any transcript

```bash
cat ../04_learning/concepts/index.md
cat ../04_learning/entities/index.md
```

This is the dedup baseline. You cannot canonicalize against pages you haven't seen,
and the most common failure of this pass is creating a near-duplicate of a concept that
already exists under a slightly different name.

### 3. Read the transcripts

Read each `raw/` file in the batch. For each, note:

- **Claims worth keeping** — with their `[HH:MM:SS]` timestamps
- **Named things** — tools, people, companies → candidate entities
- **Ideas** — techniques, patterns, arguments → candidate concepts

Ignore: conference logistics, speaker intros, demo narration, audience Q&A chatter.
A 20-minute talk usually yields 1–3 real concepts. Often zero. **Zero is a valid
result** — say so rather than manufacturing a page.

### 4. Canonicalize

For each candidate, decide:

| Situation | Action |
|---|---|
| Page already exists | **Merge** — add the new source's angle + citation to the existing page. Update `sources:` and `updated:`. |
| New, and appears in ≥2 sources *or* linked from ≥2 places | **Create** a new page |
| New, appears once, not linked elsewhere | **Embed** it in a parent concept — do not create a page |

That last row is the page-creation threshold from SCHEMA.md. Respect it. A KB of
single-mention stubs is worse than a smaller dense one.

### 5. Write the pages

Follow SCHEMA.md exactly:

- Frontmatter: `type`, `title`, one-sentence `description`, `domain` (closed vocabulary
  in `09_ai_agents/runtime/taxonomy.json`), `status`, `sources`, `created`, `updated`
- **Relative markdown links only.** No `[[wikilinks]]` anywhere in the OKF tree.
- Typed relationship headings: `## Prerequisites`, `## Builds on`, `## Contrasts with`,
  `## Implemented by`, `## Related`, `## Sources`
- **Reciprocate every typed edge.** If A links to B under a typed heading, add the
  matching link on B. The linter warns on one-way edges.
- Cite claims: `([Talk title](../sources/ai-engineer/slug.md) @ 00:14:32)`

### 6. Update the source pages you consumed

For each source in the batch:

- Replace the placeholder `description` with a real one-sentence thesis
- Set `summary_status: done`
- Replace the stub body with a short summary and a `## Concepts extracted` list
  linking to the concept pages you wrote

### 7. Validate

```bash
cd 09_ai_agents
python3 runtime/build_indexes.py
python3 agents/kb_lint.py
```

Both must pass with **0 errors** before you report done. Fix what it reports; do not
hand back a failing KB. Orphan warnings on sources you just processed mean you didn't
link them from a concept — go back to step 5.

### 8. Report

Tell the user, concretely:

- Concepts **created** vs **merged into** (these are different, and merges are the
  signal the KB is working)
- Entities added
- Transcripts that yielded nothing, and why
- Current lint status

Then stop. Let them review the diff before the next batch.

## Quality bar

The pages you write should read like the hand-built ones in `concepts/` — for example
`concepts/jagged-intelligence.md`. Specifically:

- A `>` blockquote opening line that states the idea sharply
- Prose that explains *why it matters*, not a bulleted transcript restatement
- Genuine cross-links that a reader would actually follow
- Every non-obvious claim traceable to a source and timestamp

**Do not pad.** If a concept only warrants four sentences, write four sentences.
A short true page beats a long padded one.

## What not to do

- Don't invent claims the transcript doesn't support. Auto-captions garble names and
  terms — if a term looks mangled, verify against the video or leave it out.
- Don't create a concept page per talk.
- Don't use `[[wikilinks]]` in the OKF tree.
- Don't edit anything in `raw/`. It is immutable provenance.
- Don't mark `summary_status: done` on a source you didn't actually read.
- Don't skip the lint step.

## Related

- Stage 1 ingestion — `09_ai_agents/agents/channel_ingest.py`
- Schema contract — `04_learning/SCHEMA.md`
- Conformance gate — `09_ai_agents/agents/kb_lint.py`
- Index generation — `09_ai_agents/runtime/build_indexes.py`
