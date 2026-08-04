"""
graph.py — export the knowledge base as a graph, for questions traversal cannot answer.

A knowledge base in this format already *is* a graph: pages are nodes, typed relationship
headings are labelled edges, and the linter enforces bidirectionality. What it lacks is a
query engine. Traversal answers "what relates to X"; it cannot answer "which concepts cite
only one source and sit in two clusters" without walking everything.

This module derives that graph so a real query tool can answer those. It deliberately does
NOT become one:

    markdown is the source of truth; the graph is a derived, disposable view

That direction matters. A graph database in the loop is a second system that can drift
from the files, needs its own migration story, and turns `git diff` into something you
cannot read. Regenerating a 64 KB export costs milliseconds, so there is no reason to keep
it authoritative.

At the scale this format targets — hundreds of nodes, not millions — the whole export fits
in a single model context. Handing an agent the entire graph is often simpler than giving
it a query language.

Usage:
    g = build(config)
    print(to_json(g))
    Path("kb.graphml").write_text(to_graphml(g))
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Optional

from okf.config import Config
from okf.model import (
    Page,
    get_md_links,
    get_typed_edges,
    iter_pages,
    resolve_md_link,
)

# Node attributes carried into every export format. Kept small on purpose — an export
# nobody can read in a viewer is no more useful than the directory it came from.
NODE_FIELDS = ("type", "title", "domain", "status", "confidence")

# Edges asserted by a typed heading carry that heading as their label. Everything else
# is an untyped reference, which is worth keeping but worth distinguishing.
RELATION_UNTYPED = "references"
RELATION_PROVENANCE = "cites_source"


def _node_id(config: Config, page: Page) -> str:
    """Stable identity: the KB-relative path minus .md, same as a page's `id`.

    Uses the same identity the links use, so an export can be joined back to the files
    it came from without a lookup table.
    """
    return page.id


def build(config: Config, include_provenance: bool = True) -> dict[str, Any]:
    """Derive nodes and edges from the knowledge base.

    `include_provenance` keeps edges from concepts to the sources they cite. Those are
    the majority of edges in a healthy KB and they are what makes "which ideas share
    evidence" answerable — but they also dominate a visual layout, so they can be
    dropped for diagramming.
    """
    pages = [p for p in iter_pages(config)]
    by_path = {p.path.resolve(): p for p in pages}

    nodes: list[dict[str, Any]] = []
    for page in pages:
        attrs = {"id": _node_id(config, page)}
        for field in NODE_FIELDS:
            value = page.meta.get(field)
            if value not in (None, "", []):
                attrs[field] = str(value)
        sources = page.meta.get("sources") or []
        if isinstance(sources, list) and sources:
            attrs["source_count"] = len(sources)
        nodes.append(attrs)

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for page in pages:
        src_id = _node_id(config, page)

        # Typed edges first, so a link that appears under a relationship heading is
        # labelled with that relationship rather than as a bare reference.
        typed_targets: dict[str, str] = {}
        for heading, targets in get_typed_edges(page).items():
            for target in targets:
                resolved = resolve_md_link(page.path, target)
                if resolved is None:
                    continue
                key = str(resolved.resolve())
                typed_targets.setdefault(key, heading)

        for text, target in get_md_links(page.body):
            resolved = resolve_md_link(page.path, target)
            if resolved is None:
                continue
            resolved_key = resolved.resolve()
            dest = by_path.get(resolved_key)
            if dest is None:
                continue  # link out of the KB, or to a raw transcript

            relation = typed_targets.get(str(resolved_key))
            if relation is None:
                relation = (RELATION_PROVENANCE if dest.type == "source"
                            else RELATION_UNTYPED)
            elif relation == "sources":
                relation = RELATION_PROVENANCE

            if relation == RELATION_PROVENANCE and not include_provenance:
                continue

            dst_id = _node_id(config, dest)
            key = (src_id, dst_id, relation)
            if key in seen:
                continue  # a page may cite the same target repeatedly
            seen.add(key)
            edges.append({"source": src_id, "target": dst_id, "relation": relation})

    return {
        "kb": str(config.kb),
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: (e["source"], e["target"], e["relation"])),
    }


# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------


def to_json(graph: dict[str, Any], indent: Optional[int] = 2) -> str:
    return json.dumps(graph, indent=indent, ensure_ascii=False)


def to_graphml(graph: dict[str, Any]) -> str:
    """GraphML — opens in Gephi, yEd, and imports into Neo4j.

    Attribute keys have to be declared up front in GraphML, so this collects the union
    of attributes actually present rather than assuming every node carries every field.
    """
    ns = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", ns)
    root = ET.Element(f"{{{ns}}}graphml")

    node_attrs = sorted({k for n in graph["nodes"] for k in n if k != "id"})
    for name in node_attrs:
        key = ET.SubElement(root, f"{{{ns}}}key")
        key.set("id", f"n_{name}")
        key.set("for", "node")
        key.set("attr.name", name)
        key.set("attr.type", "long" if name == "source_count" else "string")

    key = ET.SubElement(root, f"{{{ns}}}key")
    key.set("id", "e_relation")
    key.set("for", "edge")
    key.set("attr.name", "relation")
    key.set("attr.type", "string")

    g = ET.SubElement(root, f"{{{ns}}}graph")
    g.set("id", "kb")
    g.set("edgedefault", "directed")

    for node in graph["nodes"]:
        el = ET.SubElement(g, f"{{{ns}}}node")
        el.set("id", node["id"])
        for name in node_attrs:
            if name in node:
                data = ET.SubElement(el, f"{{{ns}}}data")
                data.set("key", f"n_{name}")
                data.text = str(node[name])

    for i, edge in enumerate(graph["edges"]):
        el = ET.SubElement(g, f"{{{ns}}}edge")
        el.set("id", f"e{i}")
        el.set("source", edge["source"])
        el.set("target", edge["target"])
        data = ET.SubElement(el, f"{{{ns}}}data")
        data.set("key", "e_relation")
        data.text = edge["relation"]

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )


def to_dot(graph: dict[str, Any]) -> str:
    """Graphviz DOT. Nodes are coloured by type so the shape of the KB is legible."""
    colours = {
        "concept": "#2b6cb0",
        "entity": "#2f855a",
        "source": "#975a16",
        "moc": "#6b46c1",
        "overview": "#4a5568",
    }

    def esc(text: str) -> str:
        return str(text).replace('"', '\\"')

    lines = ["digraph kb {", '  graph [rankdir=LR, overlap=false, splines=true];',
             '  node [shape=box, style="rounded,filled", fontname="Helvetica",'
             ' fontsize=10, fillcolor="#ffffff"];',
             '  edge [fontname="Helvetica", fontsize=8, color="#a0aec0"];']

    for node in graph["nodes"]:
        colour = colours.get(node.get("type", ""), "#4a5568")
        label = esc(node.get("title", node["id"]))
        lines.append(f'  "{esc(node["id"])}" [label="{label}", color="{colour}"];')

    for edge in graph["edges"]:
        label = "" if edge["relation"] == RELATION_UNTYPED else edge["relation"]
        attr = f' [label="{esc(label)}"]' if label else ""
        lines.append(f'  "{esc(edge["source"])}" -> "{esc(edge["target"])}"{attr};')

    lines.append("}")
    return "\n".join(lines) + "\n"


FORMATS = {"json": to_json, "graphml": to_graphml, "dot": to_dot}


def render(graph: dict[str, Any], fmt: str = "json") -> str:
    try:
        return FORMATS[fmt](graph)
    except KeyError:
        raise ValueError(
            f"unknown format {fmt!r}; expected one of {', '.join(sorted(FORMATS))}"
        ) from None
