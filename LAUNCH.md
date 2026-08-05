# Launch copy — ugraph

Working drafts. Not part of the package; delete or move before tagging if you'd rather
keep the repo clean.

**The one rule running through all of these:** the honest version is the strong version.
The tool's whole claim is "you can check this." Copy that oversells it is self-refuting —
someone will install it and find out. Every number below is real and was measured.

**Numbers you can safely use:**
- 150 talks ingested, 57 concepts, 385 pages, `lint` and `verify` both clean
- `verify` found 11 defects in my own hand-read KB; 1 was a sentence nobody said
- ~230-page graph exports to ~64 KB of JSON
- 3 runtime dependencies, no database, no embeddings
- `qwen2.5-coder:7b` locally: 5 concepts from one 45-min talk in ~7 minutes

**Do not claim:** that it answers questions better than a bare model. Nobody has measured
that. It's listed as unproven in the README and should stay unproven in the copy.

---

## LinkedIn — the main post

> Long-form, professional, story-first. This is the one that carries the launch.

---

I built a knowledge base from 150 conference talks. Then I ran a script over it that
checks every quote against the original transcript.

It found 11 defects. In pages I had written and read myself.

Ten were small. An editor writes "because" where the speaker said "cuz." Captions read
"self harm," the page tidies it to "self-harm." A garbled acronym gets helpfully expanded
to "[OpenTelemetry]" in place. Two sentence fragments get stitched across an ellipsis.
A period appears where the speaker never paused.

Every one of those is someone doing their job well. Machine transcripts are messy and
cleaning them up is a kindness to the reader.

The eleventh was different. One page had a Lyft engineer saying:

"if this interaction should grant a concession, did it?"

The word "concession" is in that talk. That sentence is not. It was a cleaned-up
paraphrase that had quietly put on quotation marks somewhere between the transcript and
the page.

I had read that page. Several times. It reads perfectly.

That is the failure mode nobody has a defence against — not carelessness, but the fact
that a well-written fabrication and a real quote look identical on the page. You cannot
catch it by being careful. You can only catch it by checking.

So that's what I built.

ugraph turns a YouTube channel into a knowledge base that an AI agent can navigate and
cite. Plain markdown, YAML frontmatter, relative links. No database. No embeddings. No
vector store. Seven directories you could have made by hand.

And one command — `ugraph verify` — that confirms every quote is a literal substring of
its transcript and every timestamp is real.

That check is the point. Everything else is plumbing.

Two decisions I'd defend:

**One page per idea, not one per video.** Ten talks about context engineering produce one
page citing ten sources. A folder of video summaries is not a wiki, it's a folder. The
merge is the entire value and it's also the hard part.

**Markdown stays the source of truth.** You can read it, grep it, `git diff` it, edit a
page at 2am, and nothing needs re-indexing. A ~230-page base exports to 64 KB of JSON —
small enough to hand a model the whole graph instead of teaching it a query language.

It installs in one command and points at any folder. Obsidian, Logseq, Foam, plain git —
they all just read markdown, so there's nothing to integrate.

MIT. Built on the Open Knowledge Format by Cole Medin.

One thing I'll say plainly because it belongs in the first paragraph and not the
footnotes: nobody has yet measured whether a knowledge base in this format answers
questions better than a bare model. The citations are real and checkable. "Agents
navigate it well" is a design intention, not a finding. That's the next thing I'm
testing, and I'd rather say so than let you find out.

🔗 github.com/saran-io/ugraph

---

## X / Twitter — thread

> Shorter sentences. One idea per post. The hook is the fabricated quote, not the tool.

**1/**
I built a knowledge base from 150 conference talks.

Then I wrote a script that checks every quote against the original transcript.

It found a sentence nobody had ever said.

**2/**
The page had a Lyft engineer saying:

"if this interaction should grant a concession, did it?"

"Concession" is in the talk. That sentence isn't.

It was a paraphrase that put on quotation marks somewhere along the way.

**3/**
I'd read that page several times.

It reads perfectly. That's the problem.

A well-written fabrication and a real quote look identical. You can't catch it by being
careful. Only by checking.

**4/**
10 more defects, all invisible:

"because" → speaker said "cuz"
"self-harm" → captions read "self harm"
"[OpenTelemetry]" → expanded over a garbled acronym
a period the speaker never paused for

Each one an editor doing their job.

**5/**
So: ugraph.

YouTube channel → a knowledge base an agent can navigate and cite.

Plain markdown. No database. No embeddings. No vector store.

7 directories you could've made by hand.

**6/**
The one command that matters:

  ugraph verify

Every quote a literal substring of its transcript. Every timestamp real.

That check is the point. Everything else is plumbing.

**7/**
Design call I'd defend:

One page per IDEA, not per video.

10 talks about context engineering → 1 page citing 10 sources.

A folder of video summaries isn't a wiki. It's a folder.

**8/**
Markdown stays the source of truth.

Read it. Grep it. git diff it. Edit at 2am. Nothing re-indexes.

230 pages → 64 KB of JSON. Small enough to hand a model the whole graph instead of
teaching it a query language.

**9/**
Works with Obsidian, Logseq, Foam, or a plain git repo.

There's nothing to integrate. They all just read markdown.

  uv tool install git+https://github.com/saran-io/ugraph
  ugraph init

**10/**
The honest part:

Nobody has measured whether this answers questions better than a bare model.

Citations are real and checkable. "Agents navigate it well" is a design intention, not a
finding.

That's what I'm testing next.

**11/**
MIT. Built on the Open Knowledge Format by @cole_medin.

github.com/saran-io/ugraph

---

## Instagram — carousel

> 8 slides. Big type, one thought each. The story does the work; the tool arrives at 5.

**Slide 1** — full bleed, largest type
> I read this page
> several times.
>
> It quoted someone
> saying something
> they never said.

**Slide 2**
> 150 conference talks.
> 385 pages.
> Every quote checked
> against the original
> transcript.
>
> **11 defects.**

**Slide 3** — monospace, styled as a page excerpt
> "if this interaction
> should grant a
> concession, did it?"
>
> — attributed to a Lyft engineer
>
> **He never said it.**

**Slide 4**
> The other 10 were
> smaller.
>
> "because" → he said "cuz"
> "self-harm" → captions: "self harm"
> a period he never paused for
>
> Every one of them,
> an editor doing
> their job.

**Slide 5**
> You cannot catch this
> by being careful.
>
> A good fabrication and
> a real quote look
> identical on the page.
>
> You can only catch it
> by checking.

**Slide 6** — the tool
> **ugraph**
>
> YouTube channel →
> a knowledge base an
> agent can navigate
> and cite.
>
> No database.
> No embeddings.
> Just markdown.

**Slide 7** — terminal styling
> `ugraph verify`
>
> Every quote a literal
> substring of its
> transcript.
>
> Every timestamp real.

**Slide 8** — CTA
> Free. MIT. One command.
>
> **github.com/saran-io/ugraph**
>
> Built on the Open Knowledge
> Format by Cole Medin.

**Caption:**
I built a knowledge base from 150 conference talks, then wrote something to check my own
work. It found a quote that was never said — on a page I'd read several times. The tool
is free and open source, link in bio. The full story is on LinkedIn. 🔗

---

## Company blog / newsletter — long form

> This is the article. It should be able to stand on its own even if nobody installs
> anything, because the argument is more broadly useful than the tool.

### Title options

1. **The quote that was never said**
2. **Your knowledge base is lying to you, politely**
3. **What I found when I checked my own work**
4. **A knowledge base you can actually verify**

Recommend #1. It's concrete, it's the story, and it doesn't accuse the reader.

### Structure

**Open with the defect, not the tool.** The Lyft quote. What it said, what the transcript
said, that the word "concession" really is in the talk — which is what makes it
convincing. Land the point that the page had been read several times.

**Widen to the class of error.** The other ten. Frame them sympathetically: every one is
an editor improving a machine transcript, which is a reasonable thing to do. The error
isn't sloppiness. It's that the artifact of tidying is indistinguishable from the
artifact of fabricating, once it's on the page.

**Name why this is getting worse.** More knowledge bases are now assembled by models from
machine transcripts. Both ends of that pipeline produce plausible text as their normal
output. Plausibility is the product. Nothing in the pipeline is checking, and the output
is specifically optimized to survive a read-through.

**Then the design.** Only now introduce ugraph, as the consequence of the argument rather
than the subject of the article:

- Plain markdown, relative links, no database — so a citation is a path you can follow,
  and the check is a substring test rather than a similarity score
- Immutable `raw/` transcripts — the thing you check against cannot be edited to agree
  with the page
- One page per idea, not per video — the merge is the value
- Typed relationship headings as the graph — `## Prerequisites` is a labelled edge, and
  `lint` enforces the other page points back

**The generation–verification loop.** The most transferable idea in the piece, and it's
worth naming as a general pattern: an unreliable generator plus a cheap mechanical check
equals a reliable pipeline. It's why a 7B model running on a laptop is safe to use for
extraction here — it paraphrases, gets caught by a substring test, and retries. Measured:
5 concepts from a 45-minute talk in ~7 minutes, none rejected.

**Where the loop doesn't reach — be specific.** Deciding that ten candidate concepts are
really one concept has no mechanical check. `verify` catches a fabricated quote; nothing
catches bad judgement. So that step is left to a strong model with a human looking at the
result, and the tool deliberately does not offer to do it locally. This paragraph is what
makes the rest of the article credible.

**Close on the unproven part.** Nobody has measured whether the format answers questions
better than a bare model. Say it plainly. State that it's next.

### Pull quote

> A well-written fabrication and a real quote look identical on the page. You cannot
> catch that by being careful. You can only catch it by checking.

---

## Notes on sequencing

1. Push the repo. Nothing below works without a live link.
2. Blog post first — it's the canonical version everything else points at.
3. LinkedIn same day, linking the post.
4. X thread same day. Different hook, same story.
5. Instagram a day later, pointing at the blog.

If someone asks "is this just RAG?" — no, and the honest answer is that it's the opposite
bet. RAG retrieves chunks by similarity at query time. This builds a small curated graph
ahead of time that a model reads by following links, and the entire thing fits in a
context window. Different tradeoff, not a better one: it needs curation, and it doesn't
scale to a million documents.
