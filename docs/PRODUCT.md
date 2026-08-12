# ugraph — product home

**Single source of truth** for goal, features, roadmap, and the public product log.  
Contributors and future-you: read this before adding work. Ship notes go in the **Product log** at the bottom — then commit, tag, PyPI, then X / LinkedIn.

Companion (mechanics only): [releasing.md](releasing.md) · ADRs in `docs/adr/` · evidence in `CLAIMS.md`

---

## 1. Goal (locked)

> An **open-source CLI** anyone can install.  
> Copy **any local input** → run `ugraph` → process with local/advanced ML → build a **concept-driven knowledge base + graph** agents can use.  
> Over time the KB **evolves and self-improves** — not a one-shot dump.

**Install → capture anything → compile concept KB + graph for agents → keep improving.**

```
AI stack =
    Inference     (Ollama / open weights)
  + Graph memory  (ugraph)          ← this product
  + Agent / app   (what builders already have)
  + Control       (hook / slim / wipe)
```

| For | Not for |
|-----|---------|
| Devs & builders who install a CLI | Hosted chatbot / memory SaaS |
| Local-first, OSS contributors | “Second brain” app with a UI |
| Agents that hook a KB + graph | Replacing Obsidian as an editor |

---

## 2. Daily loop (the habit)

1. Copy text, screenshot, file, …  
2. Type `ugraph`  
3. See **Detected: …** + preview  
4. Confirm **Ingest this? [Y/n]**  
5. Local model runs → concepts + graph  

If you wouldn’t hit that **≥10×/week**, stop expanding modalities and fix the loop.

**Now:** any CLI input (clipboard, paste, pipe, file, URL), detect → preview → confirm.  
**Next:** screenshot OCR, then PDF/book — still the same loop.

---

## 3. Feature map

Status: **done** · **partial** · **todo** · **later**  
`[OKB]` = inspired by [OpenKB](https://github.com/VectifyAI/OpenKB) (adopted into our roadmap; implemented our way).

### Band 0 — Install & trust

| ID | Feature | Status |
|----|---------|--------|
| F0.1 | Installable OSS CLI (`ugraph-kit` / `ugraph`) | **done** |
| F0.2 | `ugraph init` → markdown KB | **done** |
| F0.3 | Ollama-first / no API key required | **partial** |
| F0.4 | Verbatim gates + verify | **done** |
| F0.5 | `[OKB]` Public example vault (one paper → concepts → ask) | **todo** |

### Band 1 — Capture anything

| ID | Feature | Status |
|----|---------|--------|
| F1.1 | Clipboard text | **done** |
| F1.2 | Detect → preview → confirm (text, YT playlist, YT person) | **done** |
| F1.3 | Text → chunks → concepts → indexes | **done** |
| F1.4 | Screenshot / image → OCR | **todo** |
| F1.5 | `[OKB]` PDF / book (short path first; long-doc tree later) | **todo** (txt/md file works) |
| F1.8 | `[OKB]` Unified `ugraph add <file\|dir\|url>` (plus clipboard bare `ugraph`) | **todo** |
| F1.6 | Audio → local ASR | **later** |
| F1.7 | Video file | **later** |
| F1.9 | `[OKB]` Long-doc index (TOC/tree retrieve — PageIndex-class, local) | **later** |

### Band 2 — KB + graph for agents

| ID | Feature | Status |
|----|---------|--------|
| F2.1 | Concept / entity / source pages | **done** |
| F2.2 | Indexes + typed links | **done** |
| F2.3 | Graph export | **partial** |
| F2.4 | `[OKB]` `ugraph ask` / query with **citation-hard** answers | **todo** ← pick up hard |
| F2.5 | MCP / stack hooks | **todo** |
| F2.6 | Local embed + search | **partial** (embed yes; search no) |
| F2.7 | `[OKB]` `watch` raw/ → auto-compile new files | **later** |
| F2.8 | `[OKB]` `remove` / `recompile` document lifecycle | **todo** |
| F2.9 | `[OKB]` Agent-facing KB contract (`AGENTS.md` or SCHEMA as runtime manual) | **partial** (SCHEMA/skill exist; not first-class) |

### Band 3 — Evolves over time

| ID | Feature | Status |
|----|---------|--------|
| F3.1 | `[OKB]` Merge on compile — second source **updates** existing concepts | **todo** ← pick up hard |
| F3.2 | Conflict file when merges disagree | **todo** |
| F3.3 | Batch / sleep consolidate | **later** |
| F3.4 | `ugraph gc` lifecycle | **todo** |
| F3.5 | Eval proves it gets better | **todo** |
| F3.6 | `[OKB]` Entity pages kept in sync on compile (people/orgs/tools) | **partial** (person capture; not full sync) |

### Non-goals (for now)

Hosted SaaS · full agent OS · Mem0-style chat prefs · Rust rewrite · “any media” marketing before image+PDF+audio · drop-raw by default · **OpenKB web workbench** · **Skill Factory / slide decks** (generators after ask+merge) · soft uncited wiki prose

**Deviation test:** If a change doesn’t improve *copy → `ugraph` → concepts/graph an agent can use* for someone who just installed the CLI, defer it.

---

## 4. OpenKB pickup assessment

Reference: [VectifyAI/OpenKB](https://github.com/VectifyAI/OpenKB) — CLI wiki compiler, PageIndex long docs, query/chat, OKF-ish markdown.

### Adopt (add to our list — implement ugraph-style)

| OpenKB idea | Our feature ID | Why |
|-------------|----------------|-----|
| `query` / `chat` over the wiki | **F2.4** | Biggest product gap; without ask, the KB feels dead |
| Compile updates existing concepts | **F3.1** (+ F3.2 conflicts) | Their “knowledge compounds” story; we only append today |
| `add file\|dir\|url` | **F1.8** | Clearer than split ingest/capture; keep clipboard as bare `ugraph` |
| PDF / long documents | **F1.5**, later **F1.9** | Books are the learning-gate demo |
| `remove` / `recompile` | **F2.8** | Maintained KB, not append-only dump |
| `watch` | **F2.7** | Nice after add+ask work |
| Examples + agent contract | **F0.5**, **F2.9** | Contributors need a walked demo |
| Entity sync on compile | **F3.6** | Enrich people/orgs/tools as knowledge grows |

### Adapt (same job, our constraints)

| OpenKB | ugraph twist |
|--------|----------------|
| Answers from wiki prose | **Citation-hard** ask (quotes/chunk ids must verify) |
| PageIndex (+ optional cloud) | Local tree/TOC first; no required cloud key |
| LiteLLM multi-cloud default | **Ollama-first**; cloud escape hatch only |
| Wikilinks / Obsidian graph | Keep OKF relative links + `ugraph graph` export |

### Skip (for now)

| OpenKB | Why skip |
|--------|----------|
| Knowledge Workbench web UI | Dilutes CLI wedge; optional much later |
| Skill Factory / HTML decks | Generators after ask + merge ship |
| “No vector DB” as religion | Light local embed/search OK if ask stays cited |
| Soft LLM wiki without gates | Attacks our provenance moat |

**Positioning vs OpenKB:** they win formats + polish + chat; we win **local + citation-hard + clipboard habit**. Steal their *surfaces* (ask, add, merge), not their *identity*.

---

## 5. Honest gap

| Goal phrase | Today |
|-------------|--------|
| OSS installable CLI | Yes |
| Copy any input | Partial — text / file / pipe / URL; more modalities next |
| Process → concepts | Partial |
| Graph agents use / interact | Weak — export, no ask/MCP |
| Self-improving over time | Mostly missing (OpenKB ahead on merge/recompile) |

---

## 6. Build & release order

Reordered after OpenKB assessment: **ask + merge** rise; OCR stays in the daily loop.

| Next up | Ship when | PyPI theme |
|---------|-----------|------------|
| **F0.3** Ollama-first README/auth | Fresh install never needs Anthropic | **0.2** |
| **F1.4** screenshot OCR | Mac clipboard image → same path | with 0.2 |
| **F2.4** `ugraph ask` (cited) | One question → answer + quote spans | **0.3** ← OKB pickup |
| **F3.1** merge on compile | Second source grows concept pages | with 0.3 |
| **F1.8** `ugraph add` | file/dir/url one command | **0.4** |
| **F1.5** PDF/book (+ F0.5 example vault) | Learning-gate demo | **0.5** |
| **F2.8** remove/recompile · **F3.4** gc | Lifecycle parity | **0.6** |
| **F1.9** long-doc tree · **F2.7** watch · **F1.6** audio | Scale + multimodal | **0.7+** |

Each release: bump version → `pytest` → `uv build` → GitHub tag → PyPI ([releasing.md](releasing.md)) → **log below** → post X / LinkedIn.

Promises to say: *No API key required. Open weights via Ollama. Library on disk you own. Answers you can verify.*  
Don’t say: *Free forever / Claude quality / any media / “just like OpenKB”.*

---

## 7. Keep / kill (90 days)

**Double down if:** confirm→ingest ≥10×/week · Ollama concepts you re-open · merge grows the graph · `ask` returns cited answers · at least one agent hook.  
**Lab-only if:** you still paste into ChatGPT instead · local output is mush · habit never forms.

---

## 8. Product log

Newest first. One entry per meaningful ship (feature, release, or public milestone).  
Use this for GitHub release notes and social posts.

### Template

```md
### YYYY-MM-DD — short title (vX.Y.Z optional)
- **Shipped:** …
- **Why:** …
- **Try:** `…`
- **Next:** …
- **Share angle:** one sentence for X / LinkedIn
```

### Entries

### 2026-08-10 — OpenKB pickup folded into feature map
- **Shipped:** Assessed [OpenKB](https://github.com/VectifyAI/OpenKB); adopted ask, merge-on-compile, `add`, PDF/long-doc, remove/recompile, examples into `PRODUCT.md` (`[OKB]` tags). Skipped workbench / skill factory / soft citations.
- **Why:** Steal their finished surfaces; keep local + citation-hard identity.
- **Try:** Read §4 OpenKB pickup assessment
- **Next:** F0.3 + F1.4 (0.2), then F2.4 ask + F3.1 merge (0.3)
- **Share angle:** Building a local, verifiable knowledge graph CLI — learning from OpenKB’s compile loop without becoming another cloud wiki chat.

### 2026-08-09 — Product home + capture confirm
- **Shipped:** Single product doc (`docs/PRODUCT.md`). Bare `ugraph`: detect clipboard / paste / URL / person → preview → confirm. Ingest resume hardening (`--repair-state`, billing abort, status alignment). Local embed hash-reuse earlier in the week.
- **Why:** One place for goal/features/log; daily loop must feel intentional for any input.
- **Try:** Copy any text → `ugraph` → `[Y/n]`
- **Next:** F1.4 screenshot OCR; Ollama-first README (F0.3)
- **Share angle:** Open-source CLI: any input → confirm → concept KB for agents — no dashboard required.

### 2026-08-07 — Ingest + provenance spine (alpha)
- **Shipped:** Batch URL/file ingest, extract/promote/indexes, content-addressed chunks, verify gates, PyPI-oriented packaging.
- **Why:** Prove capture → concepts on a real corpus.
- **Try:** `printf '…' | ugraph --yes` · `ugraph ingest file ./note.md`
- **Next:** Confirm UX; repair/resume for long runs
- **Share angle:** Filesystem-native, citation-gated knowledge compile from any source you choose.

---

## 9. OSS loop (how we publish)

```
build daily → commit → push GitHub
    → tag release when a Band item ships
    → PyPI (ugraph-kit)
    → update Product log (§7)
    → post X + LinkedIn (use Share angle)
    → contributors land on PRODUCT.md + good first issues
```

Good first issues = anything marked **todo** in Band 1–2 with a clear “done when” in a GitHub issue linking this file.
