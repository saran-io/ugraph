"""youtube.py — pull YouTube channel transcripts into a knowledge base.

Stage 1 of the pipeline. Deterministic, no LLM: fetch captions with yt-dlp,
normalize them into timestamped markdown, and emit a `raw/` transcript plus a stub
`sources/` page for each video. Stage 2 (extraction into concepts and entities) is a
separate, LLM-driven pass. This module never invents content; it only transports it.

Incremental and resumable by design. Video IDs already ingested are recorded in
state and skipped, so this is safe to re-run against a 1000-video channel in
whatever sized batches you like — and safe to interrupt, because state is
checkpointed after every written video rather than once at the end.

Everything here takes a `Config`; nothing resolves paths on its own and nothing
prints progress. The CLI owns argument parsing and stdout, and passes a `progress`
callback if it wants per-video output.

    from okf import config, sources
    from okf.sources import youtube

    cfg = config.load()
    result = youtube.ingest(cfg, "https://www.youtube.com/@aiDotEngineer", limit=20)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from okf.config import Config
from okf.store import State, hhmmss, iso, log, read_md, slugify, write_md

# Name used for the state file and the log file. Changing it orphans existing state.
JOB = "youtube"

# Seconds between video fetches. YouTube throttles aggressively on bulk access;
# this is the difference between a batch completing and getting a 429.
DEFAULT_SLEEP = 1.5

# Caption cues are merged into paragraphs of roughly this length so citations land
# on a readable block rather than a three-word fragment.
PARAGRAPH_SECONDS = 30

YT_DLP = "yt-dlp"

# progress(index, total, video_id, title) — optional, so the caller can print.
ProgressFn = Callable[[int, int, str, str], None]


class YtDlpNotFound(RuntimeError):
    """The yt-dlp binary is not on PATH."""


def _require_yt_dlp() -> None:
    """Fail early and legibly rather than with a bare FileNotFoundError deep in a loop."""
    if shutil.which(YT_DLP) is None:
        raise YtDlpNotFound(
            "yt-dlp is required for YouTube ingestion but was not found on PATH.\n"
            "  Install it with one of:\n"
            "    pipx install yt-dlp\n"
            "    pip install yt-dlp\n"
            "    brew install yt-dlp\n"
            "  See https://github.com/yt-dlp/yt-dlp#installation"
        )


def _log(config: Config, message: str, echo: bool = False) -> None:
    log(config.logs, JOB, message, echo=echo)


# ---------------------------------------------------------------------------
# yt-dlp wrappers
# ---------------------------------------------------------------------------


def list_channel_videos(channel_url: str, limit: int | None = None) -> list[dict]:
    """Return [{id, title, duration}] for a channel, newest first.

    Pure read: touches no config and writes nothing, so a CLI can call it to preview
    a channel before deciding to ingest.
    """
    _require_yt_dlp()

    url = channel_url.rstrip("/")
    if not url.endswith(("/videos", "/streams")):
        url += "/videos"

    cmd = [YT_DLP, "--flat-playlist", "--ignore-errors",
           "--print", "%(id)s\t%(title)s\t%(duration)s"]
    if limit:
        cmd += ["--playlist-end", str(limit)]
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(f"yt-dlp failed to list {url}:\n{result.stderr[-800:]}")

    videos: list[dict] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        vid, title, duration = parts[0], parts[1], parts[2]
        videos.append({
            "id": vid,
            "title": title,
            "duration": int(duration) if duration.isdigit() else 0,
        })
    return videos


def fetch_video(config: Config, video_id: str, workdir: Path) -> dict | None:
    """Download English auto-captions + metadata for one video.

    Returns {title, channel, upload_date, duration, captions_path} or None when the
    video has no English captions.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        YT_DLP, "--skip-download", "--no-warnings",
        "--write-auto-subs", "--sub-langs", "en", "--sub-format", "json3",
        "-o", str(workdir / "%(id)s.%(ext)s"),
        # --print implies --simulate, which silently suppresses writing the subtitle
        # file. --no-simulate restores it so we get metadata *and* captions in one
        # call. This cost real debugging time; do not remove it.
        "--print", "%(title)s\t%(channel)s\t%(upload_date)s\t%(duration)s",
        "--no-simulate",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        _log(config, f"  {video_id}: yt-dlp error — {result.stderr.strip()[:200]}")
        return None

    line = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else ""
    parts = line.split("\t")
    if len(parts) < 4:
        _log(config, f"  {video_id}: unexpected metadata line — {line[:120]!r}")
        return None

    captions = workdir / f"{video_id}.en.json3"
    if not captions.exists():
        _log(config, f"  {video_id}: no English captions available")
        return None

    return {
        "title": parts[0],
        "channel": parts[1],
        "upload_date": parts[2],
        "duration": int(parts[3]) if parts[3].isdigit() else 0,
        "captions_path": captions,
    }


# ---------------------------------------------------------------------------
# Caption parsing
# ---------------------------------------------------------------------------


def parse_json3(path: Path) -> list[tuple[int, str]]:
    """Parse a YouTube json3 caption file into [(start_seconds, text)] cues.

    Auto-captions interleave real cues with `aAppend` newline events used for the
    rolling on-screen effect. Those carry no content and are dropped.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cues: list[tuple[int, str]] = []
    for event in data.get("events", []):
        if event.get("aAppend"):
            continue
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(seg.get("utf8", "") for seg in segs)
        text = text.replace("\n", " ").strip()
        if not text or text == "[music]":
            continue
        cues.append((int(event.get("tStartMs", 0)) // 1000, text))
    return cues


def cues_to_paragraphs(cues: list[tuple[int, str]],
                       window: int = PARAGRAPH_SECONDS) -> list[tuple[int, str]]:
    """Merge cues into ~`window`-second paragraphs, each keyed by its start time.

    Cues arrive a few words at a time. Merging them is what makes a timestamp
    citation point at a readable block instead of a three-word fragment.
    """
    if not cues:
        return []

    paragraphs: list[tuple[int, str]] = []
    bucket_start = cues[0][0]
    buffer: list[str] = []

    for start, text in cues:
        if buffer and start - bucket_start >= window:
            paragraphs.append((bucket_start, " ".join(buffer)))
            bucket_start, buffer = start, []
        buffer.append(text)

    if buffer:
        paragraphs.append((bucket_start, " ".join(buffer)))

    # Collapse the double spaces auto-captions leave behind.
    return [(t, re.sub(r"\s{2,}", " ", p).strip()) for t, p in paragraphs]


# ---------------------------------------------------------------------------
# Page writing
# ---------------------------------------------------------------------------


def unique_slug(config: Config, title: str, video_id: str, channel_dir: Path,
                warnings: list[str] | None = None) -> str:
    """Stable kebab-case slug, disambiguated by video id only when it collides.

    A base-slug collision between two different video IDs usually means the channel
    published the same talk twice (a conference recording and a shorter re-record, for
    instance). Both get kept, but the collision is logged loudly: two files for one talk
    silently double-count toward the format's >=2-source rule and fabricate a merge that
    never happened. Review flagged pairs before extraction.
    """
    base = slugify(title)
    candidate = channel_dir / f"{base}.md"
    if not candidate.exists():
        return base
    existing = candidate.read_text(encoding="utf-8", errors="replace")
    if video_id in existing:
        return base  # same video, re-ingested

    message = (f"DUPLICATE TITLE: '{base}' already exists with a different video id; "
               f"storing {video_id} separately. Review before extraction — "
               f"near-duplicate talks double-count toward the >=2-source threshold.")
    # echo=True deliberately: progress output belongs to the caller, but a silent
    # duplicate corrupts the corpus, so this one gets said out loud as well as
    # returned in the result dict.
    _log(config, f"  {message}", echo=True)
    if warnings is not None:
        warnings.append(message)
    return f"{base}-{video_id[:6]}"


def write_transcript(config: Config, channel_slug: str, video_slug: str, video_id: str,
                     meta: dict, paragraphs: list[tuple[int, str]]) -> Path:
    """Write the immutable raw/ transcript."""
    path = config.raw_dir / channel_slug / f"{video_slug}.md"

    body = [f"# {meta['title']}", "",
            "> Machine-generated captions, normalized. Immutable — never edit by hand.",
            ""]
    body += [f"[{hhmmss(t)}] {text}" for t, text in paragraphs]

    write_md(path, "\n".join(body) + "\n", {
        "type": "raw-transcript",
        "immutable": True,
        "slug": f"{channel_slug}/{video_slug}",
        "youtube_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "published": iso_from_upload(meta["upload_date"]),
        "duration": hhmmss(meta["duration"]),
        "caption_source": "youtube-auto",
        "fetched": iso(),
    })
    return path


def write_source_stub(config: Config, channel_slug: str, video_slug: str, video_id: str,
                      meta: dict, paragraphs: list[tuple[int, str]]) -> Path:
    """Write the sources/ page. Description is a placeholder until extraction runs."""
    path = config.sources / channel_slug / f"{video_slug}.md"
    raw_rel = f"../../raw/{channel_slug}/{video_slug}.md"

    # Preserve any human-written summary across re-ingestion. Re-ingesting a video is
    # routine (a --force run, a re-listed channel); losing a hand-written thesis line
    # to it is not recoverable, so `summary_status: done` is never clobbered.
    existing_meta: dict = {}
    if path.exists():
        existing_meta, _ = read_md(path)

    summarized = existing_meta.get("summary_status") == "done"
    description = existing_meta.get("description") if summarized else \
        "Not yet summarized — run the extraction pass to write a thesis line."

    body = [
        f"# {meta['title']}",
        "",
        f"**{meta['channel']}** · {hhmmss(meta['duration'])} · "
        f"[watch](https://www.youtube.com/watch?v={video_id})",
        "",
    ]
    if not summarized:
        body += [
            "> **Stub.** Transcript is ingested; the summary and concept extraction",
            f"> have not run yet. Full text: [transcript]({raw_rel})",
            "",
            "## Outline",
            "",
        ]
        # A coarse time index gives the extraction pass somewhere to start.
        step = max(1, len(paragraphs) // 8)
        for t, text in paragraphs[::step][:8]:
            snippet = text[:110].rsplit(" ", 1)[0] if len(text) > 110 else text
            body.append(f"- `{hhmmss(t)}` — {snippet}…")
        body.append("")
    else:
        body += [f"See [transcript]({raw_rel}).", ""]

    write_md(path, "\n".join(body), {
        "type": "source",
        "source_type": "video",
        "title": meta["title"],
        "description": description,
        "channel": channel_slug,
        "youtube_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "slug": f"{channel_slug}/{video_slug}",
        "published": iso_from_upload(meta["upload_date"]),
        "duration": hhmmss(meta["duration"]),
        "raw": raw_rel,
        "summary_status": existing_meta.get("summary_status", "pending"),
        "created": existing_meta.get("created", iso()),
        "updated": iso(),
    })
    return path


def iso_from_upload(upload_date: str) -> str:
    """yt-dlp gives YYYYMMDD; the format wants YYYY-MM-DD."""
    return iso(upload_date)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def ingest(config: Config,
           channel_url: str,
           limit: int = 10,
           slug: str | None = None,
           dry_run: bool = False,
           sleep: float = DEFAULT_SLEEP,
           force: bool = False,
           progress: ProgressFn | None = None) -> dict:
    """Ingest up to `limit` not-yet-seen videos from `channel_url`.

    Args:
        config:      resolved knowledge base configuration.
        channel_url: channel URL or @handle page.
        limit:       max NEW videos to ingest this run.
        slug:        override the channel slug (default: slugified channel name).
        dry_run:     resolve what would be fetched and return without fetching.
        sleep:       seconds to wait between videos.
        force:       re-ingest videos already recorded in state.
        progress:    optional callable (index, total, video_id, title), called once
                     per video before it is fetched. This module never prints
                     progress itself — that is the caller's job.

    Returns a summary dict:
        {channel, slug, listed, already_ingested, pending, videos,
         written, skipped, total_ingested, warnings, dry_run}
    """
    _require_yt_dlp()

    state = State(config.state, JOB)
    channels: dict = state.setdefault("channels", {})

    _log(config, f"Listing videos for {channel_url}")
    # Over-fetch the listing so `limit` counts *new* videos, not listed ones.
    listing = list_channel_videos(channel_url,
                                  limit=None if force else max(limit * 5, 50))

    key = channel_url.rstrip("/")
    record: dict = dict(channels.get(key, {}))
    seen: set[str] = set(record.get("ingested", []))
    pending = [v for v in listing if force or v["id"] not in seen]
    batch = pending[:limit]

    # Reuse the slug this channel was previously ingested under, so a resumed run
    # cannot land the same channel in two different directories.
    slug_for_channel = slug or record.get("slug")

    result = {
        "channel": key,
        "slug": slug_for_channel,
        "listed": len(listing),
        "already_ingested": len(seen),
        "pending": len(pending),
        "videos": batch,
        "written": 0,
        "skipped": 0,
        "total_ingested": len(seen),
        "warnings": [],
        "dry_run": dry_run,
    }

    if dry_run or not batch:
        return result

    warnings: list[str] = result["warnings"]
    written = skipped = 0

    state.record_run()
    state.checkpoint()

    def _save() -> None:
        """Persist what has been ingested so far.

        The original implementation saved state once, after the loop. An interrupted
        run of 800 videos therefore recorded nothing and re-fetched everything on the
        next attempt. This is called after every successfully written video instead:
        a state write is a few milliseconds, a re-download is a network round trip
        plus a rate-limit risk. Cheap insurance, paid every iteration.
        """
        channels[key] = {
            "slug": slug_for_channel,
            "ingested": sorted(seen),
            "last_run": state.get("last_run"),
            "total_listed": len(listing),
        }
        state.set("channels", channels)
        state.checkpoint()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for i, video in enumerate(batch, 1):
            vid = video["id"]
            if progress is not None:
                progress(i, len(batch), vid, video["title"])

            meta = fetch_video(config, vid, workdir)
            if meta is None:
                skipped += 1
                continue

            if slug_for_channel is None:
                slug_for_channel = slugify(meta["channel"])
                _log(config, f"Channel slug resolved to '{slug_for_channel}'")

            cues = parse_json3(meta["captions_path"])
            paragraphs = cues_to_paragraphs(cues)
            if not paragraphs:
                _log(config, f"  {vid}: captions parsed to nothing, skipping")
                skipped += 1
                continue

            channel_dir = config.raw_dir / slug_for_channel
            channel_dir.mkdir(parents=True, exist_ok=True)
            video_slug = unique_slug(config, meta["title"], vid, channel_dir, warnings)

            write_transcript(config, slug_for_channel, video_slug, vid, meta, paragraphs)
            write_source_stub(config, slug_for_channel, video_slug, vid, meta, paragraphs)

            seen.add(vid)
            written += 1
            meta["captions_path"].unlink(missing_ok=True)

            # Checkpoint immediately: both pages for this video are on disk, so the
            # work is done and must not be repeated if the next fetch is interrupted.
            _save()

            if i < len(batch):
                time.sleep(sleep)

    # Final save covers the case where every video in the batch was skipped and the
    # loop never checkpointed — the run itself still happened.
    _save()

    _log(config, f"Ingested {written}, skipped {skipped}, total {len(seen)}")

    result.update({
        "slug": slug_for_channel,
        "written": written,
        "skipped": skipped,
        "total_ingested": len(seen),
    })
    return result
