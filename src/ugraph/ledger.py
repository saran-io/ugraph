"""
ledger.py — where every source is in its lifecycle, and how it got there.

A knowledge base accumulates material faster than it processes it. `ugraph status` answers
"how much is done"; this answers "where is *this* item, and what is stuck". Those are
different questions and the second one is what you need to decide what to work on.

## Two halves, deliberately split

**State is derived, never stored.** A `stage:` field in frontmatter would be a second
source of truth, and it would drift the first time somebody edits a page by hand — which
in this format happens constantly. Deriving from the files means the ledger cannot lie
about the present, even if the log is lost.

**Transitions are appended to a log.** Derivation cannot say *when* something was pulled,
how long it has been sitting, or what failed on the way. That needs history, and history
has to be written as it happens.

## Why this needs no per-source-type code

Every ingest adapter writes the same two files — `raw/<channel>/<slug>.md` and
`sources/<channel>/<slug>.md` — and the slug is the format's universal identity. A blog,
newsletter or saved-thread adapter therefore appears in the ledger the day it lands,
with nothing added here. That is the entire reason this keys on the slug rather than on
anything video-shaped.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from ugraph.config import Config
from ugraph.model import Page, get_typed_edges, iter_pages
from ugraph.store import read_md

LEDGER_FILENAME = "ledger.jsonl"

# The happy path, in order. `index()` of a stage is its progress rank, so "furthest
# stage reached" is a max() rather than a pile of conditionals.
STAGES = ["discovered", "pulled", "extracted", "synthesized", "linked", "verified"]

# Outcomes that are not progress. `skipped` is a legitimate end state — a talk with no
# transferable content should stop here rather than be nagged about forever.
TERMINAL = {"skipped"}
PROBLEM = {"orphaned"}

STAGE_GLYPH = {
    "discovered": "·", "pulled": "▪", "extracted": "▪▪", "synthesized": "▪▪▪",
    "linked": "▪▪▪▪", "verified": "▪▪▪▪▪", "skipped": "—", "orphaned": "!",
}


@dataclass
class Item:
    """One source, and everything known about where it is."""

    slug: str
    title: str = ""
    channel: str = ""
    kind: str = ""           # source_type: video, article, thread, talk…
    stage: str = "discovered"
    pulled: bool = False
    extracted: bool = False
    synthesized: bool = False
    linked: bool = False
    concepts: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    first_seen: Optional[str] = None
    last_change: Optional[str] = None
    age_days: Optional[int] = None

    @property
    def done(self) -> bool:
        return self.stage in {"linked", "verified"} or self.stage in TERMINAL

    @property
    def stuck(self) -> bool:
        """Pulled, went no further, and has been sitting a while."""
        return self.pulled and not self.synthesized and self.stage not in TERMINAL


# ---------------------------------------------------------------------------
# Transition log
# ---------------------------------------------------------------------------


def ledger_path(config: Config) -> Path:
    return Path(config.state) / LEDGER_FILENAME


def record(config: Config, slug: str, stage: str, by: str = "",
           detail: str = "") -> dict[str, Any]:
    """Append one transition.

    JSONL rather than a JSON document because appends are atomic enough under
    concurrent writers and the file stays readable with `tail`. A ledger you cannot
    inspect with ordinary tools is a ledger nobody checks.
    """
    if stage not in STAGES and stage not in TERMINAL and stage not in PROBLEM:
        known = ", ".join(STAGES + sorted(TERMINAL))
        raise ValueError(f"unknown stage {stage!r}; expected one of {known}")

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "slug": slug, "stage": stage, "by": by, "detail": detail,
    }
    path = ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def history(config: Config, slug: Optional[str] = None) -> list[dict[str, Any]]:
    """Read transitions back, oldest first. A corrupt line is skipped, not fatal —
    losing one entry is recoverable; refusing to open the ledger is not."""
    path = ledger_path(config)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if slug is None or entry.get("slug") == slug:
            out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def _mtime(path: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime,
                                      timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return None


def collect(config: Config) -> list[Item]:
    """Derive the current lifecycle state of every source."""
    pages = list(iter_pages(config))
    sources = [p for p in pages if p.type == "source"]
    concepts = [p for p in pages if p.type in {"concept", "entity"}]

    # Which sources does each concept cite, and does that concept carry typed edges?
    cites: dict[str, list[str]] = defaultdict(list)
    has_edges: dict[str, bool] = {}
    for page in concepts:
        typed = sum(len(v) for k, v in get_typed_edges(page).items() if k != "sources")
        has_edges[page.id] = typed > 0
        for slug in (page.meta.get("sources") or []):
            cites[str(slug)].append(page.id)

    transitions = history(config)
    by_slug: dict[str, list[dict]] = defaultdict(list)
    for entry in transitions:
        by_slug[entry.get("slug", "")].append(entry)

    now = datetime.now(timezone.utc)
    items: list[Item] = []

    for page in sources:
        slug = str(page.meta.get("slug") or page.id)
        item = Item(
            slug=slug,
            title=page.title,
            channel=str(page.meta.get("channel") or ""),
            kind=str(page.meta.get("source_type") or ""),
        )

        raw_ref = page.meta.get("raw")
        raw_path = None
        if raw_ref:
            raw_path = (page.path.parent / str(raw_ref)).resolve()
            item.pulled = raw_path.is_file()
        elif item.kind == "video":
            # A video is expected to have a transcript; anything else legitimately
            # may not, so absence is only an issue for the type that promises one.
            item.issues.append("video source with no `raw:` transcript")

        cand = config.candidates / f"{Path(slug).name}.json"
        item.extracted = cand.is_file()

        fed = cites.get(slug, [])
        item.concepts = sorted(fed)
        item.synthesized = (
            str(page.meta.get("summary_status", "")) == "done" and bool(fed)
        )
        item.linked = any(has_edges.get(cid) for cid in fed)

        # Furthest stage reached wins, so a later stage is never masked by an earlier
        # one being unrecorded.
        reached = ["discovered"]
        if item.pulled:
            reached.append("pulled")
        if item.extracted:
            reached.append("extracted")
        if item.synthesized:
            reached.append("synthesized")
        if item.linked:
            reached.append("linked")
        item.stage = max(reached, key=STAGES.index)

        # Synthesized with nothing behind it: the page asserts claims that cannot be
        # checked against a transcript. Worth surfacing above ordinary progress.
        if item.synthesized and not item.pulled:
            item.stage = "orphaned"
            item.issues.append("cited by concepts but never pulled — quotes unverifiable")

        events = by_slug.get(slug, [])
        if events:
            item.first_seen = events[0].get("ts")
            item.last_change = events[-1].get("ts")
        else:
            # Fall back to file mtime so the ledger is useful on a KB that predates
            # it, rather than only for items processed after it was switched on.
            item.first_seen = _mtime(page.path)
            item.last_change = _mtime(raw_path) if raw_path else item.first_seen

        if item.last_change:
            try:
                seen = datetime.fromisoformat(item.last_change)
                item.age_days = max((now - seen).days, 0)
            except ValueError:
                pass

        items.append(item)

    items.sort(key=lambda i: (STAGES.index(i.stage) if i.stage in STAGES else -1,
                              i.slug))
    return items


def summary(items: Iterable[Item]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item.stage] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_table(items: list[Item], limit: Optional[int] = None) -> str:
    """Compact terminal view."""
    if not items:
        return "  no sources yet — run `ugraph ingest`"

    counts = summary(items)
    lines = [f"  {len(items)} sources", ""]
    for stage in STAGES + sorted(TERMINAL | PROBLEM):
        if stage in counts:
            lines.append(f"    {STAGE_GLYPH.get(stage, ' '):<6} {stage:<13} "
                         f"{counts[stage]:>4}")
    lines.append("")

    shown = items[:limit] if limit else items
    width = max((len(i.slug) for i in shown), default=10)
    width = min(width, 62)
    for item in shown:
        flag = "!" if item.issues else " "
        age = f"{item.age_days}d" if item.age_days is not None else ""
        lines.append(f"  {flag} {STAGE_GLYPH.get(item.stage, ''):<6} "
                     f"{item.stage:<12} {item.slug[:width]:<{width}} {age:>5}")
    if limit and len(items) > limit:
        lines.append(f"    … and {len(items) - limit} more")
    return "\n".join(lines)


def render_markdown(items: list[Item], config: Config) -> str:
    """Report written into the logs directory.

    Markdown rather than CSV because the logs directory usually sits inside an
    Obsidian vault, and a status report nobody opens is not a status report.
    """
    counts = summary(items)
    now = datetime.now(timezone.utc)
    done = sum(1 for i in items if i.done)

    lines = [
        "---",
        "type: overview",
        'title: "Pipeline ledger"',
        f'description: "Lifecycle state of every source — {done} of {len(items)} complete."',
        f"generated: {now.date().isoformat()}",
        "---",
        "",
        "# Pipeline ledger",
        "",
        f"_Generated by `ugraph ledger --write` on {now.strftime('%Y-%m-%d %H:%M UTC')}._",
        "Derived from the filesystem, so it cannot disagree with what is actually there.",
        "",
        "## Where everything is",
        "",
        "| Stage | Count | Meaning |",
        "|---|---:|---|",
    ]
    meaning = {
        "discovered": "known to exist, not fetched",
        "pulled": "raw content on disk, nothing extracted yet",
        "extracted": "candidates emitted, not yet synthesized",
        "synthesized": "fed at least one concept page",
        "linked": "its concepts carry typed relationships",
        "verified": "quotes checked against the transcript",
        "skipped": "no transferable content — a valid outcome",
        "orphaned": "cited by concepts but never pulled",
    }
    for stage in STAGES + sorted(TERMINAL | PROBLEM):
        if stage in counts:
            lines.append(f"| `{stage}` | {counts[stage]} | {meaning.get(stage, '')} |")

    flagged = [i for i in items if i.issues]
    if flagged:
        lines += ["", "## Needs attention", ""]
        for item in flagged:
            lines.append(f"- **{item.title or item.slug}** — {'; '.join(item.issues)}")

    backlog = [i for i in items if i.stuck]
    if backlog:
        backlog.sort(key=lambda i: -(i.age_days or 0))
        lines += ["", f"## Pulled but unprocessed ({len(backlog)})", "",
                  "Oldest first — these are the next thing to work on.", "",
                  "| Age | Source | Kind |", "|---:|---|---|"]
        for item in backlog[:40]:
            age = f"{item.age_days}d" if item.age_days is not None else "—"
            lines.append(f"| {age} | {item.title or item.slug} | {item.kind} |")
        if len(backlog) > 40:
            lines.append(f"\n_…and {len(backlog) - 40} more._")

    complete = [i for i in items if i.done and not i.issues]
    if complete:
        lines += ["", f"## Complete ({len(complete)})", "",
                  "| Source | Concepts fed |", "|---|---:|"]
        for item in sorted(complete, key=lambda i: -len(i.concepts))[:40]:
            lines.append(f"| {item.title or item.slug} | {len(item.concepts)} |")

    return "\n".join(lines) + "\n"


def write_report(config: Config, items: Optional[list[Item]] = None) -> Path:
    items = items if items is not None else collect(config)
    path = Path(config.logs) / "ledger.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(items, config), encoding="utf-8")
    return path


def to_json(items: list[Item]) -> str:
    return json.dumps([asdict(i) for i in items], indent=2, ensure_ascii=False)
