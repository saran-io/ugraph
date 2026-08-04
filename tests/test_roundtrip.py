"""
End-to-end test: scaffold a knowledge base, populate it, and prove the gates work.

These tests deliberately avoid the network and avoid mocks. They build a small KB on
disk with the same shapes a real one has — a concept citing a source citing a
transcript — and then assert that the linter catches the things it exists to catch.

A mocked linter test proves the mock works. This proves the tool does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ugraph import config as config_mod
from ugraph import indexes, lint, status, store

TRANSCRIPT = """\
# Example Talk

> Machine-generated captions, normalized. Immutable — never edit by hand.

[00:00:00] Welcome everybody, thanks for having me here today.
[00:00:31] The thing nobody tells you about context windows is that they degrade
long before they fill up.
[00:01:04] So we treat the window as a budget rather than as headroom.
"""


def scaffold(tmp_path: Path) -> config_mod.Config:
    """A minimal but structurally complete KB."""
    kb = tmp_path / "kb"
    for rel in config_mod.CONTENT_DIRS:
        (kb / rel).mkdir(parents=True, exist_ok=True)

    from ugraph import templates
    (kb / "taxonomy.json").write_text(templates.read("taxonomy.json"), encoding="utf-8")
    (kb / "SCHEMA.md").write_text("---\ntype: overview\ntitle: Schema\n---\n\n# Schema\n",
                                  encoding="utf-8")

    store.write_md(kb / "raw" / "demo" / "example-talk.md", TRANSCRIPT, {
        "type": "raw-transcript", "immutable": True, "slug": "demo/example-talk",
    })
    store.write_md(kb / "sources" / "demo" / "example-talk.md",
                   "# Example Talk\n\nA talk about context budgets.\n", {
                       "type": "source", "source_type": "talk", "title": "Example Talk",
                       "description": "Context windows degrade before they fill.",
                       "channel": "demo", "slug": "demo/example-talk",
                       "raw": "../../raw/demo/example-talk.md",
                       "summary_status": "done",
                       "created": "2026-08-04", "updated": "2026-08-04",
                   })
    store.write_md(kb / "concepts" / "context-budget.md", (
        "# Context budget\n\n"
        "> The window is a budget, not headroom.\n\n"
        "Quality falls away well before the advertised limit "
        "([Example Talk](../sources/demo/example-talk.md) @ 00:00:31).\n\n"
        "## Sources\n\n"
        "- [Example Talk](../sources/demo/example-talk.md)\n"
    ), {
        "type": "concept", "title": "Context budget",
        "description": "The window is a budget, not headroom.",
        "domain": "ai_engineering", "status": "growing",
        "sources": ["demo/example-talk"],
        "created": "2026-08-04", "updated": "2026-08-04",
    })
    return config_mod.load(kb=kb)


def test_scaffolded_kb_lints_clean(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    findings, pages = lint.lint(cfg)
    assert findings.errors == [], findings.errors
    assert pages


def test_indexes_are_idempotent(tmp_path):
    """Same input must produce byte-identical output, or `--check` is worthless."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    assert indexes.check(cfg) == []
    assert indexes.write_all(cfg) == []


def test_broken_link_is_an_error(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    page = cfg.concepts / "context-budget.md"
    page.write_text(page.read_text() + "\n[gone](./nowhere.md)\n", encoding="utf-8")
    findings, _ = lint.lint(cfg)
    assert any(e["check"] == "links" for e in findings.errors)


def test_wikilink_banned_in_okf_tree(tmp_path):
    """The rule that keeps the bundle portable — wikilinks only resolve in Obsidian."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    page = cfg.concepts / "context-budget.md"
    page.write_text(page.read_text() + "\nSee [[some-other-note]].\n", encoding="utf-8")
    findings, _ = lint.lint(cfg)
    assert any(e["check"] == "links" and "wikilink" in e["message"]
               for e in findings.errors)


def test_missing_required_field_is_an_error(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    meta, body = store.read_md(cfg.concepts / "context-budget.md")
    del meta["description"]
    store.write_md(cfg.concepts / "context-budget.md", body, meta)
    findings, _ = lint.lint(cfg)
    assert any("description" in e["message"] for e in findings.errors)


def test_unknown_page_type_can_be_declared_in_taxonomy(tmp_path):
    """A KB may grow types the format never defined; it should not have to fork."""
    cfg = scaffold(tmp_path)
    store.write_md(cfg.kb / "digest.md", "# Digest\n",
                   {"type": "weekly_brief", "title": "Digest"})
    indexes.write_all(cfg)

    findings, _ = lint.lint(cfg)
    assert any("unknown page type" in e["message"] for e in findings.errors)

    tax = json.loads((cfg.kb / "taxonomy.json").read_text())
    tax["page_types"] = {"weekly_brief": []}
    (cfg.kb / "taxonomy.json").write_text(json.dumps(tax, indent=2), encoding="utf-8")

    findings, _ = lint.lint(cfg)
    assert not any("unknown page type" in e["message"] for e in findings.errors)


def test_status_reports_canonicalization_health(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    stats = status.collect(cfg)
    assert stats["concepts"] == 1
    assert stats["sources_total"] == 1
    assert stats["extracted"] == 1
    # One concept citing one source — the histogram is what flags it as a merge
    # candidate, and that signal is the reason the view exists.
    assert stats["source_counts"].get(1) == 1


def test_config_resolution_errors_are_actionable(tmp_path):
    with pytest.raises(config_mod.ConfigError) as exc:
        config_mod.load(kb=None, start=tmp_path)
    assert "ugraph init" in str(exc.value)


def test_init_suggests_commands_that_actually_run(tmp_path, capsys, monkeypatch):
    """`ugraph init vault/kb` writes ugraph.toml into `vault/`, but config resolution walks
    UP from the working directory — so a bare `ugraph ingest` from the parent cannot find
    it. Printing the bare command sent users straight into "cannot find a knowledge
    base" as the very next thing they ran after a successful init.
    """
    from ugraph import cli

    workdir = tmp_path / "work"
    (workdir / "MyVault").mkdir(parents=True)
    monkeypatch.chdir(workdir)

    args = cli.build_parser().parse_args(["init", "MyVault/knowledge"])
    assert args.func(args) == 0
    out = capsys.readouterr().out

    # ugraph.toml landed in MyVault/, which is below cwd and therefore unreachable.
    assert (workdir / "MyVault" / "ugraph.toml").exists()
    assert "--kb MyVault/knowledge ingest youtube" in out
    assert "cd MyVault" in out


def test_init_omits_the_flag_when_config_is_reachable(tmp_path, capsys, monkeypatch):
    """Inside a directory the config search can reach, the flag is noise."""
    from ugraph import cli

    monkeypatch.chdir(tmp_path)
    args = cli.build_parser().parse_args(["init", "kb"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "ugraph ingest youtube" in out
    assert "--kb" not in out


def test_configured_candidates_path_resolves_against_the_kb(tmp_path, monkeypatch):
    """A relative `candidates` path in ugraph.toml must resolve against the KB, not the
    working directory — otherwise the setting appears to do nothing, or something
    different, depending on where the command was run from."""
    kb = tmp_path / "vault" / "kb"
    kb.mkdir(parents=True)
    (tmp_path / "vault" / "ugraph.toml").write_text(
        'kb = "kb"\ncandidates = "../tooling/candidates"\n', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    cfg = config_mod.load(start=tmp_path / "vault")
    assert cfg.candidates == (tmp_path / "vault" / "tooling" / "candidates").resolve()

    monkeypatch.chdir(tmp_path / "vault")
    assert config_mod.load(start=tmp_path / "vault").candidates == cfg.candidates


def test_default_candidates_sit_outside_the_kb(tmp_path):
    """Phase A output is working state, not knowledge — it must not be linted."""
    cfg = scaffold(tmp_path)
    assert cfg.kb not in cfg.candidates.parents


def test_one_bad_file_does_not_hide_the_rest_of_the_kb(tmp_path):
    """A malformed page must cost one finding, not the remainder of the corpus.

    `iter_pages` is a generator that raises on unparseable frontmatter, and a raised
    generator cannot be resumed. An earlier `load_pages` caught that exception and
    broke, so every page sorted after the bad one silently vanished — and the linter
    then reported PASS on a knowledge base it had stopped reading. A gate that fails
    open is worse than no gate.
    """
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)

    # Sorts before 'context-budget.md', so a break here would swallow the real page.
    (cfg.concepts / "aaa-broken.md").write_text(
        "---\ntype: concept\ntitle: [unclosed\n  bad: : yaml\n---\n\n# Broken\n",
        encoding="utf-8")
    # And one after it, to catch the reverse ordering too.
    (cfg.concepts / "zzz-broken.md").write_text(
        "---\n\tthis is not: valid: yaml\n---\n", encoding="utf-8")

    findings, pages = lint.lint(cfg)

    seen = {p.path.name for p in pages}
    assert "context-budget.md" in seen, "a good page was dropped by a bad neighbour"
    assert any(e["check"] == "parse" for e in findings.errors)
    # Both bad files reported, not just the first one encountered.
    assert sum(1 for e in findings.errors if e["check"] == "parse") == 2


def _vault_with_notes(tmp_path):
    """A realistic Obsidian vault: real notes, wikilinks, no frontmatter."""
    vault = tmp_path / "MyVault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "Daily Notes").mkdir()
    (vault / "Daily Notes" / "2026-08-01.md").write_text(
        "# Monday\n\nSpoke to [[Sarah]] about [[Project Falcon]].\n", encoding="utf-8")
    (vault / "Sarah.md").write_text("# Sarah\nWorks on [[Project Falcon]]\n",
                                    encoding="utf-8")
    return vault


def test_init_refuses_an_obsidian_vault_root(tmp_path, capsys, monkeypatch):
    """The obvious thing a new user tries. Pointing init at the vault root used to
    scatter concepts/, entities/, raw/ and sources/ among their real folders, write an
    index.md that could clobber a note, put the config OUTSIDE the vault, and then
    report every personal note as a malformed page."""
    from ugraph import cli

    vault = _vault_with_notes(tmp_path)
    monkeypatch.chdir(vault)

    args = cli.build_parser().parse_args(["init", "."])
    assert args.func(args) == 1

    out = capsys.readouterr().out
    assert "Obsidian vault root" in out
    assert "ugraph init knowledge" in out

    # Nothing was written before the refusal.
    for created in ("concepts", "entities", "raw", "sources", "SCHEMA.md", "index.md"):
        assert not (vault / created).exists(), f"init touched the vault: {created}"
    assert not (vault.parent / "ugraph.toml").exists()


def test_init_refuses_a_directory_that_already_has_notes(tmp_path, capsys):
    """Same protection outside Obsidian — any folder holding someone's markdown."""
    from ugraph import cli

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "thing.md").write_text("# hi\n", encoding="utf-8")

    args = cli.build_parser().parse_args(["init", str(notes)])
    assert args.func(args) == 1
    out = capsys.readouterr().out
    assert "already contains markdown files" in out
    assert not (notes / "concepts").exists()


def test_init_into_a_subfolder_of_a_real_vault_is_scoped(tmp_path, monkeypatch):
    """The documented path. The KB must not see the surrounding vault's notes."""
    from ugraph import cli
    from ugraph import config as config_mod
    from ugraph import lint as lint_mod

    vault = _vault_with_notes(tmp_path)
    monkeypatch.chdir(vault)

    args = cli.build_parser().parse_args(["init", "knowledge"])
    assert args.func(args) == 0

    # Config lands inside the vault, not above it.
    assert (vault / "ugraph.toml").is_file()
    assert not (vault.parent / "ugraph.toml").exists()

    cfg = config_mod.load(kb=vault / "knowledge")
    findings, pages = lint_mod.lint(cfg)
    assert findings.errors == [], findings.errors
    assert pages == [], "lint reached outside the knowledge base into the vault"
