# Phase A — candidate extraction (subagent spec)

You read **one transcript** and emit **one JSON file**. You do not write knowledge base
pages. You do not decide whether a concept deserves a page — that decision needs a view
across the whole corpus, which you don't have.

Your output is the raw material a later canonicalization pass clusters. Precision matters
more than coverage: a wrong quote poisons a page that cites it.

## Input / output

- **Read:** `<kb>/raw/<channel>/<slug>.md`
- **Write:** the KB's candidates directory — `ugraph status --json`
  reports it, and it defaults to `.ugraph/candidates/<slug>.json`

Nothing else. Do not touch anything under the knowledge base itself.

## Schema

```json
{
  "slug": "ai-engineer/<slug>",
  "title": "exact title from the transcript frontmatter",
  "yield": "high | low | none",
  "thesis": "One sentence: the argument this talk makes. Not a topic label.",
  "cluster_hint": "harness | memory-context | rl-posttraining | evals | security | fde | multi-agent | long-horizon | meta-role | ux-product | local-edge | vertical | mcp | other",
  "concepts": [
    {
      "name": "short lowercase noun phrase",
      "claim": "One sentence stating what the talk asserts about this.",
      "verbatim_quote": "Exact words copied from the transcript.",
      "timestamp": "00:14:32",
      "domain": "agentic_systems | ai_engineering | rag | local_llms | machine_learning | mathematics | system_design | product"
    }
  ],
  "entities": [
    {"name": "TauBench", "subtype": "tool", "note": "one line on what it is / why it matters here"}
  ],
  "notes": "Optional. Caveats, garbled sections, anything the canonicalizer should know."
}
```

## Rules

**Quotes must be verbatim.** Copy exactly from the transcript — do not clean up grammar,
do not paraphrase, do not stitch two sentences together. The quote is what a later page
will cite, and someone will click the timestamp to check it. Auto-captions are messy;
that's fine, copy the mess.

**Timestamps must be real.** Use the `[HH:MM:SS]` marker of the paragraph the quote came
from. Never estimate.

**Watch for garbled names.** These are machine captions. Speaker names, company names, and
product names are frequently mangled — real examples: "Aruba"/"Rue Ba" for Uber,
"SER"/"Sonder" for SonderMind, "Sweet Bench" for SWE-Bench. If a term looks corrupted and
you cannot confidently recover it, **omit it or flag it in `notes`. Never guess a name.**

**`yield: none` is a correct answer.** Track intros, sponsor pitches, workshop logistics,
and demo narration frequently contain no transferable idea. Return `"yield": "none"` with
an empty `concepts` array and say why in `notes`. Do not manufacture concepts to look
productive. A typical 20-minute conference talk yields **1–3** real concepts; many yield
zero.

**Name concepts generically, not by talk.** `"context compaction"`, not
`"Notion's approach to context compaction"`. The canonicalizer merges by name, so
talk-specific names defeat the whole point. If two talks describe the same idea, they
should produce the same or similar `name`.

**One entry per distinct idea.** Don't split one idea into four near-identical entries to
pad the list, and don't merge two genuinely different ideas into one.

## What counts as a concept

Include a technique, pattern, architectural decision, failure mode, or argument that
would still be useful to someone who never watches this talk.

Exclude: product announcements, company background, conference logistics, "come to our
booth", personal anecdotes without a transferable point, and restatements of things every
practitioner already knows.

**Read the Q&A. Weight it up, not down.** This is counterintuitive and it was learned the
hard way: on a 94-minute workshop, ~60% of the runtime was setup and live-coding narration
that yielded nothing — but the audience Q&A was the single richest vein in the file, and
four of eleven concepts came from it. Prepared talks are rehearsed and often pitch-shaped.
Q&A is unscripted practitioners asking about the thing that actually bit them
("when do you copy data into a graph versus leave it in place?"). A speaker rarely
volunteers that. Never skip the last third of a transcript because the prepared portion
has ended.

**Judge the source, not just the content.** If a talk is a vendor pitch with a
predetermined conclusion, or rests on a demo rather than a benchmark, say so in `notes`.
Extract the ideas anyway — but the canonicalizer needs to know whether a claim is backed
by production numbers at scale or by one person's home lab, because that decides whether
the resulting page carries `confidence: low`.

**The speaker can be wrong.** Verbatim quoting protects against caption noise; it does not
protect against factual error. One talk glossed OWL as "web object language" (it is Web
Ontology Language). Record the claim accurately, flag the error in `notes`, and never
propagate it as fact.

## Yield levels

| Level | Meaning |
|---|---|
| `high` | 2+ concepts a practitioner could act on |
| `low` | 1 concept, or ideas that are real but thin |
| `none` | nothing transferable |

## Before you finish

- Every `verbatim_quote` appears character-for-character in the transcript
- Every `timestamp` matches a real `[HH:MM:SS]` marker in that file
- Every `domain` is from the closed list above
- The JSON parses
- You wrote exactly one file, to the candidates directory
