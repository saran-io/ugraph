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

from ugraph.config import Config
from ugraph.model import (
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


def build(config: Config, include_provenance: bool = True,
          types: Optional[set[str]] = None) -> dict[str, Any]:
    """Derive nodes and edges from the knowledge base.

    `include_provenance` keeps edges from concepts to the sources they cite. Those are
    the majority of edges in a healthy KB and they are what makes "which ideas share
    evidence" answerable — but they also dominate a visual layout, so they can be
    dropped for diagramming.

    `types` restricts which page types become nodes. A KB usually has far more sources
    than concepts — 153 against 57 here — so an unfiltered visual is mostly provenance
    and the idea structure disappears into it. Analysis wants everything; a picture
    usually wants `{"concept", "entity", "moc"}`.
    """
    pages = [p for p in iter_pages(config)]
    if types:
        pages = [p for p in pages if p.type in types]
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


# ---------------------------------------------------------------------------
# Layout — needed by formats that store coordinates rather than compute them
# ---------------------------------------------------------------------------

# Domain colours, shared by every visual format so a concept is the same colour
# whichever way you look at it.
DOMAIN_COLOURS = {
    "agentic_systems": "#3d6fd6",
    "ai_engineering": "#c47b1e",
    "rag": "#1f8f76",
    "system_design": "#8355c4",
    "machine_learning": "#c0435f",
    "product": "#c2185b",
}
DEFAULT_COLOUR = "#8a91a0"


def layout(graph: dict[str, Any], iterations: int = 420,
           seed: int = 7) -> dict[str, tuple[float, float]]:
    """Force-directed positions, deterministic for a given graph.

    Obsidian Canvas stores coordinates rather than computing them, so a layout has to
    exist before the file is written. Determinism matters more than optimality here:
    re-exporting after adding one concept should nudge the picture, not reshuffle it,
    or the canvas becomes unreadable every time the KB grows.
    """
    import math
    import random

    rng = random.Random(seed)
    ids = [n["id"] for n in graph["nodes"]]
    if not ids:
        return {}

    index = {nid: i for i, nid in enumerate(ids)}
    # Seed on a ring grouped by domain, so the simulation refines real structure
    # instead of untangling noise.
    domains = sorted({n.get("domain", "") for n in graph["nodes"]})
    pos = []
    for i, node in enumerate(graph["nodes"]):
        g = domains.index(node.get("domain", ""))
        angle = (g / max(len(domains), 1)) * math.tau + (i % 13) * 0.11
        radius = 320 + (i % 9) * 40
        pos.append([math.cos(angle) * radius, math.sin(angle) * radius])

    links = [(index[e["source"]], index[e["target"]], e["relation"])
             for e in graph["edges"]
             if e["source"] in index and e["target"] in index]

    vel = [[0.0, 0.0] for _ in ids]
    alpha = 1.0
    for _ in range(iterations):
        alpha *= 0.99
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                dx = pos[j][0] - pos[i][0]
                dy = pos[j][1] - pos[i][1]
                d2 = dx * dx + dy * dy
                if d2 < 0.01:
                    dx, dy = rng.uniform(-1, 1), rng.uniform(-1, 1)
                    d2 = 1.0
                d = math.sqrt(d2)
                f = (90000.0 * alpha) / d2
                fx, fy = (dx / d) * f, (dy / d) * f
                vel[i][0] -= fx; vel[i][1] -= fy
                vel[j][0] += fx; vel[j][1] += fy

        for a, b, rel in links:
            dx = pos[b][0] - pos[a][0]
            dy = pos[b][1] - pos[a][1]
            d = math.hypot(dx, dy) or 1.0
            rest = 620.0 if rel == RELATION_UNTYPED else 420.0
            f = (d - rest) * 0.012 * alpha
            fx, fy = (dx / d) * f, (dy / d) * f
            vel[a][0] += fx; vel[a][1] += fy
            vel[b][0] -= fx; vel[b][1] -= fy

        for i in range(len(ids)):
            vel[i][0] -= pos[i][0] * 0.0016 * alpha
            vel[i][1] -= pos[i][1] * 0.0016 * alpha
            vel[i][0] *= 0.84; vel[i][1] *= 0.84
            pos[i][0] += vel[i][0]; pos[i][1] += vel[i][1]

    return {nid: (round(pos[i][0]), round(pos[i][1])) for nid, i in index.items()}


def find_vault_root(config: Config) -> Optional[Any]:
    """Walk up from the KB looking for `.obsidian`.

    Canvas stores *vault-relative* file paths, so a canvas written without knowing the
    vault root points at files that do not exist. Detecting it is better than asking,
    and failing loudly is better than emitting a canvas full of dead nodes.
    """
    from pathlib import Path

    current = Path(config.kb).resolve()
    for directory in (current, *current.parents):
        if (directory / ".obsidian").is_dir():
            return directory
    return None


# ---------------------------------------------------------------------------
# Obsidian
# ---------------------------------------------------------------------------


def to_canvas(graph: dict[str, Any], config: Config,
              vault_root: Optional[Any] = None) -> str:
    """Obsidian Canvas (.canvas).

    Nodes are `file` nodes pointing at the real pages, so clicking one opens the note
    rather than a copy of it — the canvas is a view onto the KB, not a snapshot of it.
    Edges carry the relationship name as a label, which is the thing Obsidian's own
    graph view cannot show.
    """
    from pathlib import Path

    root = vault_root or find_vault_root(config)
    kb = Path(config.kb).resolve()

    def vault_path(node_id: str) -> str:
        target = kb / f"{node_id}.md"
        if root is not None:
            try:
                return str(target.relative_to(Path(root).resolve()).as_posix())
            except ValueError:
                pass
        return str(target.as_posix())

    pos = layout(graph)
    positioned = {n["id"]: n for n in graph["nodes"]}

    nodes = []
    for nid, node in positioned.items():
        x, y = pos.get(nid, (0, 0))
        colour = DOMAIN_COLOURS.get(node.get("domain", ""), DEFAULT_COLOUR)
        nodes.append({
            "id": nid.replace("/", "_"),
            "type": "file",
            "file": vault_path(nid),
            "x": int(x), "y": int(y),
            "width": 300, "height": 120,
            "color": colour,
        })

    edges = []
    for i, edge in enumerate(graph["edges"]):
        if edge["relation"] == RELATION_UNTYPED:
            continue  # untyped references bury the labelled edges in noise
        edges.append({
            "id": f"e{i}",
            "fromNode": edge["source"].replace("/", "_"),
            "fromSide": "right",
            "toNode": edge["target"].replace("/", "_"),
            "toSide": "left",
            "label": edge["relation"],
            # Disagreement is the rarest and most useful edge; make it red.
            "color": "1" if edge["relation"] == "contrasts with" else "6",
        })

    return json.dumps({"nodes": nodes, "edges": edges}, indent=2)


def to_obsidian_groups(graph: dict[str, Any]) -> str:
    """Colour groups for Obsidian's built-in graph view.

    Obsidian stores these in `.obsidian/graph.json` as search queries plus colours.
    It cannot label edges, so this only colours nodes by domain — worth having because
    it needs no plugin, but the canvas export shows strictly more.
    """
    def rgb_int(hex_colour: str) -> int:
        h = hex_colour.lstrip("#")
        return int(h, 16)

    present = {n.get("domain") for n in graph["nodes"] if n.get("domain")}
    groups = [
        {"query": f'["domain":"{domain}"]',
         "color": {"a": 1, "rgb": rgb_int(DOMAIN_COLOURS.get(domain, DEFAULT_COLOUR))}}
        for domain in sorted(present)
    ]
    groups.append({"query": "path:raw/",
                   "color": {"a": 1, "rgb": rgb_int("#4a5568")}})

    return json.dumps({
        "colorGroups": groups,
        "showTags": False,
        "showAttachments": False,
        "showOrphans": True,
        "_comment": ("Generated by `ugraph graph --format obsidian-groups`. "
                     "Merge into .obsidian/graph.json, or paste the colorGroups "
                     "array into your existing config."),
    }, indent=2)


# ---------------------------------------------------------------------------
# d3
# ---------------------------------------------------------------------------

_D3_HTML = """<!doctype html>
<meta charset="utf-8">
<title>%(title)s</title>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<style>
  :root {
    --ground:#eef0f4; --ink:#14161d; --soft:#545a68; --faint:#878e9d;
    --panel:#fff; --edge-c:#c3c9d4; --typed:#7d8698; --dissent:#d1495b;
  }
  @media (prefers-color-scheme: dark) {
    :root { --ground:#101319; --ink:#e8eaef; --soft:#9aa3b4; --faint:#6b7385;
            --panel:#171b23; --edge-c:#333a48; --typed:#5a6478; --dissent:#ff6b7f; }
  }
  * { box-sizing:border-box }
  body { margin:0; background:var(--ground); color:var(--ink); overflow:hidden;
         font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif }
  svg { display:block; width:100vw; height:100vh; cursor:grab }
  svg.grabbing { cursor:grabbing }
  .panel { position:fixed; top:18px; left:18px; background:var(--panel);
           border:1px solid var(--edge-c); border-radius:9px; padding:15px 16px;
           box-shadow:0 8px 26px rgba(0,0,0,.10); max-width:250px }
  h1 { font-size:14px; margin:0 0 3px; letter-spacing:-.01em }
  .m { font:10.5px ui-monospace,"SF Mono",Menlo,monospace; color:var(--faint);
       font-variant-numeric:tabular-nums; margin:0 0 12px }
  .k { display:flex; align-items:center; gap:7px; font-size:12px;
       color:var(--soft); margin:3px 0 }
  .sw { width:9px; height:9px; border-radius:50%%; flex:none }
  .hint { position:fixed; right:18px; bottom:16px;
          font:10px ui-monospace,Menlo,monospace; color:var(--faint) }
  .lbl { font-size:10px; fill:var(--ink); pointer-events:none;
         paint-order:stroke; stroke:var(--ground); stroke-width:3px }
  .tip { position:fixed; pointer-events:none; background:var(--panel);
         border:1px solid var(--edge-c); border-radius:6px; padding:7px 10px;
         font-size:12px; box-shadow:0 6px 20px rgba(0,0,0,.14); opacity:0;
         transition:opacity .12s; max-width:270px }
  .tip b { display:block; margin-bottom:2px }
  .tip span { color:var(--faint);
              font:10px ui-monospace,Menlo,monospace }
</style>

<svg id="v"></svg>
<div class="panel">
  <h1>%(title)s</h1>
  <p class="m">%(n)d nodes · %(e)d edges</p>
  <div id="key"></div>
</div>
<div class="tip" id="tip"></div>
<div class="hint">drag nodes · scroll to zoom · %(dissent)d disagreement edges in red</div>

<script>
const DATA = %(data)s;
const COLOURS = %(colours)s;
const DEFAULT_COLOUR = "%(default_colour)s";

const nodes = DATA.nodes.map(d => Object.assign({}, d));
const byId = new Map(nodes.map(n => [n.id, n]));
const links = DATA.edges
  .filter(e => byId.has(e.source) && byId.has(e.target))
  .map(e => Object.assign({}, e));

const deg = {};
links.forEach(l => { deg[l.source] = (deg[l.source]||0)+1;
                     deg[l.target] = (deg[l.target]||0)+1; });
nodes.forEach(n => n.deg = deg[n.id] || 0);

const colour = n => COLOURS[n.domain] || DEFAULT_COLOUR;
const radius = n => 4 + Math.sqrt(n.deg) * 1.9;

const svg = d3.select("#v");
const g = svg.append("g");
const tip = d3.select("#tip");

svg.call(d3.zoom().scaleExtent([0.2, 5]).on("zoom", ev => {
  g.attr("transform", ev.transform);
  g.selectAll(".lbl").attr("opacity", ev.transform.k > 0.75 ? 1 : 0);
}));

const link = g.append("g").selectAll("line").data(links).join("line")
  .attr("stroke", d => d.relation === "contrasts with"
        ? "var(--dissent)"
        : (d.relation === "references" ? "var(--edge-c)" : "var(--typed)"))
  .attr("stroke-width", d => d.relation === "contrasts with" ? 2.1
        : (d.relation === "references" ? 0.6 : 1.2))
  .attr("stroke-opacity", d => d.relation === "references" ? 0.28 : 0.75);

const node = g.append("g").selectAll("circle").data(nodes).join("circle")
  .attr("r", radius).attr("fill", colour)
  .attr("stroke", "var(--ground)").attr("stroke-width", 1.2)
  .style("cursor", "pointer")
  .call(d3.drag()
    .on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(.3).restart();
                              d.fx = d.x; d.fy = d.y; })
    .on("drag",  (ev, d) => { d.fx = ev.x; d.fy = ev.y; })
    .on("end",   (ev, d) => { if (!ev.active) sim.alphaTarget(0);
                              d.fx = null; d.fy = null; }));

node.on("pointerenter", (ev, d) => {
    const bits = [d.domain, d.status, d.source_count
                  ? d.source_count + " sources" : null,
                  d.confidence ? "confidence " + d.confidence : null]
                 .filter(Boolean).join(" · ");
    tip.html("<b>" + d.title + "</b><span>" + bits + "</span>")
       .style("opacity", 1);
  })
  .on("pointermove", ev => tip.style("left", (ev.clientX + 14) + "px")
                              .style("top", (ev.clientY + 14) + "px"))
  .on("pointerleave", () => tip.style("opacity", 0));

const label = g.append("g").selectAll("text").data(nodes.filter(n => n.deg >= 6))
  .join("text").attr("class", "lbl").attr("text-anchor", "middle")
  .attr("dy", d => radius(d) + 11)
  .text(d => d.title.length > 28 ? d.title.slice(0, 27) + "\\u2026" : d.title);

const sim = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(links).id(d => d.id)
    .distance(d => d.relation === "references" ? 130 : 78)
    .strength(d => d.relation === "contrasts with" ? 0.9 : 0.35))
  .force("charge", d3.forceManyBody().strength(-340))
  .force("center", d3.forceCenter(innerWidth/2, innerHeight/2))
  .force("collide", d3.forceCollide().radius(d => radius(d) + 6))
  .on("tick", () => {
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("cx", d => d.x).attr("cy", d => d.y);
    label.attr("x", d => d.x).attr("y", d => d.y);
  });

d3.select("#key").html(
  Object.entries(COLOURS).filter(([k]) => nodes.some(n => n.domain === k))
    .map(([k, c]) => '<div class="k"><span class="sw" style="background:' + c +
         '"></span>' + k.replace(/_/g, " ") + "</div>").join(""));

addEventListener("resize", () => sim.force("center",
  d3.forceCenter(innerWidth/2, innerHeight/2)).alpha(0.3).restart());
</script>
"""


def to_d3(graph: dict[str, Any], title: str = "Concept graph") -> str:
    """Standalone interactive HTML using d3-force.

    Loads d3 from a CDN, which is fine here and not elsewhere: this file is opened
    directly in a browser, where no Content-Security-Policy blocks it. The trade is
    that it needs a network connection the first time. Use `--format json` with your
    own viewer if that matters.
    """
    dissent = sum(1 for e in graph["edges"] if e["relation"] == "contrasts with")
    return _D3_HTML % {
        "title": title,
        "n": len(graph["nodes"]),
        "e": len(graph["edges"]),
        "dissent": dissent,
        "data": json.dumps(graph, separators=(",", ":")),
        "colours": json.dumps(DOMAIN_COLOURS),
        "default_colour": DEFAULT_COLOUR,
    }


FORMATS = {"json": to_json, "graphml": to_graphml, "dot": to_dot}

# Formats needing more than the graph itself are dispatched separately by render().
CONTEXT_FORMATS = {"canvas", "obsidian-groups"}


def render(graph: dict[str, Any], fmt: str = "json",
           config: Optional[Config] = None) -> str:
    if fmt == "canvas":
        if config is None:
            raise ValueError("the canvas format needs a Config to resolve vault paths")
        return to_canvas(graph, config)
    if fmt == "obsidian-groups":
        return to_obsidian_groups(graph)
    try:
        return FORMATS[fmt](graph)
    except KeyError:
        known = sorted(set(FORMATS) | CONTEXT_FORMATS)
        raise ValueError(
            f"unknown format {fmt!r}; expected one of {', '.join(known)}"
        ) from None
