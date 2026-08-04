"""
store.py — reading and writing the knowledge base on disk.

Replaces the `vault_io` module the original implementation borrowed from a personal
Obsidian setup. Everything here is deliberately boring: markdown files with YAML
frontmatter, JSON state, plain-text logs. No database, because the whole premise of
the format is that an agent can read the knowledge base with nothing but a filesystem.

Keep it that way. If something here starts wanting an index or a daemon, that belongs
in a consumer of this library, not in the store.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import frontmatter

# ---------------------------------------------------------------------------
# Markdown read / write
# ---------------------------------------------------------------------------


def read_md(path: str | Path) -> tuple[dict, str]:
    """Return (metadata, body) for a markdown file."""
    post = frontmatter.load(str(path))
    return dict(post.metadata), post.content


def write_md(path: str | Path, content: str, metadata: dict | None = None) -> Path:
    """Write markdown with YAML frontmatter, creating parent directories.

    Frontmatter keys are emitted in a stable order so that regenerating a file
    produces a clean diff rather than a reshuffle. That matters more than it
    sounds: these files live in git, and noisy diffs hide real changes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = dict(metadata or {})
    post = frontmatter.Post(content, **meta)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return path


def iter_md(root: str | Path, skip_hidden: bool = True) -> Iterator[Path]:
    """Yield every markdown file under `root`, sorted, skipping dotfiles."""
    root = Path(root)
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.md")):
        if skip_hidden and any(p.startswith(".") for p in path.relative_to(root).parts):
            continue
        yield path


# ---------------------------------------------------------------------------
# State — so long-running jobs are resumable
# ---------------------------------------------------------------------------


class State:
    """Small JSON store, one file per job.

    Exists because ingestion runs are long and interruptible. The original version
    saved state only after its loop finished, which meant an interrupted run of 800
    videos recorded nothing and re-fetched everything. `checkpoint()` is the fix and
    callers should use it liberally — a write is cheap, a re-download is not.
    """

    def __init__(self, directory: str | Path, name: str):
        self.path = Path(directory) / f"{name}.json"
        self.data: dict[str, Any] = {}
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                # A truncated state file should not be fatal; a lost checkpoint is
                # recoverable, an unstartable job is not.
                self.data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def setdefault(self, key: str, value: Any) -> Any:
        return self.data.setdefault(key, value)

    def checkpoint(self) -> None:
        """Persist now. Written to a temp file and moved, so an interrupt during
        write cannot leave a half-JSON file behind."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, default=str) + "\n",
                       encoding="utf-8")
        tmp.replace(self.path)

    def record_run(self) -> None:
        self.data["last_run"] = datetime.now().isoformat()
        self.data["run_count"] = int(self.data.get("run_count", 0)) + 1


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(directory: str | Path, job: str, message: str, echo: bool = False) -> None:
    """Append a timestamped line to `<directory>/<date>-<job>.log`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now()
    line = f"[{stamp:%H:%M:%S}] {message}\n"
    with open(directory / f"{stamp:%Y-%m-%d}-{job}.log", "a", encoding="utf-8") as fh:
        fh.write(line)
    if echo:
        print(message)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^\w\s-]")
_SLUG_SEP = re.compile(r"[\s_-]+")


def slugify(text: str, max_len: int = 60) -> str:
    """Stable kebab-case identifier. Filenames are identities in this format —
    they are what links point at — so this must stay deterministic across versions."""
    import unicodedata

    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = _SLUG_STRIP.sub("", text.lower())
    text = _SLUG_SEP.sub("-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text or "untitled"


def iso(value: Any = None) -> str:
    """Normalize anything date-ish to ISO YYYY-MM-DD. Defaults to today."""
    if value is None:
        return date.today().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().strip("'\"")
    if len(text) == 8 and text.isdigit():  # yt-dlp style YYYYMMDD
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def hhmmss(seconds: float | None) -> str:
    if not seconds:
        return "00:00:00"
    total = int(seconds)
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def parse_hhmmss(stamp: str) -> int:
    parts = [int(p) for p in str(stamp).strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]
