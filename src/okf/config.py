"""
config.py — where the knowledge base lives, and what vocabulary it uses.

This module exists because the original implementation hardcoded a single Obsidian
vault path. Everything else in the toolchain was already portable; only the root was
not. Resolving the root from config instead of an import is what turns a personal
script into a tool other people can run.

Resolution order for the KB root, first hit wins:
    1. explicit --kb argument              (CLI flag)
    2. OKF_KB environment variable
    3. `kb` key in the nearest okf.toml    (walking up from cwd)
    4. the directory containing okf.toml
    5. cwd, if it looks like a KB (has SCHEMA.md or concepts/)

A KB is just a directory. It can sit inside an Obsidian vault, a git repo, or
nowhere in particular — the format does not care, which is the point.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # stdlib from 3.11; the backport is a dependency below that
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

CONFIG_FILENAME = "okf.toml"

# Directories that make up an OKF bundle. Created by `okf init`.
#
# `_mocs` is here because it is part of the strict tree (see OKF_DIRS) and so is held
# to the no-wikilink rule. Scaffolding it but leaving it empty was a real oversight:
# a directory the linter polices should exist, or the first person to create one
# discovers the rule by tripping over it.
CONTENT_DIRS = ("concepts", "entities/tools", "entities/people",
                "entities/organizations", "sources", "raw", "_mocs")

# The strict tree — pages here are traversed by agents and may not use [[wikilinks]].
# Anything else in the KB root is treated as a human-facing note.
OKF_DIRS = frozenset({"concepts", "entities", "sources", "_mocs"})

RESERVED_NAMES = frozenset({"index.md", "README.md", "SCHEMA.md"})


class ConfigError(RuntimeError):
    """Raised when the KB root cannot be resolved or the config is malformed."""


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default cwd) looking for okf.toml."""
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _looks_like_kb(path: Path) -> bool:
    return (path / "SCHEMA.md").is_file() or (path / "concepts").is_dir()


@dataclass
class Config:
    """Resolved configuration for one knowledge base."""

    kb: Path
    taxonomy_path: Path | None = None
    state_dir: Path | None = None
    log_dir: Path | None = None
    source_dirs: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # -- derived paths -----------------------------------------------------

    @property
    def concepts(self) -> Path:
        return self.kb / "concepts"

    @property
    def entities(self) -> Path:
        return self.kb / "entities"

    @property
    def sources(self) -> Path:
        return self.kb / "sources"

    @property
    def raw_dir(self) -> Path:
        return self.kb / "raw"

    @property
    def mocs(self) -> Path:
        return self.kb / "_mocs"

    @property
    def schema(self) -> Path:
        return self.kb / "SCHEMA.md"

    @property
    def candidates(self) -> Path:
        """Phase A output. Deliberately outside the KB — these are working files,
        not knowledge, and should not be linted or indexed as pages.

        A configured relative path resolves against the KB root, like every other
        path in okf.toml. Returning it unresolved made `candidates = "some/dir"`
        silently resolve against the working directory instead, so the setting
        appeared to do nothing depending on where you ran the command from.
        """
        configured = self.raw.get("candidates")
        if not configured:
            return self.kb.parent / ".okf" / "candidates"
        path = Path(configured).expanduser()
        return path if path.is_absolute() else (self.kb / path).resolve()

    @property
    def state(self) -> Path:
        return self.state_dir or (self.kb.parent / ".okf" / "state")

    @property
    def logs(self) -> Path:
        return self.log_dir or (self.kb.parent / ".okf" / "logs")

    def taxonomy(self) -> dict:
        """Load the closed vocabulary. Falls back to the packaged default so a
        bare `okf init` works without the user writing one."""
        if self.taxonomy_path and self.taxonomy_path.is_file():
            return json.loads(self.taxonomy_path.read_text(encoding="utf-8"))
        packaged = self.kb / "taxonomy.json"
        if packaged.is_file():
            return json.loads(packaged.read_text(encoding="utf-8"))
        from okf import templates
        return json.loads(templates.read("taxonomy.json"))

    def is_okf_page(self, path: Path) -> bool:
        """True if `path` is in the strict tree (or is a KB-root document)."""
        try:
            rel = Path(path).resolve().relative_to(self.kb.resolve())
        except ValueError:
            return False
        if len(rel.parts) == 1:
            return True
        return rel.parts[0] in OKF_DIRS


def load(kb: str | Path | None = None, start: Path | None = None) -> Config:
    """Resolve a Config. See module docstring for the resolution order."""
    data: dict[str, Any] = {}
    config_path = find_config(start)
    if config_path:
        try:
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:  # malformed TOML is worth failing loudly on
            raise ConfigError(f"cannot parse {config_path}: {exc}") from exc

    root: Path | None = None
    if kb:
        root = Path(kb).expanduser()
    elif os.environ.get("OKF_KB"):
        root = Path(os.environ["OKF_KB"]).expanduser()
    elif config_path:
        configured = data.get("kb")
        root = (Path(configured).expanduser() if configured else config_path.parent)
        if not root.is_absolute():
            root = (config_path.parent / root).resolve()
    elif _looks_like_kb(Path.cwd()):
        root = Path.cwd()

    if root is None:
        raise ConfigError(
            "cannot find a knowledge base.\n"
            "  Pass --kb PATH, set OKF_KB, or run inside a directory containing "
            f"{CONFIG_FILENAME}.\n"
            "  To create one:  okf init ./my-kb"
        )

    root = root.expanduser().resolve()

    def _opt(key: str) -> Path | None:
        value = data.get(key)
        if not value:
            return None
        path = Path(value).expanduser()
        return path if path.is_absolute() else (root / path)

    return Config(
        kb=root,
        taxonomy_path=_opt("taxonomy"),
        state_dir=_opt("state_dir"),
        log_dir=_opt("log_dir"),
        source_dirs=dict(data.get("sources", {})),
        raw=data,
    )
