"""
model.py — Open Knowledge Format primitives: pages, links, and typed edges.

store.py is the filesystem layer; config.py says where the knowledge base lives.
This module is the format-specific layer on top: page-type contracts,
relative-markdown-link resolution, typed relationship edges, and taxonomy access.
Every page in a KB obeys SCHEMA.md; this file is the executable half of that spec.

Nothing here reads a global root. Anything that needs to know where the KB is takes
a Config, which is what makes the same code work against someone else's vault.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from ugraph.config import RESERVED_NAMES, Config
from ugraph.store import iter_md, read_md

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


def valid_domains(config: Config) -> set[str]:
    """The closed set of domain slugs a concept may declare."""
    return set(config.taxonomy()["domains"].keys())


# ---------------------------------------------------------------------------
# Page-type contracts (mirrors SCHEMA.md — keep both in sync)
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "concept": {"type", "title", "description", "domain", "status", "created", "updated"},
    "entity": {"type", "subtype", "title", "description", "created", "updated"},
    "source": {"type", "source_type", "title", "description", "slug", "created", "updated"},
    "raw-transcript": {"type", "immutable", "slug"},
    "moc": {"type", "title"},
    "overview": {"type", "title"},
    # Human-facing notes that sit outside the traversable graph — link tables,
    # trackers, reading lists. Held to almost no contract on purpose.
    "note": {"type", "title"},
}

# Extra fields required only for a particular subtype/source_type.
CONDITIONAL_FIELDS = {
    ("source", "video"): {"youtube_id", "url", "published", "duration", "raw"},
}

VALID_STATUS = {"seed", "growing", "evergreen"}
VALID_SUBTYPES = {"tool", "person", "organization"}
VALID_CONFIDENCE = {"high", "medium", "low"}

# Typed relationship headings -> whether the edge is expected to be reciprocated.
#
# There is no clean inverse heading for most of these ("A builds on B" does not make
# B "a prerequisite of A" in the authoring sense), so reciprocity is checked loosely:
# if A links to B under a typed heading, B must link back to A under *some* typed
# heading. Provenance is the exception — sources never link forward to their readers.
RELATION_HEADINGS = {
    "prerequisites": True,
    "builds on": True,
    "part of": True,
    "contrasts with": True,
    "implemented by": True,
    "tools": True,
    "related": True,
    "sources": False,
}


# ---------------------------------------------------------------------------
# Page model
# ---------------------------------------------------------------------------


class Page:
    """A single OKF page: path + parsed frontmatter + body, bound to its KB."""

    def __init__(self, path: str | Path, config: Config):
        self.path = Path(path)
        self.config = config
        self.meta, self.body = read_md(self.path)

    # -- identity ----------------------------------------------------------

    @property
    def rel(self) -> str:
        """Path relative to the KB root, POSIX-separated.

        POSIX separators even on Windows: this string is the page's identity and
        appears in links, so it has to be the same on every machine.
        """
        try:
            return self.path.resolve().relative_to(self.config.kb.resolve()).as_posix()
        except ValueError:  # a page loaded from outside the KB still needs a name
            return self.path.as_posix()

    @property
    def id(self) -> str:
        """Stable identity: KB-relative path minus .md."""
        rel = self.rel
        return rel.removesuffix(".md")

    # -- typed fields ------------------------------------------------------

    @property
    def type(self) -> str:
        return str(self.meta.get("type", "")).strip()

    @property
    def title(self) -> str:
        return str(self.meta.get("title", self.path.stem))

    @property
    def description(self) -> str:
        return str(self.meta.get("description", "")).strip()

    @property
    def domain(self) -> str:
        return str(self.meta.get("domain", "")).strip()

    @property
    def is_content(self) -> bool:
        """True for concept/entity/source pages — the ones that must be indexed."""
        return self.type in {"concept", "entity", "source"}

    def __repr__(self) -> str:
        return f"<Page {self.id} type={self.type}>"


def page_paths(config: Config, root: str | Path | None = None,
               include_raw: bool = False) -> Iterator[Path]:
    """Yield the path of every page the KB considers content.

    Split out from `iter_pages` so a caller that needs to survive unparseable files —
    the linter, chiefly — can walk paths itself and decide what a parse failure means.
    """
    root = Path(root) if root else config.kb
    raw_dir = config.raw_dir.resolve()
    for path in iter_md(root):
        if path.name in RESERVED_NAMES:
            continue
        if not include_raw and raw_dir in path.resolve().parents:
            continue
        yield path


def iter_pages(config: Config, root: str | Path | None = None,
               include_raw: bool = False, strict: bool = True) -> Iterator[Page]:
    """Yield every OKF page under the KB (or a subdirectory of it).

    Skips reserved files (index.md, SCHEMA.md, README.md) and, unless asked,
    the raw/ transcript tree.

    `strict=True` raises on unparseable frontmatter. `strict=False` skips it — which
    a caller must choose deliberately, because silently dropping pages from a
    structural check produces a confident answer about a KB that was never fully read.
    """
    for path in page_paths(config, root, include_raw):
        try:
            yield Page(path, config)
        except Exception as exc:  # malformed YAML
            if strict:
                raise ValueError(f"Cannot parse {path}: {exc}") from exc
            continue


def load_page(path: str | Path, config: Config) -> Page:
    return Page(path, config)


def concept_registry(config: Config, include_entities: bool = True) -> dict[str, dict]:
    """Compact map of every concept/entity page that already exists.

    This is the dedup baseline for the extraction pass. Canonicalization fails silently
    when the writer can't see that a candidate already has a home, so this returns title
    *and* description — a title alone ("receipts") often doesn't reveal that a page
    covers the same idea under a different name.

    Small enough to paste whole into a prompt: ~120 bytes per page.
    """
    registry: dict[str, dict] = {}
    for page in iter_pages(config):
        if page.type == "concept" or (include_entities and page.type == "entity"):
            registry[page.id] = {
                "title": page.title,
                "description": page.description,
                "type": page.type,
                "domain": page.domain,
                "sources": list(page.meta.get("sources") or []),
            }
    return registry


def registry_digest(config: Config) -> str:
    """concept_registry() rendered as compact lines for a prompt."""
    lines = []
    for pid, info in sorted(concept_registry(config).items()):
        kind = info["type"]
        n = len(info["sources"])
        lines.append(f"- {pid} [{kind}, {n} source{'s' if n != 1 else ''}] "
                     f"{info['title']} — {info['description']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

# [text](target)  — excludes images ![...](...) and bare autolinks
_MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]*)\]\(([^)\s]+?)(?:\s+\"[^\"]*\")?\)")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_EXTERNAL_RE = re.compile(r"^(https?:|mailto:|tel:|#)")


def _strip_code(content: str) -> str:
    """Remove fenced and inline code so examples in docs aren't linted as links."""
    content = _CODE_FENCE_RE.sub("", content)
    return _INLINE_CODE_RE.sub("", content)


def get_md_links(content: str, strip_code: bool = True) -> list[tuple[str, str]]:
    """Extract [(display_text, target)] for every relative markdown link.

    External links (http://, https://, mailto:) are excluded — only intra-KB
    edges are returned.
    """
    if strip_code:
        content = _strip_code(content)
    links = []
    for text, target in _MD_LINK_RE.findall(content):
        if _EXTERNAL_RE.match(target):
            continue
        links.append((text, target))
    return links


def get_wikilinks(content: str, strip_code: bool = True) -> list[str]:
    """Extract [[wikilink]] targets. Inside the strict OKF tree these are schema
    errors: a wikilink only resolves inside the tool that invented it, and the
    format's premise is that a plain filesystem is enough to follow an edge."""
    if strip_code:
        content = _strip_code(content)
    return _WIKILINK_RE.findall(content)


def resolve_md_link(from_path: str | Path, target: str) -> Path | None:
    """Resolve a relative markdown link against the file that contains it.

    Returns the resolved Path if it exists on disk, else None.
    """
    target = target.split("#")[0].strip()
    if not target:
        return None
    candidate = (Path(from_path).parent / target).resolve()
    if candidate.exists():
        return candidate
    if candidate.suffix != ".md" and candidate.with_suffix(".md").exists():
        return candidate.with_suffix(".md")
    return None


def relpath_between(from_path: str | Path, to_path: str | Path) -> str:
    """Build the relative markdown link from one page to another (POSIX separators)."""
    rel = os.path.relpath(Path(to_path).resolve(), Path(from_path).resolve().parent)
    return Path(rel).as_posix()


# ---------------------------------------------------------------------------
# Typed relationship edges
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)


def get_typed_edges(page: Page) -> dict[str, list[str]]:
    """Map each typed relationship heading to the link targets beneath it.

    Returns {"prerequisites": ["../concepts/context-window.md", ...], ...}
    using lowercased heading names. Only headings listed in RELATION_HEADINGS
    are returned.
    """
    body = _strip_code(page.body)
    edges: dict[str, list[str]] = {}

    matches = list(_HEADING_RE.finditer(body))
    for i, m in enumerate(matches):
        heading = m.group(2).strip().lower()
        if heading not in RELATION_HEADINGS:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section = body[start:end]
        targets = [t for _, t in get_md_links(section, strip_code=False)]
        if targets:
            edges.setdefault(heading, []).extend(targets)

    return edges


def build_backlink_map(pages: list[Page]) -> dict[Path, set[Path]]:
    """{target_path: {source_paths that link to it}} across the whole KB."""
    backlinks: dict[Path, set[Path]] = {}
    for page in pages:
        for _, target in get_md_links(page.body):
            resolved = resolve_md_link(page.path, target)
            if resolved:
                backlinks.setdefault(resolved, set()).add(page.path.resolve())
    return backlinks
