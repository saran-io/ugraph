"""
templates.py — access to the files shipped inside the wheel.

`okf init` copies these into a new knowledge base, and `config.taxonomy()` falls back to
the packaged vocabulary so a bare `init` produces something that lints. Kept in one place
because "where do the bundled files live" has two answers — installed wheel vs source
checkout — and every caller getting that wrong independently is how packaging bugs happen.
"""

from __future__ import annotations

from pathlib import Path


def _root(kind: str = "templates") -> Path:
    packaged = Path(__file__).parent / "_bundled" / kind
    if packaged.is_dir():
        return packaged
    repo = Path(__file__).resolve().parents[2] / kind
    if repo.is_dir():
        return repo
    raise FileNotFoundError(
        f"bundled {kind}/ not found — looked in {packaged} and {repo}"
    )


def path(name: str, kind: str = "templates") -> Path:
    """Absolute path to a bundled file."""
    candidate = _root(kind) / name
    if not candidate.exists():
        raise FileNotFoundError(f"no bundled {kind} file named {name!r}")
    return candidate


def read(name: str, kind: str = "templates") -> str:
    """Contents of a bundled file."""
    return path(name, kind).read_text(encoding="utf-8")
