"""
The Obsidian and d3 exports carry more failure modes than the plain formats, because
each targets a consumer with its own rules: Canvas file paths are vault-relative and
silently produce dead nodes if resolved wrongly, and the d3 page is a single file that
either runs in a browser or does not.
"""

from __future__ import annotations

import json

from okf import graph, indexes
from tests.test_roundtrip import scaffold


def test_layout_is_deterministic(tmp_path):
    """Re-exporting after a small change should nudge the picture, not reshuffle it."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    g = graph.build(cfg)
    assert graph.layout(g, iterations=40) == graph.layout(g, iterations=40)


def test_layout_separates_nodes(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    g = graph.build(cfg)
    pos = graph.layout(g, iterations=120)
    coords = list(pos.values())
    assert len(set(coords)) == len(coords), "nodes must not be stacked at one point"


def test_canvas_is_valid_and_self_consistent(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    g = graph.build(cfg)
    canvas = json.loads(graph.to_canvas(g, cfg))

    assert canvas["nodes"], "a canvas with no nodes is not worth writing"
    ids = {n["id"] for n in canvas["nodes"]}
    for node in canvas["nodes"]:
        assert node["type"] == "file"
        assert node["file"].endswith(".md")
        for key in ("x", "y", "width", "height"):
            assert isinstance(node[key], int)
    for edge in canvas["edges"]:
        # A dangling edge renders as a line to nowhere and cannot be selected.
        assert edge["fromNode"] in ids
        assert edge["toNode"] in ids
        assert edge["label"]


def test_canvas_paths_resolve_against_the_vault(tmp_path):
    """Canvas stores vault-relative paths. Resolving them wrongly yields a canvas of
    dead nodes that looks fine until every one is clicked."""
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    cfg = scaffold(vault)  # scaffold() puts the KB at <parent>/kb
    indexes.write_all(cfg)

    assert graph.find_vault_root(cfg) == vault

    g = graph.build(cfg)
    canvas = json.loads(graph.to_canvas(g, cfg))
    for node in canvas["nodes"]:
        assert (vault / node["file"]).exists(), node["file"]


def test_canvas_drops_untyped_references(tmp_path):
    """Labelled edges are the reason to use a canvas; unlabelled ones bury them."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    g = graph.build(cfg)
    canvas = json.loads(graph.to_canvas(g, cfg))
    assert graph.RELATION_UNTYPED not in {e["label"] for e in canvas["edges"]}


def test_obsidian_groups_are_loadable_config(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    g = graph.build(cfg)
    conf = json.loads(graph.to_obsidian_groups(g))
    assert conf["colorGroups"]
    for group in conf["colorGroups"]:
        assert isinstance(group["color"]["rgb"], int)
        assert group["query"]


def test_d3_page_is_self_contained_html(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    html = graph.to_d3(graph.build(cfg))
    assert html.startswith("<!doctype html>")
    assert "d3.min.js" in html
    assert "const DATA = {" in html
    # A stray unescaped %% in the template would have already raised, but an
    # unsubstituted placeholder would silently ship a broken page.
    assert "%(" not in html


def test_types_filter_shrinks_the_graph(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    everything = graph.build(cfg)
    concepts = graph.build(cfg, types={"concept", "entity", "moc"})
    assert len(concepts["nodes"]) < len(everything["nodes"])
    assert all(n.get("type") != "source" for n in concepts["nodes"])


def test_canvas_without_config_is_a_clear_error(tmp_path):
    cfg = scaffold(tmp_path)
    g = graph.build(cfg)
    try:
        graph.render(g, "canvas")
    except ValueError as exc:
        assert "Config" in str(exc)
    else:
        raise AssertionError("canvas without a Config should raise")
