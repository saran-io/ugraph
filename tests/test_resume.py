"""
Resume has to survive a lost state file and a video that can never be fetched.

Both of these were real. The state file was orphaned by a rename and the tool offered
to re-download 151 videos it already had, because it never looked at disk. And a video
with no captions was never recorded as tried, so it stayed at the head of the queue
forever.

No network: these test the bookkeeping, which is the part that has to be right.
"""

from __future__ import annotations

import json

from tests.test_roundtrip import scaffold
from ugraph import store
from ugraph.sources import youtube


def _raw(cfg, name: str, video_id: str | None) -> None:
    meta = {"type": "raw-transcript", "immutable": True, "slug": f"demo/{name}"}
    if video_id:
        meta["youtube_id"] = video_id
    store.write_md(cfg.raw_dir / "demo" / f"{name}.md", "[00:00:00] words\n", meta)


# ---------------------------------------------------------------------------
# Reconciling state from disk
# ---------------------------------------------------------------------------

def test_ids_are_recoverable_from_transcripts(tmp_path):
    """The evidence is on disk. A lost state file must not mean a lost corpus."""
    cfg = scaffold(tmp_path)
    _raw(cfg, "one", "aaa111")
    _raw(cfg, "two", "bbb222")
    assert youtube.ids_on_disk(cfg) == {"aaa111", "bbb222"}


def test_reconcile_recovers_an_orphaned_state_file(tmp_path):
    """The exact failure: state says nothing, disk holds everything.

    Before this, `ingest` treated all of them as new."""
    cfg = scaffold(tmp_path)
    _raw(cfg, "one", "aaa111")
    _raw(cfg, "two", "bbb222")
    assert youtube.reconcile(cfg, []) == {"aaa111", "bbb222"}


def test_reconcile_keeps_ids_whose_transcript_was_deleted(tmp_path):
    """Union, not replace. A talk ingested twice under two titles gets one copy
    deleted by hand — and deleting it must not invite it back on the next run."""
    cfg = scaffold(tmp_path)
    _raw(cfg, "one", "aaa111")
    assert youtube.reconcile(cfg, ["aaa111", "deleted99"]) == {"aaa111", "deleted99"}


def test_a_transcript_with_no_video_id_is_ignored_not_crashed_on(tmp_path):
    """Hand-written and non-YouTube transcripts legitimately have no id."""
    cfg = scaffold(tmp_path)
    _raw(cfg, "handwritten", None)
    _raw(cfg, "real", "aaa111")
    assert youtube.ids_on_disk(cfg) == {"aaa111"}


def test_an_unreadable_transcript_does_not_abort_reconciliation(tmp_path):
    """One bad file must not silently shrink the recovered set to nothing — that is
    the failing-open shape that made the linter dangerous."""
    cfg = scaffold(tmp_path)
    _raw(cfg, "good", "aaa111")
    (cfg.raw_dir / "demo" / "broken.md").write_text(
        "---\n:::not yaml:::\n---\nbody\n", encoding="utf-8")
    assert "aaa111" in youtube.ids_on_disk(cfg)


# ---------------------------------------------------------------------------
# Terminal failures
# ---------------------------------------------------------------------------

def test_a_video_with_no_captions_is_not_retried_forever(tmp_path, monkeypatch):
    """The livelock. `batch = pending[:limit]` follows listing order, so a channel
    whose newest videos lack captions makes every run retry the same ones and never
    advance. Recording the failure is what lets the queue move."""
    cfg = scaffold(tmp_path)
    monkeypatch.setattr(youtube, "_require_yt_dlp", lambda: None)
    monkeypatch.setattr(youtube, "list_channel_videos", lambda url, limit=None: [
        {"id": "dead01", "title": "No captions", "duration": 60},
        {"id": "dead02", "title": "Also none", "duration": 60},
    ])
    monkeypatch.setattr(youtube, "fetch_video", lambda *a, **k: None)

    first = youtube.ingest(cfg, "https://youtube.com/@x", limit=2)
    assert first["written"] == 0 and first["skipped"] == 2
    assert first["failed"] == 2

    # Second run: both are known-bad, so there is nothing left pending.
    second = youtube.ingest(cfg, "https://youtube.com/@x", limit=2)
    assert second["pending"] == 0, "a permanent failure was queued again"
    assert second["known_failed"] == 2


def test_retry_failed_reconsiders_them(tmp_path, monkeypatch):
    """Captions do get added later, so the exclusion has to be escapable."""
    cfg = scaffold(tmp_path)
    monkeypatch.setattr(youtube, "_require_yt_dlp", lambda: None)
    monkeypatch.setattr(youtube, "list_channel_videos", lambda url, limit=None: [
        {"id": "dead01", "title": "No captions", "duration": 60},
    ])
    monkeypatch.setattr(youtube, "fetch_video", lambda *a, **k: None)
    youtube.ingest(cfg, "https://youtube.com/@x", limit=1)

    again = youtube.ingest(cfg, "https://youtube.com/@x", limit=1, retry_failed=True,
                           dry_run=True)
    assert again["pending"] == 1


def test_failures_record_a_reason_and_a_count(tmp_path, monkeypatch):
    """"Why" matters: 'no captions' on attempt 1 and on attempt 4 mean different
    things about whether to keep waiting."""
    cfg = scaffold(tmp_path)
    monkeypatch.setattr(youtube, "_require_yt_dlp", lambda: None)
    monkeypatch.setattr(youtube, "list_channel_videos", lambda url, limit=None: [
        {"id": "dead01", "title": "No captions", "duration": 60},
    ])
    monkeypatch.setattr(youtube, "fetch_video", lambda *a, **k: None)
    youtube.ingest(cfg, "https://youtube.com/@x", limit=1)
    youtube.ingest(cfg, "https://youtube.com/@x", limit=1, retry_failed=True)

    saved = json.loads((cfg.state / "youtube.json").read_text(encoding="utf-8"))
    entry = saved["channels"]["https://youtube.com/@x"]["failed"]["dead01"]
    assert entry["reason"] == "no captions available"
    assert entry["attempts"] == 2
    assert entry["at"]


# ---------------------------------------------------------------------------
# --newest
# ---------------------------------------------------------------------------

def test_newest_bounds_the_window_and_limit_bounds_the_work(tmp_path, monkeypatch):
    """`--newest 5 --limit 2` is "of the 5 most recent, do 2" — the documented order."""
    cfg = scaffold(tmp_path)
    listed = []

    def fake_list(url, limit=None):
        listed.append(limit)
        return [{"id": f"v{i}", "title": f"Talk {i}", "duration": 60}
                for i in range(limit or 20)]

    monkeypatch.setattr(youtube, "_require_yt_dlp", lambda: None)
    monkeypatch.setattr(youtube, "list_channel_videos", fake_list)

    result = youtube.ingest(cfg, "https://youtube.com/@x", newest=5, limit=2,
                            dry_run=True)
    assert listed[-1] == 5, "--newest must bound the listing, not over-fetch"
    assert len(result["videos"]) == 2


def test_newest_is_idempotent_when_everything_is_already_held(tmp_path, monkeypatch):
    """"Make sure the newest 10 are in" must do nothing on the second run — this is
    the check that would have caught the orphaned-state re-download."""
    cfg = scaffold(tmp_path)
    for i in range(3):
        _raw(cfg, f"talk{i}", f"v{i}")

    monkeypatch.setattr(youtube, "_require_yt_dlp", lambda: None)
    monkeypatch.setattr(youtube, "list_channel_videos", lambda url, limit=None: [
        {"id": f"v{i}", "title": f"Talk {i}", "duration": 60} for i in range(3)
    ])

    result = youtube.ingest(cfg, "https://youtube.com/@x", newest=3, dry_run=True)
    assert result["videos"] == [], "already-held videos were queued again"
    assert result["recovered_from_disk"] == 3
