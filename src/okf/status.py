"""
status.py — where the knowledge base extraction actually stands.

`lint` answers "is it valid?". This answers "how much is done?" — which sources are
extracted, which transcripts have candidates waiting, and how the concept graph is
distributed. Built for the cluster-by-cluster extraction workflow, where the question
between batches is always "what's left and what should I do next?".

The module is split in two on purpose:

    collect(config) -> dict     every number, no formatting
    render(stats, ...) -> str   one terminal view of those numbers

Nothing here prints. `collect()` is the part worth reusing — a dashboard, a CI check
that fails when canonicalization regresses, or a test asserting on counts all want the
numbers and none of them want a progress bar. The CLI owns argument parsing and output.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from okf.config import Config
from okf.model import Page, iter_pages

__all__ = ["collect", "render"]


# ---------------------------------------------------------------------------
# Gathering
# ---------------------------------------------------------------------------


def _pages(config: Config, root: Path | None = None) -> Iterable[Page]:
    """Single adapter onto the model layer, so the traversal call lives in one
    place rather than being spread across every counter below."""
    return iter_pages(config, root)


def _load_sources(config: Config) -> list[Page]:
    if not config.sources.is_dir():
        return []
    return [p for p in _pages(config, config.sources) if p.type == "source"]


def _load_candidates(config: Config) -> tuple[dict[str, dict], list[str]]:
    """Return ({stem: parsed}, [stems that could not be read]).

    Candidate files are Phase A working output and may be observed mid-write, so an
    unreadable or half-written file is reported, never raised. Anything that does not
    parse to an object is counted as broken too: the rest of this module treats a
    candidate as a mapping, and a bare list would only fail further downstream.
    """
    parsed: dict[str, dict] = {}
    broken: list[str] = []
    if not config.candidates.is_dir():
        return parsed, broken
    for path in sorted(config.candidates.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # JSONDecodeError and UnicodeDecodeError included
            broken.append(path.stem)
            continue
        if isinstance(data, dict):
            parsed[path.stem] = data
        else:
            broken.append(path.stem)
    return parsed, broken


def _raw_size(source: Page) -> int:
    """Bytes of the transcript a source page points at, 0 if unknown or missing."""
    raw = source.meta.get("raw")
    if not raw:
        return 0
    try:
        path = (source.path.parent / str(raw)).resolve()
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _count_transcripts(config: Config) -> int:
    if not config.raw_dir.is_dir():
        return 0
    return sum(1 for _ in config.raw_dir.rglob("*.md"))


def collect(config: Config) -> dict[str, Any]:
    """Every number the status views need, and no presentation.

    Returned keys are stable and JSON-serializable, which is what makes this usable
    from something other than a terminal.
    """
    sources = _load_sources(config)
    candidates, broken = _load_candidates(config)

    extracted = [s for s in sources if str(s.meta.get("summary_status", "")) == "done"]
    extracted_ids = {id(s) for s in extracted}
    pending = [s for s in sources if id(s) not in extracted_ids]

    pages = list(_pages(config))
    concepts = [p for p in pages if p.type == "concept"]
    entities = [p for p in pages if p.type == "entity"]

    # Distribution of concepts by how many sources back them. This is the health
    # signal for canonicalization: a concept with 1 source is a merge candidate —
    # probably the same idea already living under another name — while 3+ sources
    # means the concept has been corroborated and is well-canonicalized. A histogram
    # that stays piled up at 1 means extraction is producing duplicates, not knowledge.
    source_counts = Counter(len(p.meta.get("sources") or []) for p in concepts)

    clusters: dict[str, dict[str, int]] = {}
    for candidate in candidates.values():
        key = str(candidate.get("cluster_hint") or "other")
        bucket = clusters.setdefault(key, {"talks": 0, "candidates": 0})
        bucket["talks"] += 1
        bucket["candidates"] += len(candidate.get("concepts") or [])

    pending_rows = [
        {
            "title": s.title,
            "size": _raw_size(s),
            "has_candidate": s.path.stem in candidates,
        }
        for s in pending
    ]
    pending_rows.sort(key=lambda r: (-r["size"], r["title"]))

    thin = [
        {"title": p.title, "domain": p.domain}
        for p in concepts
        if len(p.meta.get("sources") or []) <= 1
    ]
    thin.sort(key=lambda r: r["title"])

    return {
        "sources_total": len(sources),
        "extracted": len(extracted),
        "pending_total": len(pending),
        "candidates": len(candidates),
        "broken_candidates": broken,
        "concepts": len(concepts),
        "entities": len(entities),
        "transcripts": _count_transcripts(config),
        "source_counts": {int(n): int(c) for n, c in sorted(source_counts.items())},
        "yields": dict(sorted(
            Counter(str(c.get("yield", "?")) for c in candidates.values()).items()
        )),
        "candidate_concepts": sum(
            len(c.get("concepts") or []) for c in candidates.values()
        ),
        "clusters": clusters,
        "pending": pending_rows,
        "thin": thin,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _bar(done: int, total: int, width: int = 32) -> str:
    if total == 0:
        return "─" * width
    filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled)


def render(
    stats: dict[str, Any],
    clusters: bool = False,
    pending: bool = False,
    thin: bool = False,
) -> str:
    """Format `collect()` output for a terminal. The three flags add detail views."""
    total = stats["sources_total"]
    out: list[str] = []

    out.append("Knowledge Base Status")
    out.append("=" * 58)
    out.append(f"  Sources extracted   {_bar(stats['extracted'], total)}  "
               f"{stats['extracted']}/{total}")
    out.append(f"  Candidates ready    {_bar(stats['candidates'], total)}  "
               f"{stats['candidates']}/{total}")
    out.append("")
    out.append(f"  Concepts  {stats['concepts']}   Entities  {stats['entities']}   "
               f"Transcripts  {stats['transcripts']}")

    broken = stats["broken_candidates"]
    if broken:
        out.append("")
        out.append(f"  [!] {len(broken)} candidate file(s) unparseable "
                   f"(may be mid-write): {', '.join(broken[:4])}"
                   + (" …" if len(broken) > 4 else ""))

    if stats["source_counts"]:
        out.append("")
        out.append("  Concepts by source count "
                   "(1 = merge candidate, 3+ = well-canonicalized)")
        for n, count in sorted(stats["source_counts"].items()):
            label = f"{n} source" + ("s" if n != 1 else "")
            out.append(f"    {label:<12} {'▪' * count}  {count}")

    if stats["yields"]:
        summary = "  ".join(f"{k}={v}" for k, v in sorted(stats["yields"].items()))
        out.append("")
        out.append(f"  Candidate yield: {summary}   "
                   f"({stats['candidate_concepts']} raw concept candidates)")

    if clusters:
        out.append("")
        out.append("  By cluster")
        by_cluster = stats["clusters"]
        if not by_cluster:
            out.append("    (no candidates extracted yet)")
        for key in sorted(by_cluster, key=lambda k: (-by_cluster[k]["talks"], k)):
            row = by_cluster[key]
            out.append(f"    {key:<18} {row['talks']:>3} talks  "
                       f"{row['candidates']:>3} candidate concepts")

    if pending:
        rows = stats["pending"]
        out.append("")
        out.append(f"  Pending sources ({len(rows)}), largest transcript first")
        for row in rows:
            mark = "✓" if row["has_candidate"] else " "
            out.append(f"    [{mark}] {row['size'] // 1024:>4}K  {row['title'][:62]}")

    if thin:
        rows = stats["thin"]
        out.append("")
        out.append(f"  Single-source concepts ({len(rows)}) — merge targets")
        for row in rows:
            out.append(f"    {row['title']:<44} {row['domain']}")

    out.append("")
    return "\n".join(out)
