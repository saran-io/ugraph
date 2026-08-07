"""Resolve a person from a YouTube URL and add a minimal, verified KB record."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from ugraph.config import Config
from ugraph.store import read_md, slugify, write_md

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


class PersonResolutionError(RuntimeError):
    """The supplied URL could not be resolved to one verified identity."""


@dataclass(frozen=True)
class Person:
    name: str
    handle: str
    profile_url: str
    source_url: str
    source_title: str


@dataclass(frozen=True)
class AddPersonResult:
    person: Person
    canonical_path: Path
    redirect_path: Path
    created: bool


def is_supported_url(value: str) -> bool:
    """Return whether value is exactly one HTTP(S) YouTube URL."""
    value = value.strip()
    if not value or any(ch.isspace() for ch in value):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in YOUTUBE_HOSTS


def resolve(url: str) -> Person:
    """Resolve channel identity deterministically through yt-dlp, never an LLM."""
    if not is_supported_url(url):
        raise PersonResolutionError("v1 supports YouTube video, channel, and profile URLs only")
    if shutil.which("yt-dlp") is None:
        raise PersonResolutionError(
            "yt-dlp is unavailable; reinstall ugraph-kit or install yt-dlp"
        )

    result = subprocess.run(
        [
            "yt-dlp",
            "--skip-download",
            "--no-warnings",
            "--playlist-items",
            "1",
            "--dump-single-json",
            url.strip(),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()[-500:] or "unknown yt-dlp error"
        raise PersonResolutionError(f"could not read YouTube metadata: {detail}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PersonResolutionError("YouTube metadata was not valid JSON") from exc

    entry = (data.get("entries") or [{}])[0] or {}

    def first(*keys: str) -> str:
        for key in keys:
            value = data.get(key) or entry.get(key)
            if value:
                return str(value).strip()
        return ""

    name = first("channel", "uploader", "playlist_uploader")
    handle = first("uploader_id", "channel_id")
    profile_url = first("channel_url", "uploader_url")
    title = first("title", "playlist_title") or "YouTube source"

    if handle and not handle.startswith("@") and profile_url:
        match = re.search(r"youtube\.com/(@[^/?#]+)", profile_url)
        if match:
            handle = match.group(1)
    if not name:
        raise PersonResolutionError("YouTube returned no creator/channel name for this URL")
    if not profile_url and handle.startswith("@"):
        profile_url = f"https://www.youtube.com/{handle}"
    if not profile_url:
        raise PersonResolutionError("YouTube returned no creator profile URL for this source")

    # Keep the exact URL, including ?t=. That moment is often why the user saved it.
    return Person(name, handle, profile_url, url.strip(), title)


def _existing_for(config: Config, person: Person) -> Path | None:
    directory = config.entities / "people"
    if not directory.is_dir():
        return None
    target_handle = person.handle.casefold()
    target_url = person.profile_url.rstrip("/").casefold()
    for path in directory.glob("*.md"):
        try:
            meta, _ = read_md(path)
        except Exception as exc:
            raise PersonResolutionError(
                f"cannot inspect existing person page {path}: {exc}"
            ) from exc
        resource = str(meta.get("resource") or "").rstrip("/").casefold()
        handles = {str(handle).casefold() for handle in (meta.get("handles") or [])}
        if resource == target_url or (target_handle and target_handle in handles):
            return path
    return None


def _slug(config: Config, person: Person) -> str:
    existing = _existing_for(config, person)
    if existing:
        return existing.stem
    base = slugify(person.name)
    candidate = config.entities / "people" / f"{base}.md"
    if not candidate.exists():
        return base
    suffix = slugify(person.handle.lstrip("@")) if person.handle else "youtube"
    return f"{base}-{suffix}"


def _write_redirect(config: Config, slug: str, person: Person) -> Path:
    redirect = config.kb / "resources" / "people" / f"{slug}.md"
    relative = f"../../entities/people/{slug}.md"
    body = (
        f"# {person.name}\n\n"
        "> **This note moved.** Its content now lives at\n"
        f"> [{person.name}]({relative}) as part of the knowledge base.\n\n"
        "This stub exists only so existing links elsewhere in the vault keep resolving.\n"
        "Don't add content here — edit the canonical page instead."
    )
    return write_md(
        redirect,
        body,
        {
            "type": "overview",
            "title": person.name,
            "description": "Redirect to the canonical person page.",
            "moved_to": relative,
            "updated": date.today().isoformat(),
        },
    )


def add(config: Config, person: Person) -> AddPersonResult:
    """Create a canonical page once; repeated calls never overwrite human edits."""
    slug = _slug(config, person)
    canonical = config.entities / "people" / f"{slug}.md"
    created = not canonical.exists()
    today = date.today().isoformat()

    if created:
        handle_note = f" ({person.handle})" if person.handle else ""
        body = (
            f"# {person.name}\n\n"
            f"YouTube creator{handle_note}, added from a source supplied to ugraph.\n\n"
            "## Where to follow\n\n"
            f"- YouTube — [{person.handle or person.name}]({person.profile_url})\n\n"
            "## Discovered from\n\n"
            f"- [{person.source_title}]({person.source_url})\n"
        )
        write_md(
            canonical,
            body,
            {
                "type": "entity",
                "subtype": "person",
                "title": person.name,
                "description": f"YouTube creator{handle_note}; added from a supplied source.",
                "resource": person.profile_url,
                "handles": [person.handle] if person.handle else [],
                "tags": ["youtube"],
                "discovered_from": [person.source_url],
                "created": today,
                "updated": today,
            },
        )

    redirect = _write_redirect(config, slug, person)
    return AddPersonResult(person, canonical, redirect, created)
