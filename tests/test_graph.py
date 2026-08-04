"""
The graph export is a derived view, so the only interesting property is that it agrees
with the source of truth. If the linter says an edge is one-way and the export disagrees,
one of them is lying and the export is the one nobody would notice.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from tests.test_roundtrip import scaffold
from ugraph import graph, indexes, lint, model


def test_every_node_is_a_real_page(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    g = graph.build(cfg)

    ids = {p.id for p in model.iter_pages(cfg)}
    assert {n["id"] for n in g["nodes"]} <= ids
    assert g["nodes"], "a scaffolded KB has pages, so it must have nodes"


def test_every_edge_endpoint_exists(tmp_path):
    """A dangling edge in an export is worse than a broken link in a file — the file
    at least gets flagged by the linter."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    g = graph.build(cfg)

    node_ids = {n["id"] for n in g["nodes"]}
    for edge in g["edges"]:
        assert edge["source"] in node_ids, edge
        assert edge["target"] in node_ids, edge


def test_graph_agrees_with_linter_on_reciprocity(tmp_path):
    """The concept page cites a source. That is provenance — one-way by definition —
    so the export must not claim a reciprocal edge the linter would reject."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    findings, _ = lint.lint(cfg)
    assert not findings.errors

    g = graph.build(cfg)
    provenance = [e for e in g["edges"] if e["relation"] == graph.RELATION_PROVENANCE]
    assert provenance, "the scaffold cites a source"
    for edge in provenance:
        reverse = [e for e in g["edges"]
                   if e["source"] == edge["target"] and e["target"] == edge["source"]]
        assert not reverse, f"source pages must not link back: {edge}"


def test_provenance_can_be_dropped(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    full = graph.build(cfg, include_provenance=True)
    lean = graph.build(cfg, include_provenance=False)
    assert len(lean["edges"]) < len(full["edges"])
    assert not [e for e in lean["edges"] if e["relation"] == graph.RELATION_PROVENANCE]


def test_export_is_deterministic(tmp_path):
    """Regenerating must produce identical bytes, or the export cannot live in git."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    assert graph.to_json(graph.build(cfg)) == graph.to_json(graph.build(cfg))


def test_all_formats_are_well_formed(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    g = graph.build(cfg)

    parsed = json.loads(graph.to_json(g))
    assert parsed["nodes"] and "edges" in parsed

    ET.fromstring(graph.to_graphml(g))  # raises if malformed

    dot = graph.to_dot(g)
    assert dot.startswith("digraph kb {") and dot.rstrip().endswith("}")


def test_unknown_format_is_a_clear_error(tmp_path):
    cfg = scaffold(tmp_path)
    g = graph.build(cfg)
    try:
        graph.render(g, "neo4j")
    except ValueError as exc:
        assert "neo4j" in str(exc) and "json" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown format")
