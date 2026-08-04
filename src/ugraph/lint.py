"""
lint.py — the conformance gate for a knowledge base.

This is the executable half of SCHEMA.md. Errors block; warnings inform. It is what
makes a KB trustworthy enough for an agent to cite from: if the linter is green then
every link resolves, every page is reachable from an index, and every claim has a
traceable source.

Nothing here decides what to *do* about a finding — no exit codes, no printing, no
argument parsing. `lint(config)` returns a `Findings`; the CLI owns the verdict. That
split is what lets the same checks run from a pre-commit hook, a test, or a CI job.

Every check takes a `Config`, so a lint run is fully described by the KB it points at.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from ugraph.config import RESERVED_NAMES, Config
from ugraph.model import (
    CONDITIONAL_FIELDS,
    RELATION_HEADINGS,
    REQUIRED_FIELDS,
    VALID_CONFIDENCE,
    VALID_STATUS,
    VALID_SUBTYPES,
    Page,
    build_backlink_map,
    get_md_links,
    get_typed_edges,
    get_wikilinks,
    iter_pages,
    resolve_md_link,
)
from ugraph.store import State, iter_md, log, read_md

JOB_NAME = "lint"

STALE_SEED_DAYS = 90

# Pages exempt from the orphan check — they are entry points, not leaves.
ORPHAN_EXEMPT_TYPES = {"moc", "overview", "weekly_brief", "raw-transcript"}


class Findings:
    """Accumulates errors and warnings with a consistent shape."""

    def __init__(self):
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def error(self, check: str, file: str, message: str, **extra):
        self.errors.append({"check": check, "file": file, "message": message, **extra})

    def warn(self, check: str, file: str, message: str, **extra):
        self.warnings.append({"check": check, "file": file, "message": message, **extra})

    @property
    def total(self) -> int:
        return len(self.errors) + len(self.warnings)


# ---------------------------------------------------------------------------
# Path helpers — the only place that knows where the KB root is
# ---------------------------------------------------------------------------


def _rel(config: Config, path: Path) -> str:
    """KB-relative path for display. Falls back to the absolute path."""
    try:
        return str(Path(path).resolve().relative_to(config.kb.resolve()))
    except ValueError:
        return str(path)


def _under(path: Path, directory: Path) -> bool:
    """True if `path` sits anywhere beneath `directory`."""
    try:
        Path(path).resolve().relative_to(Path(directory).resolve())
    except ValueError:
        return False
    return True


def valid_domains(config: Config) -> set:
    """The closed set of domain names, from the KB's taxonomy."""
    return set((config.taxonomy().get("domains") or {}).keys())


def page_types(config: Config) -> dict:
    """Page type -> required frontmatter fields.

    The format defines concept, entity, source, raw-transcript, moc, overview and
    note. Real knowledge bases grow types the format never anticipated — a weekly
    digest, a meeting record, a reading log — and a linter that rejects them forces
    users to either abandon the type or fork the tool.

    So `page_types` in taxonomy.json extends this. Values are the required fields;
    `type` and `title` are added automatically since every page needs both:

        "page_types": { "weekly_brief": ["created"] }

    Extension is additive only — a taxonomy cannot weaken the requirements on a
    type the format already defines, because the rest of the toolchain relies on
    them.
    """
    types = {name: set(fields) for name, fields in REQUIRED_FIELDS.items()}
    for name, fields in (config.taxonomy().get("page_types") or {}).items():
        if name in REQUIRED_FIELDS:
            continue  # built-in types are not overridable
        types[name] = {"type", "title"} | set(fields or [])
    return types


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_frontmatter(config: Config, page: Page, f: Findings,
                      domains: Optional[set] = None):
    """Type declared, required fields present, closed vocabularies respected."""
    if domains is None:
        domains = valid_domains(config)
    rel = page.rel

    if not page.type:
        f.error("frontmatter", rel, "missing or empty `type` in frontmatter")
        return

    required = page_types(config).get(page.type)
    if required is None:
        f.error("frontmatter", rel,
                f"unknown page type `{page.type}` — add it to `page_types` in "
                f"taxonomy.json if this KB uses a type the format does not define")
        return

    missing = sorted(field for field in required
                     if field not in page.meta
                     or page.meta[field] in (None, "", []))
    if missing:
        f.error("frontmatter", rel,
                f"`{page.type}` missing required field(s): {', '.join(missing)}")

    # Conditional requirements (e.g. video sources need youtube_id/duration/raw).
    discriminator = page.meta.get("source_type") or page.meta.get("subtype")
    extra_required = CONDITIONAL_FIELDS.get((page.type, discriminator), set())
    missing_cond = sorted(field for field in extra_required
                          if field not in page.meta
                          or page.meta[field] in (None, "", []))
    if missing_cond:
        f.error("frontmatter", rel,
                f"`{page.type}/{discriminator}` missing: {', '.join(missing_cond)}")

    # Closed vocabularies.
    if page.type in {"concept", "entity"} and page.domain:
        if page.domain not in domains:
            f.error("taxonomy", rel,
                    f"domain `{page.domain}` is not in the taxonomy")

    if page.type == "concept":
        status = str(page.meta.get("status", "")).strip()
        if status and status not in VALID_STATUS:
            f.error("taxonomy", rel,
                    f"status `{status}` not one of {sorted(VALID_STATUS)}")

    if page.type == "entity":
        subtype = str(page.meta.get("subtype", "")).strip()
        if subtype and subtype not in VALID_SUBTYPES:
            f.error("taxonomy", rel,
                    f"subtype `{subtype}` not one of {sorted(VALID_SUBTYPES)}")

    confidence = str(page.meta.get("confidence", "")).strip()
    if confidence and confidence not in VALID_CONFIDENCE:
        f.error("taxonomy", rel,
                f"confidence `{confidence}` not one of {sorted(VALID_CONFIDENCE)}")

    # description should be one sentence — it is reused verbatim in indexes.
    desc = page.description
    if desc:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", desc) if s.strip()]
        if len(sentences) > 1:
            f.warn("style", rel,
                   f"`description` is {len(sentences)} sentences; indexes read best with one")
        if len(desc) > 200:
            f.warn("style", rel, f"`description` is {len(desc)} chars; aim for under 200")


def check_links(config: Config, page: Page, f: Findings):
    """Relative markdown links resolve; no wikilinks in the OKF directories.

    The no-wikilink rule applies to the OKF tree (concepts/, entities/, sources/,
    _mocs/) — the pages agents actually traverse. Notes elsewhere in the KB keep
    their wikilinks and get a warning instead, since they are read by humans in an
    editor, not walked by link-following agents.
    """
    rel = page.rel
    strict = config.is_okf_page(page.path)

    for wl in get_wikilinks(page.body):
        msg = (f"`[[{wl}]]` — wikilinks are not allowed in the OKF tree; "
               f"use a relative markdown link")
        if strict:
            f.error("links", rel, msg)
        else:
            f.warn("links", rel,
                   f"`[[{wl}]]` — legacy wikilink; fine for humans, invisible to "
                   f"link-following agents")

    for text, target in get_md_links(page.body):
        if resolve_md_link(page.path, target) is None:
            f.error("links", rel, f"broken link `[{text}]({target})`")


def check_raw_bijection(config: Config, page: Page, f: Findings):
    """Every source with a raw: path has that transcript on disk."""
    if page.type != "source":
        return
    raw_ref = page.meta.get("raw")
    if not raw_ref:
        return
    resolved = resolve_md_link(page.path, str(raw_ref))
    if resolved is None:
        f.error("provenance", page.rel,
                f"`raw:` points at `{raw_ref}` which does not exist")
    elif not _under(resolved, config.raw_dir):
        f.error("provenance", page.rel,
                f"`raw:` points outside raw/ — `{raw_ref}`")


def check_orphan_raw(config: Config, pages: Sequence[Page], f: Findings):
    """Every transcript in raw/ is claimed by exactly one source page."""
    claimed: dict[Path, list[str]] = defaultdict(list)
    for page in pages:
        if page.type != "source":
            continue
        raw_ref = page.meta.get("raw")
        if not raw_ref:
            continue
        resolved = resolve_md_link(page.path, str(raw_ref))
        if resolved:
            claimed[resolved.resolve()].append(page.rel)

    if not config.raw_dir.exists():
        return

    for transcript in iter_md(config.raw_dir):
        owners = claimed.get(transcript.resolve(), [])
        rel = _rel(config, transcript)
        if not owners:
            f.warn("provenance", rel, "transcript has no source page pointing at it")
        elif len(owners) > 1:
            f.error("provenance", rel,
                    f"transcript claimed by {len(owners)} source pages: {', '.join(owners)}")


def check_indexed(config: Config, pages: Sequence[Page], f: Findings):
    """Every concept/entity/source is listed in some index.md."""
    indexed: set[Path] = set()
    for index_file in sorted(config.kb.rglob("index.md")):
        content = index_file.read_text(encoding="utf-8", errors="replace")
        for _, target in get_md_links(content):
            resolved = resolve_md_link(index_file, target)
            if resolved:
                indexed.add(resolved.resolve())

    for page in pages:
        if not page.is_content:
            continue
        if page.path.resolve() not in indexed:
            f.error("index", page.rel,
                    "not listed in any index.md — run `ugraph index`")


def check_orphans(config: Config, pages: Sequence[Page], f: Findings):
    """Every content page has at least one inbound link from a non-index page."""
    backlinks = build_backlink_map(list(pages))

    # Index files are generated, so being linked only from an index isn't real
    # connectivity — recompute inbound links excluding index.md sources.
    inbound_non_index: dict[Path, int] = defaultdict(int)
    for target, sources in backlinks.items():
        for src in sources:
            if src.name != "index.md":
                inbound_non_index[target] += 1

    for page in pages:
        if not page.is_content or page.type in ORPHAN_EXEMPT_TYPES:
            continue
        if inbound_non_index.get(page.path.resolve(), 0) == 0:
            f.warn("graph", page.rel,
                   "orphan — no inbound links from any content page")


def check_bidirectional(config: Config, pages: Sequence[Page], f: Findings):
    """A typed edge A→B should be answered by some typed edge B→A.

    Reciprocity is checked loosely — B may link back under any typed heading,
    since most relations have no clean inverse heading. Provenance (`## Sources`)
    is exempt: a source never links forward to the pages that cite it.
    """
    by_path = {p.path.resolve(): p for p in pages}
    edges_cache = {p.path.resolve(): get_typed_edges(p) for p in pages}

    for page in pages:
        src = page.path.resolve()
        for heading, targets in edges_cache[src].items():
            if not RELATION_HEADINGS.get(heading, False):
                continue  # one-way by design
            for target in targets:
                resolved = resolve_md_link(page.path, target)
                if resolved is None or resolved.resolve() not in by_path:
                    continue  # broken links already reported by check_links
                # A typed section legitimately contains inline citations. Provenance is
                # one-way by definition — a source never links forward to the concepts
                # that cite it — so citations are not edges and must not be reciprocated.
                if (_under(resolved, config.sources)
                        or _under(resolved, config.raw_dir)):
                    continue
                target_page = by_path[resolved.resolve()]
                back_edges = edges_cache.get(resolved.resolve(), {})
                linked_back = any(
                    (r := resolve_md_link(target_page.path, t)) is not None
                    and r.resolve() == src
                    for back_heading, back_targets in back_edges.items()
                    if RELATION_HEADINGS.get(back_heading, False)
                    for t in back_targets
                )
                if not linked_back:
                    f.warn("graph", page.rel,
                           f"`## {heading.title()}` → {target} is one-way; "
                           f"{target_page.path.name} does not link back")


def check_staleness(config: Config, pages: Sequence[Page], f: Findings):
    """Seed pages that never grew."""
    cutoff = date.today() - timedelta(days=STALE_SEED_DAYS)
    for page in pages:
        if page.type != "concept":
            continue
        if str(page.meta.get("status", "")).strip() != "seed":
            continue
        updated = str(page.meta.get("updated", "") or page.meta.get("created", "")).strip()
        try:
            when = datetime.strptime(updated[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if when < cutoff:
            f.warn("staleness", page.rel,
                   f"status `seed` since {when.isoformat()} "
                   f"({(date.today() - when).days} days) — grow it or archive it")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def load_pages(config: Config, f: Optional[Findings] = None) -> list[Page]:
    """Every page in the KB, including raw transcripts.

    Unparseable frontmatter is a finding, not a crash. The bad files are found in a
    separate cheap pass because `iter_pages` is a generator: if it raised on the first
    malformed file, every page after it would silently vanish from the lint. One extra
    read per file is a fair price for reporting all of them.
    """
    if f is not None:
        for path in iter_md(config.kb):
            if path.name in RESERVED_NAMES:
                continue
            try:
                read_md(path)
            except Exception as exc:
                f.error("parse", _rel(config, path), f"cannot parse frontmatter: {exc}")

    pages: list[Page] = []
    walker = iter_pages(config, include_raw=True)
    while True:
        try:
            pages.append(next(walker))
        except StopIteration:
            break
        except Exception:
            break  # already reported above
    return pages


def lint(config: Config) -> tuple[Findings, list[Page]]:
    """Run every check. Returns (findings, pages) — see the note at the return."""
    f = Findings()
    domains = valid_domains(config)

    pages = load_pages(config, f)

    for page in pages:
        if _under(page.path, config.raw_dir):
            # Transcripts get frontmatter checks only — they contain no links.
            check_frontmatter(config, page, f, domains)
            continue
        check_frontmatter(config, page, f, domains)
        check_links(config, page, f)
        check_raw_bijection(config, page, f)

    content_pages = [p for p in pages if not _under(p.path, config.raw_dir)]
    check_indexed(config, content_pages, f)
    check_orphans(config, content_pages, f)
    check_bidirectional(config, content_pages, f)
    check_staleness(config, content_pages, f)
    check_orphan_raw(config, content_pages, f)

    state = State(config.state, JOB_NAME)
    state.record_run()
    state.set("errors_found", len(f.errors))
    state.set("warnings_found", len(f.warnings))
    state.set("pages", len(pages))
    state.checkpoint()
    log(config.logs, JOB_NAME,
        f"{'FAIL' if f.errors else 'PASS'} — {len(pages)} pages, "
        f"{len(f.errors)} error(s), {len(f.warnings)} warning(s)")

    # Pages come back with the findings because callers need the page count for a
    # verdict line and the page list for render_report(); re-walking the tree just to
    # recover them would double the I/O on the largest operation in the toolchain.
    return f, pages


def render_report(f: Findings, pages: Iterable[Page]) -> str:
    """Markdown summary of a lint run, grouped by check."""
    pages = list(pages)
    counts: dict[str, int] = defaultdict(int)
    for p in pages:
        counts[p.type or "(untyped)"] += 1

    status = "PASS" if not f.errors else "FAIL"
    lines = [
        f"# Knowledge Base Lint — {date.today().isoformat()}",
        "",
        f"**Status:** {status}  ",
        f"**Errors:** {len(f.errors)}  ",
        f"**Warnings:** {len(f.warnings)}  ",
        f"**Pages scanned:** {len(pages)}",
        "",
        "| Type | Count |",
        "|------|------:|",
    ]
    lines += [f"| {t} | {c} |" for t, c in sorted(counts.items())]
    lines += ["", "---", ""]

    for label, items in (("Errors", f.errors), ("Warnings", f.warnings)):
        lines += [f"## {label} ({len(items)})", ""]
        if not items:
            lines += ["None.", ""]
            continue
        by_check = defaultdict(list)
        for item in items:
            by_check[item["check"]].append(item)
        for check in sorted(by_check):
            lines += [f"### {check} ({len(by_check[check])})", ""]
            for item in by_check[check][:50]:
                lines.append(f"- `{item['file']}` — {item['message']}")
            if len(by_check[check]) > 50:
                lines.append(f"- _...and {len(by_check[check]) - 50} more_")
            lines.append("")

    return "\n".join(lines)
