# ugraph

Turn any CLI input — clipboard, paste, pipe, file, or URL — into a
filesystem-native knowledge base that Obsidian and agents can read. Raw sources
remain inspectable, chunk IDs are content-addressed, and extracted quotes are
checked against source text before they become candidates.

> **Alpha:** the ingestion foundation is usable; retrieval and the evaluation
> harness are still under active development.

## Install

The distribution is named `ugraph-kit` because `ugraph` is already taken on
PyPI. The installed command is still the short form: `ugraph`.

```bash
# Recommended: isolated command-line install
uv tool install ugraph-kit

# Or with pipx
pipx install ugraph-kit
```

To use Anthropic or OpenAI synthesis:

```bash
uv tool install "ugraph-kit[api]"
# pipx install "ugraph-kit[api]" also works
```

Python 3.10+ is required.

## First run

Create a knowledge folder inside an Obsidian vault (or anywhere on disk):

```bash
ugraph init ~/Documents/MyVault/knowledge
export UGRAPH_KB=~/Documents/MyVault/knowledge
```

Copy some text and run:

```bash
ugraph
```

On macOS and supported Linux desktops, ugraph reads the clipboard. Otherwise it
prompts for a paste terminated by Ctrl+D. Piped input is always supported:

```bash
printf 'Hybrid retrieval combines lexical and semantic search.' | ugraph
```

## Add a person

Copy a profile or talk URL (or paste a bio) and run `ugraph`. It previews the
detected identity and asks before writing.

The explicit, scriptable form is:

```bash
ugraph person "https://example.com/about"
ugraph person "https://example.com/about" --yes
```

This creates:

- `entities/people/<name>.md` — the canonical, minimally verified person page
- `resources/people/<name>.md` — a compatibility redirect for existing vaults

Repeating the command does not duplicate the person or overwrite
human-authored canonical content.

## Model setup

Capture and person resolution do not require an LLM. Synthesis is optional:

```bash
ugraph auth set anthropic
ugraph auth use anthropic

# or
ugraph auth set openai
ugraph auth use openai

# or a running local Ollama installation
ugraph auth use ollama
```

Check the active configuration with `ugraph auth status`.

## Other commands

```bash
ugraph --kb ./knowledge ingest file ./note.md
printf 'a claim you care about' | ugraph --kb ./knowledge --yes
ugraph ps
ugraph logs
ugraph lint
ugraph verify
```

`--kb` is a global option and therefore comes before the subcommand.
Alternatively set `UGRAPH_KB` once or run inside a configured knowledge base.

## Reliability contract

The current test suite enforces:

1. Re-ingesting the same document creates no duplicates.
2. Editing a document updates only affected chunks.
3. Interrupting ingestion and rerunning completes cleanly.
4. Model quotes must occur verbatim in their source chunk.
5. Person capture is idempotent and preserves existing human content.

Operational events are appended to `runs.jsonl` and exposed through
`ugraph ps` and `ugraph logs`.

## Development

```bash
uv sync --extra dev
uv run pytest
uv build
```

Project artifacts:

- `docs/PRODUCT.md` — **product home**: goal, features, roadmap, public product log
- `CLAIMS.md` — claims backed by tests, ADRs, or measured runs
- `docs/adr/` — architecture decision records
- `docs/techniques/` — just-in-time technique scans
- `docs/releasing.md` — PyPI publish steps
- `eval/` — evaluation harness work
- `corpus/manifest.json` — loaded real-world data

Licensed under Apache-2.0.
