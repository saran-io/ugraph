"""
The ledger derives state from the filesystem and logs transitions separately. The tests
that matter are the ones proving those two halves cannot disagree with each other, or
with `ugraph status`, which reports the same facts in aggregate.
"""

from __future__ import annotations

import json

from tests.test_roundtrip import scaffold
from ugraph import indexes, ledger, status, store


def test_a_fully_processed_source_reaches_linked(tmp_path):
    """The scaffold has a concept citing a source citing a transcript, and that concept
    carries a typed edge — so the source has been all the way through."""
    cfg = scaffold(tmp_path)
    # Give the concept a typed relationship so `linked` is reachable.
    page = cfg.concepts / "context-budget.md"
    page.write_text(
        page.read_text().replace(
            "## Sources",
            "## Related\n\n- [Self](context-budget.md)\n\n## Sources"),
        encoding="utf-8")
    indexes.write_all(cfg)

    items = ledger.collect(cfg)
    assert len(items) == 1
    item = items[0]
    assert item.pulled and item.synthesized and item.linked
    assert item.stage == "linked"
    assert item.concepts == ["concepts/context-budget"]
    assert item.done


def test_source_with_no_transcript_is_flagged_orphaned(tmp_path):
    """A page cited by concepts with nothing behind it asserts claims that cannot be
    checked. That is worse than being unprocessed and must not read as progress."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)

    src = cfg.sources / "demo" / "example-talk.md"
    meta, body = store.read_md(src)
    del meta["raw"]
    meta["source_type"] = "talk"
    store.write_md(src, body, meta)
    (cfg.raw_dir / "demo" / "example-talk.md").unlink()

    item = ledger.collect(cfg)[0]
    assert item.stage == "orphaned"
    assert not item.pulled
    assert any("never pulled" in i for i in item.issues)


def test_video_without_transcript_raises_an_issue(tmp_path):
    """Only `video` promises a transcript, so only `video` is faulted for lacking one."""
    cfg = scaffold(tmp_path)
    src = cfg.sources / "demo" / "example-talk.md"
    meta, body = store.read_md(src)
    del meta["raw"]
    meta["source_type"] = "video"
    store.write_md(src, body, meta)
    indexes.write_all(cfg)

    item = ledger.collect(cfg)[0]
    assert any("no `raw:` transcript" in i for i in item.issues)


def test_pulled_but_unprocessed_is_stuck(tmp_path):
    cfg = scaffold(tmp_path)
    src = cfg.sources / "demo" / "example-talk.md"
    meta, body = store.read_md(src)
    meta["summary_status"] = "pending"
    store.write_md(src, body, meta)
    indexes.write_all(cfg)

    item = ledger.collect(cfg)[0]
    assert item.stage == "pulled"
    assert item.stuck and not item.done


def test_transitions_round_trip(tmp_path):
    cfg = scaffold(tmp_path)
    ledger.record(cfg, "demo/example-talk", "pulled", by="test")
    ledger.record(cfg, "demo/example-talk", "extracted", by="test", detail="3 candidates")
    ledger.record(cfg, "other/thing", "pulled", by="test")

    all_events = ledger.history(cfg)
    assert len(all_events) == 3
    mine = ledger.history(cfg, "demo/example-talk")
    assert [e["stage"] for e in mine] == ["pulled", "extracted"]
    assert mine[1]["detail"] == "3 candidates"


def test_unknown_stage_is_rejected(tmp_path):
    """A typo'd stage would sit in the log forever, invisible and uncounted."""
    cfg = scaffold(tmp_path)
    try:
        ledger.record(cfg, "demo/example-talk", "proccessed")
    except ValueError as exc:
        assert "proccessed" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unknown stage")


def test_a_corrupt_line_does_not_break_the_log(tmp_path):
    """Losing one entry is recoverable; refusing to open the ledger is not."""
    cfg = scaffold(tmp_path)
    ledger.record(cfg, "demo/example-talk", "pulled")
    with open(ledger.ledger_path(cfg), "a", encoding="utf-8") as fh:
        fh.write("{not json at all\n")
    ledger.record(cfg, "demo/example-talk", "extracted")

    events = ledger.history(cfg)
    assert [e["stage"] for e in events] == ["pulled", "extracted"]


def test_ledger_agrees_with_status(tmp_path):
    """Two views of the same filesystem disagreeing means one is wrong, and people
    trust the aggregate one by default."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)

    items = ledger.collect(cfg)
    stats = status.collect(cfg)

    assert len(items) == stats["sources_total"]
    assert sum(1 for i in items if i.synthesized) == stats["extracted"]


def test_state_is_derived_not_stored(tmp_path):
    """Deleting the transition log must not change the reported stage — otherwise the
    ledger is a second source of truth and will drift."""
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)

    before = ledger.collect(cfg)[0].stage
    ledger.record(cfg, "demo/example-talk", "pulled", by="test")
    ledger.ledger_path(cfg).unlink()
    assert ledger.collect(cfg)[0].stage == before


def test_markdown_report_is_written_and_readable(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    path = ledger.write_report(cfg)

    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")           # frontmatter, so Obsidian treats it as a page
    assert "# Pipeline ledger" in text
    assert "Where everything is" in text


def test_json_output_is_serializable(tmp_path):
    cfg = scaffold(tmp_path)
    indexes.write_all(cfg)
    parsed = json.loads(ledger.to_json(ledger.collect(cfg)))
    assert parsed and "stage" in parsed[0] and "slug" in parsed[0]
