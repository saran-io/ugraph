"""
Selection decides which work a command does. Getting it wrong is quiet: the command
succeeds, reports a sensible-looking count, and processes the wrong things — which is
exactly what `extract --limit` did for months by sorting filenames.

These tests are pure. No KB on disk, no model, no network.
"""

from __future__ import annotations

from datetime import date

import pytest

from ugraph import select


class FakePage:
    """Just enough of a Page: selection only ever reads `meta` and `id`."""

    def __init__(self, slug: str, published: str | None = None):
        self.id = slug
        self.meta = {"slug": slug}
        if published is not None:
            self.meta["published"] = published

    def __repr__(self):  # so a failure names the page rather than an object address
        return f"<{self.id} {self.meta.get('published', 'undated')}>"


def kb() -> list[FakePage]:
    return [
        FakePage("ai-engineer/mcp-apps", "2026-08-02"),
        FakePage("ai-engineer/benchmaxxing", "2026-08-02"),
        FakePage("ai-engineer/rethinking-envs", "2026-08-01"),
        FakePage("ai-engineer/old-talk", "2026-07-10"),
        FakePage("karpathy/vibe-coding"),                    # no date at all
        FakePage("karpathy/software-2-0"),
    ]


# --------------------------------------------------------------------------
# The trap this module exists to avoid
# --------------------------------------------------------------------------

def test_undated_pages_never_count_as_the_newest():
    """`sorted(reverse=True)` on the raw values puts None/"?" FIRST, so `--newest 3`
    would return three pages whose date nobody knows and call them the most recent.

    In the reference KB that is three hand-written Karpathy pages, which would have
    displaced real recent talks on every single run."""
    top = select.by_recency(kb(), newest=3)
    assert [p.id for p in top] == [
        "ai-engineer/benchmaxxing",     # 08-02, earlier slug
        "ai-engineer/mcp-apps",         # 08-02
        "ai-engineer/rethinking-envs",  # 08-01
    ]
    assert not any("karpathy" in p.id for p in top)


def test_undated_pages_sort_last_but_are_not_discarded():
    """Without `--since` they are still part of the corpus — just never the newest."""
    ordered = select.by_recency(kb())
    assert len(ordered) == 6
    assert [p.id for p in ordered[-2:]] == [
        "karpathy/software-2-0", "karpathy/vibe-coding"]


def test_since_drops_undated_pages():
    """`--since` asks for proof of recency. A page with no date cannot give one, and
    guessing in its favour would silently widen every window."""
    got = select.by_recency(kb(), since=date(2026, 7, 1))
    assert all("karpathy" not in p.id for p in got)
    assert len(got) == 4


# --------------------------------------------------------------------------
# Ordering must be stable
# --------------------------------------------------------------------------

def test_same_day_items_break_ties_by_slug_not_by_reversed_slug():
    """A batch job that picks a different five sources each run is not resumable.

    `sorted(reverse=True)` would flip the tie-breaker too, so two same-day talks would
    come back in descending slug order — correct-looking, but the opposite of every
    other listing in the tool."""
    same_day = [FakePage("c/three", "2026-08-02"), FakePage("a/one", "2026-08-02"),
                FakePage("b/two", "2026-08-02")]
    assert [p.id for p in select.by_recency(same_day)] == ["a/one", "b/two", "c/three"]


def test_selection_is_repeatable():
    first = [p.id for p in select.by_recency(kb(), newest=4)]
    second = [p.id for p in select.by_recency(list(reversed(kb())), newest=4)]
    assert first == second


# --------------------------------------------------------------------------
# Composition — the documented order
# --------------------------------------------------------------------------

def test_channel_narrows_before_newest_counts():
    got = select.by_recency(kb(), newest=2, channel="ai-engineer")
    assert [p.id for p in got] == ["ai-engineer/benchmaxxing", "ai-engineer/mcp-apps"]


def test_newest_applies_after_since_not_before():
    """`--since 2026-08-01 --newest 10` is "everything since the 1st, at most 10" —
    not "the 10 newest, then filtered", which would return fewer than it should."""
    got = select.by_recency(kb(), newest=10, since=date(2026, 8, 1))
    assert len(got) == 3


def test_no_filters_returns_everything_just_ordered():
    assert len(select.by_recency(kb())) == len(kb())


# --------------------------------------------------------------------------
# parse_since
# --------------------------------------------------------------------------

def test_absolute_dates():
    assert select.parse_since("2026-07-25") == date(2026, 7, 25)


@pytest.mark.parametrize("text,days", [("7d", 7), ("2w", 14), ("3m", 90), ("1y", 365)])
def test_relative_windows(text, days):
    today = date(2026, 8, 5)
    assert (today - select.parse_since(text, today=today)).days == days


def test_a_bad_date_says_what_is_accepted():
    """This is flag input, so the error is read by a person mid-command."""
    with pytest.raises(ValueError) as exc:
        select.parse_since("last tuesday")
    assert "YYYY-MM-DD" in str(exc.value) and "7d" in str(exc.value)


def test_channel_of_handles_a_slug_with_no_channel():
    assert select.channel_of(FakePage("loose-page")) == ""


def test_channel_matches_the_slug_segment_not_the_display_name():
    """`ledger.Item` carries a `channel` field holding "AI Engineer", while the slug
    segment is `ai-engineer`. Preferring the field would make `--channel ai-engineer`
    silently match nothing on the ledger while working fine on extract."""
    class Item:
        slug = "ai-engineer/some-talk"
        channel = "AI Engineer"      # display name, deliberately different
        published = "2026-08-02"

    assert select.channel_of(Item()) == "ai-engineer"
    assert len(select.by_recency([Item()], channel="ai-engineer")) == 1


def test_ledger_items_and_pages_select_identically():
    """The flags have to behave the same in every command, and the two commands hand
    in different shapes: a Page keeps frontmatter in `.meta`, an Item is a dataclass."""
    class Item:
        slug = "ai-engineer/talk"
        published = "2026-08-02"

    page = FakePage("ai-engineer/talk", "2026-08-02")
    assert select.published(Item()) == select.published(page)
    assert select.channel_of(Item()) == select.channel_of(page)
