"""
extract.py — optional model-driven candidate extraction (Phase A).

`ugraph` itself calls no model. This module is the one place that can, and it is opt-in:
the deterministic core keeps its three dependencies, and anything here is an extra.

## What this does and does not do

It does **Phase A only** — reading one transcript and emitting candidate concepts with
verbatim quotes and timestamps. That is mechanical work: find the claims, copy the words
exactly, note the time.

It deliberately does **not** do Phase B (deciding which candidates merge into which
canonical page). That decision needs every candidate in view at once and it is where the
entire value of the format lives — ten talks about one idea becoming one page rather than
ten. There is also no mechanical check for getting it wrong, which is precisely why it
deserves a good model and a human in the loop rather than a batch job.

## Why a weak model is safe here

Every quote a model produces is checked against the transcript before it is written:
a `verbatim_quote` that is not a literal substring is rejected and retried, and a
timestamp that does not exist is rejected. A 7B model that paraphrases gets caught by a
substring test, not by trust.

That turns an unreliable generator into a reliable pipeline at the cost of retries — the
`generation-verification loop`, applied to the tool that builds knowledge bases about it.

Backends:
    claude-code  guidance only; the agent does the work via the installed skill
    ollama       local, free, private. No new dependency — plain HTTP.
    api          Anthropic or OpenAI. Needs the `[api]` extra and a key.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ugraph import ledger, templates
from ugraph.config import Config
from ugraph.model import Page, iter_pages
from ugraph.store import read_md

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Retries per transcript when the verbatim gate rejects the output. Two is enough to
# clear transient sloppiness; a model that fails three times is the wrong model.
MAX_ATTEMPTS = 3

ProgressFn = Callable[[int, int, str, str], None]


class BackendError(RuntimeError):
    """Raised when a backend cannot run at all — missing key, server down."""


@dataclass
class ExtractResult:
    slug: str
    written: bool = False
    concepts: int = 0
    attempts: int = 0
    rejected: list[str] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class Backend:
    name = "base"

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def check(self) -> None:
        """Raise BackendError with an actionable message if unusable."""


class OllamaBackend(Backend):
    """Local models over Ollama's HTTP API.

    Uses urllib rather than a client library so the core install stays dependency-free —
    a local backend that requires a pip extra defeats the point of being local.
    """

    name = "ollama"

    def __init__(self, model: str = "qwen2.5-coder:7b", url: str = OLLAMA_URL):
        self.model = model
        self.url = url.rstrip("/")

    def check(self) -> None:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=5) as resp:
                tags = json.loads(resp.read())
        except Exception as exc:
            raise BackendError(
                f"cannot reach Ollama at {self.url} ({exc}).\n"
                "  Start it with `ollama serve`, or install from https://ollama.com"
            ) from exc

        available = {m.get("name", "") for m in tags.get("models", [])}
        if self.model not in available and f"{self.model}:latest" not in available:
            listed = ", ".join(sorted(available)[:6]) or "none"
            raise BackendError(
                f"model {self.model!r} is not pulled. Available: {listed}\n"
                f"  Get it with:  ollama pull {self.model}"
            )

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "prompt": user,
            "system": system,
            "stream": False,
            # Deterministic-ish: this is extraction, not writing. Creativity here
            # means paraphrase, which the verbatim gate then rejects.
            "options": {"temperature": 0.1},
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/api/generate", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read()).get("response", "")


class ApiBackend(Backend):
    """Anthropic or OpenAI. Imported lazily so the core install never needs them."""

    name = "api"

    def __init__(self, model: str | None = None):
        self.provider = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else (
            "openai" if os.environ.get("OPENAI_API_KEY") else "")
        self.model = model or ("claude-sonnet-4-5" if self.provider == "anthropic"
                               else "gpt-4o-mini")

    def check(self) -> None:
        if not self.provider:
            raise BackendError(
                "no API key found.\n"
                "  Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or use "
                "`--backend ollama` to run locally."
            )
        try:
            __import__(self.provider)
        except ImportError as exc:
            raise BackendError(
                f"the {self.provider} package is not installed.\n"
                f"  Install the extra:  pip install 'ugraph-kit[api]'"
            ) from exc

    def complete(self, system: str, user: str) -> str:
        if self.provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic()
            msg = client.messages.create(
                model=self.model, max_tokens=8000, system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in msg.content if b.type == "text")

        import openai
        client = openai.OpenAI()
        msg = client.chat.completions.create(
            model=self.model, temperature=0.1,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return msg.choices[0].message.content or ""


BACKENDS = {"ollama": OllamaBackend, "api": ApiBackend}


def make_backend(name: str, model: str | None = None) -> Backend:
    if name not in BACKENDS:
        known = ", ".join(sorted(BACKENDS) + ["claude-code"])
        raise BackendError(f"unknown backend {name!r}; expected one of {known}")
    cls = BACKENDS[name]
    backend = cls(model) if model else cls()
    backend.check()
    return backend


# ---------------------------------------------------------------------------
# The verbatim gate
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_TIMESTAMP = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]", re.MULTILINE)


def _norm(text: str) -> str:
    return _WS.sub(" ", str(text)).strip()


def gate(candidate: dict, transcript: str) -> tuple[list[dict], list[str]]:
    """Keep only concepts whose quote and timestamp survive checking.

    This is what makes a small local model usable. A model that paraphrases produces a
    quote that is not a substring; a model that guesses a time produces a marker that
    does not exist. Both are caught here rather than discovered months later in a page
    that cites something nobody said.
    """
    body = _norm(transcript)
    stamps = set(_TIMESTAMP.findall(transcript))

    kept, rejected = [], []
    for concept in candidate.get("concepts") or []:
        name = str(concept.get("name", "?"))
        quote = _norm(concept.get("verbatim_quote", ""))
        stamp = str(concept.get("timestamp", "")).strip()

        if not quote:
            rejected.append(f"{name}: no quote")
            continue
        if quote not in body:
            rejected.append(f"{name}: quote is not verbatim")
            continue
        if stamp and stamp not in stamps:
            rejected.append(f"{name}: timestamp {stamp} is not in the transcript")
            continue
        kept.append(concept)

    return kept, rejected


def parse_json(text: str) -> dict | None:
    """Pull a JSON object out of a model response.

    Small models wrap JSON in prose or code fences however they were feeling. Rather
    than prompt harder, find the outermost braces — cheaper than a retry.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def pending_sources(config: Config) -> list[Page]:
    """Sources with a transcript, no candidates yet, and not already synthesized."""
    out = []
    for page in iter_pages(config, root=config.sources, strict=False):
        if page.type != "source":
            continue
        if str(page.meta.get("summary_status", "")) == "done":
            continue
        slug = str(page.meta.get("slug") or page.id)
        if (config.candidates / f"{Path(slug).name}.json").is_file():
            continue
        raw_ref = page.meta.get("raw")
        if raw_ref and (page.path.parent / str(raw_ref)).resolve().is_file():
            out.append(page)
    return out


def spec() -> str:
    """The Phase A instructions, read from the file the Claude Code skill also uses.

    Single source of truth on purpose: if the API backend and the agent skill drifted,
    two users of the same tool would get differently-shaped candidates from the same
    transcript, and Phase B would have to guess which convention it was reading.
    """
    return templates.read("channel-to-kb/references/candidate-extraction.md",
                          kind="skills")


def extract_one(config: Config, page: Page, backend: Backend,
                system: str) -> ExtractResult:
    slug = str(page.meta.get("slug") or page.id)
    result = ExtractResult(slug=slug)

    raw_path = (page.path.parent / str(page.meta.get("raw"))).resolve()
    _, transcript = read_md(raw_path)

    user = (
        f"Transcript slug: {slug}\n"
        f"Title: {page.title}\n\n"
        "Return ONLY the JSON object described in the spec. No prose, no code fence.\n\n"
        f"--- TRANSCRIPT ---\n{transcript}"
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result.attempts = attempt
        try:
            raw = backend.complete(system, user)
        except Exception as exc:  # network, timeout, provider error
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        candidate = parse_json(raw)
        if candidate is None:
            result.error = "response was not JSON"
            continue

        kept, rejected = gate(candidate, transcript)
        result.rejected = rejected

        # No concepts is a legitimate outcome — a sponsor pitch has nothing in it.
        # Retry only when the gate threw work away, which means the model paraphrased.
        if rejected and kept == [] and attempt < MAX_ATTEMPTS:
            continue

        candidate["concepts"] = kept
        candidate.setdefault("slug", slug)
        candidate.setdefault("title", page.title)
        if not kept:
            candidate.setdefault("yield", "none")

        out = config.candidates / f"{Path(slug).name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

        result.written = True
        result.concepts = len(kept)
        try:
            ledger.record(config, slug, "extracted", by=f"ugraph extract ({backend.name})",
                          detail=f"{len(kept)} concepts, {len(rejected)} rejected")
        except Exception:  # bookkeeping must not fail a successful extraction
            pass
        return result

    result.error = result.error or "failed the verbatim gate on every attempt"
    return result


def run(config: Config, backend: Backend, limit: int = 10,
        progress: ProgressFn | None = None) -> dict[str, Any]:
    system = spec()
    batch = pending_sources(config)[:limit]

    results = []
    for i, page in enumerate(batch, 1):
        slug = str(page.meta.get("slug") or page.id)
        if progress:
            progress(i, len(batch), slug, page.title)
        results.append(extract_one(config, page, backend, system))

    return {
        "backend": backend.name,
        "attempted": len(results),
        "written": sum(1 for r in results if r.written),
        "concepts": sum(r.concepts for r in results),
        "rejected": sum(len(r.rejected) for r in results),
        "failed": [{"slug": r.slug, "error": r.error} for r in results if not r.written],
        "results": results,
    }
